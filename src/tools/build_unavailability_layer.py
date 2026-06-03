from pathlib import Path
import sys
import pandas as pd


def _read_csv_if_exists(path_str: str, required_columns: list[str]) -> pd.DataFrame:
    if not path_str:
        return pd.DataFrame(columns=required_columns)
    path = Path(path_str)
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame(columns=required_columns)

    df = pd.read_csv(path)
    for col in required_columns:
        if col not in df.columns:
            df[col] = ""
    return df[required_columns].copy()


def build_unavailability_layer(
    weekday_unavailability_csv: str,
    weekend_unavailability_csv: str,
    absences_unavailability_csv: str,
    guard_constraints_csv: str,
    output_csv: str,
) -> None:
    base_cols = ["professional_id", "day", "franja", "presentiality", "reason", "source", "notes"]

    def _ensure_filters(df: pd.DataFrame) -> pd.DataFrame:
        for col in ("franja", "presentiality"):
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
        return df

    weekday_df = _read_csv_if_exists(
        weekday_unavailability_csv,
        ["professional_id", "day", "reason"],
    )
    if not weekday_df.empty:
        weekday_df["source"] = "weekday_manual"
        weekday_df["notes"] = ""
        weekday_df = _ensure_filters(weekday_df)

    weekend_df = _read_csv_if_exists(
        weekend_unavailability_csv,
        ["professional_id", "day", "reason"],
    )
    if not weekend_df.empty:
        weekend_df["source"] = "weekend_manual"
        weekend_df["notes"] = ""
        weekend_df = _ensure_filters(weekend_df)

    absences_df = _read_csv_if_exists(
        absences_unavailability_csv,
        ["professional_id", "day", "reason", "source", "notes"],
    )
    if not absences_df.empty:
        absences_df = _ensure_filters(absences_df)

    guards_df_raw = _read_csv_if_exists(
        guard_constraints_csv,
        ["professional_id", "day", "constraint_type", "source_guard_kind", "notes"],
    )

    if not guards_df_raw.empty:
        # post_guard_free → dia després d'una guàrdia: bloqueja totes les
        # assignacions PRESENCIAL (a qualsevol franja). Els slots
        # NO_PRESENCIAL queden disponibles a totes les franges, perquè
        # el post-guàrdia pugui omplir un slot lleuger. Si el solver flipa
        # un d'aquests NP a PRES (per assolir el target presencial via
        # `pres_flip`), aquesta assignació és la "presencial de
        # postguàrdia" — el facultatiu hi compleix part del seu target
        # PRES setmanal sense haver de fer un PRES "dur" del calendari.
        post_guard_base = guards_df_raw.loc[
            guards_df_raw["constraint_type"] == "post_guard_free",
            ["professional_id", "day", "notes"]
        ].copy()
        if not post_guard_base.empty:
            parts = []
            for _franja in ("MATI", "TARDA", "NIT"):
                sub = post_guard_base.copy()
                sub["franja"] = _franja
                sub["presentiality"] = "PRESENCIAL"
                parts.append(sub)
            post_guard = pd.concat(parts, ignore_index=True)
        else:
            post_guard = post_guard_base
            post_guard["franja"] = ""        # no hi ha files; columna per uniformitat
            post_guard["presentiality"] = ""
        post_guard["reason"] = "post_guard_free"
        post_guard["source"] = "guards"

        # guard_day → same-day block. Semantics by guard kind:
        #   - guardia: block ALL slots in TARDA *i NIT* (la tarda és de
        #     descans i la nit és la pròpia guàrdia). El MATÍ queda lliure:
        #     s'hi prioritza NO_PRESENCIAL (teletreball) via el terme tou
        #     _add_guard_morning_telework_terms.
        #   - refuerzo: block all slots in TARDA (reforç a l'hospital la tarda).
        guard_day_src = guards_df_raw.loc[
            guards_df_raw["constraint_type"] == "guard_day",
            ["professional_id", "day", "source_guard_kind", "notes"]
        ].copy()
        if not guard_day_src.empty:
            _kind_franjas = {"guardia": ["TARDA", "NIT"], "refuerzo": ["TARDA"]}
            _kind_reason = {"guardia": "guardia_day_tarda", "refuerzo": "refuerzo_afternoon"}
            _rows = []
            for gr in guard_day_src.itertuples(index=False):
                kind = str(getattr(gr, "source_guard_kind", "") or "").strip().lower()
                for _fr in _kind_franjas.get(kind, ["TARDA"]):
                    _rows.append({
                        "professional_id": gr.professional_id,
                        "day": gr.day,
                        "franja": _fr,
                        "presentiality": "",
                        "reason": _kind_reason.get(kind, "guard_day"),
                        "source": "guards",
                        "notes": getattr(gr, "notes", ""),
                    })
            guard_day = pd.DataFrame(_rows, columns=base_cols)
        else:
            guard_day = guard_day_src

        guards_df = pd.concat(
            [post_guard[base_cols], guard_day[base_cols] if not guard_day.empty else pd.DataFrame(columns=base_cols)],
            ignore_index=True,
        )
    else:
        guards_df = pd.DataFrame(columns=base_cols)

    frames = []

    if not weekday_df.empty:
        frames.append(weekday_df[base_cols])

    if not weekend_df.empty:
        frames.append(weekend_df[base_cols])

    if not absences_df.empty:
        frames.append(absences_df[base_cols])

    if not guards_df.empty:
        frames.append(guards_df)

    if frames:
        out = pd.concat(frames, ignore_index=True)
        out["day"] = out["day"].astype(str)
        out["professional_id"] = out["professional_id"].astype(str)
        out["franja"] = out["franja"].fillna("").astype(str).str.strip().str.upper()
        out["presentiality"] = out["presentiality"].fillna("").astype(str).str.strip().str.upper()
        out["reason"] = out["reason"].astype(str)
        out["source"] = out["source"].astype(str)
        out["notes"] = out["notes"].fillna("").astype(str)

        out = out.drop_duplicates(subset=["professional_id", "day", "franja", "presentiality", "reason", "source"])
        out = out.sort_values(["day", "professional_id", "franja", "presentiality", "reason", "source"]).reset_index(drop=True)
    else:
        out = pd.DataFrame(columns=base_cols)

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_csv, index=False)

    # Conflictes: el mateix facultatiu té una guàrdia/reforç/postguàrdia i
    # alhora una absència real el mateix dia. Es notifica per stdout amb un
    # marcador que la UI captura i mostra com a avís.
    if not out.empty:
        _guard_reasons = {
            "guardia_day_tarda", "refuerzo_afternoon", "post_guard_free",
        }
        g = out[(out["source"] == "guards") & out["reason"].isin(_guard_reasons)]
        a = out[out["source"] == "absences"]
        if not g.empty and not a.empty:
            gkeys = set(zip(g["professional_id"], g["day"]))
            akeys = set(zip(a["professional_id"], a["day"]))
            conflicts = sorted(gkeys & akeys)
            for prof, day in conflicts:
                print(f"CONFLICTE_GUARDIA_ABSENCIA\t{prof}\t{day}")
            if conflicts:
                print(
                    f"AVIS_GUARDIA_ABSENCIA: {len(conflicts)} conflicte(s) "
                    "entre guàrdia i indisponibilitat (mateix facultatiu i dia)."
                )

    print(f"Capa unificada de indisponibilidades generada en: {output_csv}")
    print(f"Total filas: {len(out)}")


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(
            "Uso: python -m src.tools.build_unavailability_layer "
            "<weekday_unavailability_csv> <weekend_unavailability_csv> "
            "<absences_unavailability_csv> <guard_constraints_csv> <output_csv>"
        )
        sys.exit(1)

    build_unavailability_layer(
        weekday_unavailability_csv=sys.argv[1],
        weekend_unavailability_csv=sys.argv[2],
        absences_unavailability_csv=sys.argv[3],
        guard_constraints_csv=sys.argv[4],
        output_csv=sys.argv[5],
    )
