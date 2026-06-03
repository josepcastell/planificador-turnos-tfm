from pathlib import Path
import sys
import pandas as pd


WEEKDAY_MAP = {
    0: "MONDAY",
    1: "TUESDAY",
    2: "WEDNESDAY",
    3: "THURSDAY",
    4: "FRIDAY",
}


def _doubled_slots_from_professionals(
    professionals_csv: str = "data/professionals.csv",
) -> set[str]:
    """Conjunt d'slot_ids (en majúscules) que algun facultatiu té marcat
    com a doblat (columna `doubled_machines` de professionals.csv).
    Aquests slots s'auto-dobaràn al calendari (PRES + NP) quan
    apareguin a les plantilles."""
    p = Path(professionals_csv)
    if not p.exists() or p.stat().st_size == 0:
        return set()
    try:
        df = pd.read_csv(p)
    except Exception:
        return set()
    if "doubled_machines" not in df.columns:
        return set()
    out: set[str] = set()
    for value in df["doubled_machines"].fillna("").astype(str):
        for item in value.split(";"):
            item = item.strip().upper()
            if item and item not in {"NAN", "NONE", "NA"}:
                out.add(item)
    return out


def build_weekday_calendar_from_templates(
    base_calendar_csv: str,
    weekly_templates_csv: str,
    overrides_csv: str,
    output_csv: str,
    slot_catalog_csv: str | None = "data/slot_catalog.csv",
    professionals_csv: str | None = "data/professionals.csv",
) -> None:
    base = pd.read_csv(base_calendar_csv)
    templates = pd.read_csv(weekly_templates_csv)

    required_base = {"day", "is_working_day"}
    required_templates = {
        "weekday_name", "franja", "slot_id",
        "presentiality", "work_mode", "is_active"
    }

    missing_base = required_base - set(base.columns)
    missing_templates = required_templates - set(templates.columns)

    if missing_base:
        raise ValueError(f"Falten columnes a base_calendar: {missing_base}")
    if missing_templates:
        raise ValueError(f"Falten columnes a weekly_templates: {missing_templates}")

    base["day"] = pd.to_datetime(base["day"], errors="coerce")
    base = base.dropna(subset=["day"]).copy()
    base = base[base["is_working_day"] == 1].copy()
    base = base[base["day"].dt.weekday <= 4].copy()
    base["weekday_name"] = base["day"].dt.weekday.map(WEEKDAY_MAP)

    # Slots de revisió: definits NOMÉS al catàleg. S'ignoren les files de
    # Franges de treball per a aquests slots (poden ser-hi de seedings
    # antics) i s'instancien automàticament des del catàleg més avall.
    review_slots: list[str] = []
    if slot_catalog_csv and Path(slot_catalog_csv).exists():
        from src.services.slot_catalog import (
            load_slot_catalog,
            review_slot_ids,
            weekday_slot_ids,
        )

        _cat = load_slot_catalog(Path(slot_catalog_csv))
        _wkd = {str(s).strip().upper() for s in weekday_slot_ids(_cat)}
        review_slots = sorted(
            {str(s).strip().upper() for s in review_slot_ids(_cat)} & _wkd
        )
    _review_set = set(review_slots)

    templates = templates.copy()
    templates = templates[templates["is_active"] == 1].copy()
    # Filtra slots de revisió del template: la seva instància l'aporta el
    # bloc dedicat (review_rows) sempre com a NO_PRESENCIAL i MATÍ. La
    # condició és ÚNICAMENT pel catàleg (review=1 a l'editor d'activitats):
    # no identifiquem revisions pel nom de l'slot. Si el catàleg no marca
    # un slot com a revisió, es tracta com a slot ordinari (encara que el
    # nom comenci per REV).
    if _review_set and "slot_id" in templates.columns:
        slot_upper = templates["slot_id"].astype(str).str.strip().str.upper()
        templates = templates.loc[~slot_upper.isin(_review_set)].copy()
    templates["presentiality"] = templates["presentiality"].fillna("PRESENCIAL").astype(str)
    # MODEL DE PEONADES: work_mode del template ja no diferencia
    # peonada vs ordinària; tot és NORMAL al calendari operatiu. Les
    # peonades les decideix el solver (vegeu _add_peonada_monthly_cap).
    # Normalitzem aquí perquè el solver no vegi mai PEONADA com a input.
    templates["work_mode"] = "NORMAL"

    # NOU MODEL DE DOBLAT: cada fila del template equival ara a UNA fila
    # del calendari operatiu (posició única). Si encara hi ha files
    # legacy amb doubled=1 i presentiality=PRESENCIAL, les migrem aquí
    # afegint la sibling NO_PRESENCIAL per al segon facultatiu. Així el
    # comportament històric (1 fila → 2 posicions PRES + NP) queda
    # preservat sense necessitat de reescriure el CSV de templates.
    if "doubled" in templates.columns:
        templates["doubled"] = (
            pd.to_numeric(templates["doubled"], errors="coerce").fillna(0).astype(int).clip(0, 1)
        )
        legacy_pres_doubled = (
            (templates["doubled"] == 1)
            & (templates["presentiality"].astype(str).str.upper() == "PRESENCIAL")
        )
        if legacy_pres_doubled.any():
            siblings = templates.loc[legacy_pres_doubled].copy()
            siblings["presentiality"] = "NO_PRESENCIAL"
            templates = pd.concat([templates, siblings], ignore_index=True)
        # El flag doubled ja no condiciona l'expansió: cada fila és única.
        templates["doubled"] = 0

    # Normalitza required_staff (mínim 1).
    if "required_staff" in templates.columns:
        templates["required_staff"] = (
            pd.to_numeric(templates["required_staff"], errors="coerce")
            .fillna(1).astype(int).clip(lower=1)
        )
    else:
        templates["required_staff"] = 1

    rows = []
    for row in base.itertuples(index=False):
        tpl = templates[templates["weekday_name"] == row.weekday_name]
        for t in tpl.itertuples(index=False):
            # Expandeix `required_staff` instàncies per a aquesta plantilla:
            # cada instància obté una `position` incremental dins del mateix
            # (day, franja, slot, pres, wm) — el solver les distingeix com
            # a slots independents (claus diferents per `_make_slot_key`).
            n = max(1, int(getattr(t, "required_staff", 1) or 1))
            for pos in range(1, n + 1):
                rows.append({
                    "day": row.day.strftime("%Y-%m-%d"),
                    "franja": str(t.franja),
                    "slot_id": str(t.slot_id),
                    "presentiality": str(t.presentiality),
                    "work_mode": str(t.work_mode),
                    "position": pos,
                })

    out = pd.DataFrame(
        rows,
        columns=["day", "franja", "slot_id", "presentiality", "work_mode", "position"],
    )

    # ── Auto-doblat per facultatiu (CONDICIONAL) ──────────────────────
    # Per cada slot que algun facultatiu té a la seva llista
    # `doubled_machines`, afegim una posició 2 PRES a cada ocurrència
    # del calendari. Aquesta posició 2 és **opcional al solver**:
    # només quedarà filled si un dels facultatius marcats és assignat
    # al slot (vegeu `_add_conditional_doubling_constraints` a
    # `solver/core.py`). Quan no hi ha cap marcat → pos2 queda buida
    # (slot single).
    doubled_slots = (
        _doubled_slots_from_professionals(professionals_csv)
        if professionals_csv else set()
    )
    if doubled_slots and not out.empty:
        sid_col = out["slot_id"].astype(str).str.strip().str.upper()
        is_candidate = sid_col.isin(doubled_slots)
        pres_col = out["presentiality"].astype(str).str.upper()
        candidates_df = out.loc[is_candidate & (pres_col == "PRESENCIAL")].copy()
        if not candidates_df.empty:
            candidates_df["_sid"] = candidates_df["slot_id"].astype(str).str.upper()
            grouped = candidates_df.groupby(
                ["day", "franja", "_sid"], dropna=False
            )["position"].agg(["count", "max"])
            extra_rows = []
            for (day, franja, sid), agg in grouped.iterrows():
                cnt = int(agg["count"])
                cur_max = int(agg["max"]) if pd.notna(agg["max"]) else 0
                # Cal arribar a 2 instàncies PRES (afegim si en falten).
                need = max(0, 2 - cnt)
                for k in range(1, need + 1):
                    extra_rows.append({
                        "day": day, "franja": franja, "slot_id": sid,
                        "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
                        "position": cur_max + k,
                    })
            if extra_rows:
                out = pd.concat([out, pd.DataFrame(extra_rows)], ignore_index=True)
        out = out.drop_duplicates(
            subset=["day", "franja", "slot_id", "presentiality", "work_mode", "position"],
            keep="first",
        ).reset_index(drop=True)

    # Slots de revisió definits al catàleg: una instància per dia laborable
    # (dia sencer, NO_PRESENCIAL). El solver els tracta amb continuïtat i
    # els exclou de la quota.
    if review_slots:
        review_rows = [
            {
                "day": row.day.strftime("%Y-%m-%d"),
                "franja": "MATI",
                "slot_id": sid,
                "presentiality": "NO_PRESENCIAL",
                "work_mode": "NORMAL",
                "position": 1,
            }
            for row in base.itertuples(index=False)
            for sid in review_slots
        ]
        out = pd.concat([out, pd.DataFrame(review_rows)], ignore_index=True)

    overrides_path = Path(overrides_csv)
    if overrides_path.exists() and overrides_path.stat().st_size > 0:
        overrides = pd.read_csv(overrides_csv)

        required_overrides = {
            "day", "franja", "slot_id",
            "presentiality", "work_mode", "action"
        }
        missing_overrides = required_overrides - set(overrides.columns)
        if missing_overrides:
            raise ValueError(f"Falten columnes a overrides: {missing_overrides}")

        overrides["day"] = pd.to_datetime(overrides["day"], errors="coerce")
        overrides = overrides.dropna(subset=["day"]).copy()
        overrides["day"] = overrides["day"].dt.strftime("%Y-%m-%d")
        overrides["franja"] = overrides["franja"].astype(str)
        overrides["slot_id"] = overrides["slot_id"].astype(str)
        overrides["presentiality"] = overrides["presentiality"].fillna("PRESENCIAL").astype(str)
        # NOU MODEL: les peonades les decideix el solver, no els overrides.
        overrides["work_mode"] = "NORMAL"
        overrides["action"] = overrides["action"].astype(str).str.lower().str.strip()
        if "required_staff" not in overrides.columns:
            overrides["required_staff"] = 1
        overrides["required_staff"] = pd.to_numeric(
            overrides["required_staff"], errors="coerce"
        ).fillna(1).astype(int).clip(lower=1)

        for ov in overrides.itertuples(index=False):
            mask = (
                (out["day"] == ov.day) &
                (out["franja"] == ov.franja) &
                (out["slot_id"] == ov.slot_id) &
                (out["presentiality"] == ov.presentiality) &
                (out["work_mode"] == ov.work_mode)
            )

            if ov.action == "remove":
                out = out.loc[~mask].copy()
            elif ov.action == "add":
                if not mask.any():
                    n = int(ov.required_staff)
                    new_rows = [
                        {
                            "day": ov.day,
                            "franja": ov.franja,
                            "slot_id": ov.slot_id,
                            "presentiality": ov.presentiality,
                            "work_mode": ov.work_mode,
                            "position": position,
                        }
                        for position in range(1, n + 1)
                    ]
                    out = pd.concat([out, pd.DataFrame(new_rows)], ignore_index=True)
            else:
                raise ValueError(f"Acció no reconeguda a overrides: {ov.action}")

    out = out.drop_duplicates().sort_values(
        ["day", "franja", "slot_id", "presentiality", "work_mode", "position"]
    ).reset_index(drop=True)

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_csv, index=False)

    print(f"Calendari laborable amb franges generat a: {output_csv}")
    print(f"Total files: {len(out)}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "Ús: python -m src.tools.build_weekday_calendar_from_templates "
            "<base_calendar_csv> <weekly_templates_csv> <overrides_csv> <output_csv>"
        )
        sys.exit(1)

    build_weekday_calendar_from_templates(
        base_calendar_csv=sys.argv[1],
        weekly_templates_csv=sys.argv[2],
        overrides_csv=sys.argv[3],
        output_csv=sys.argv[4],
    )
