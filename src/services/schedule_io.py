"""Helpers d'E/S i scoping del planning, reutilitzats pel generador
d'entre setmana (`src/tools/generate_planning_part.py`):

  · filter_module_to_month — filtra les dades del mòdul al mes lògic.
  · export_schedule — escriu l'schedule (amb is_flipped) a CSV.
  · load_stability_assignments — carrega el pla anterior per a reajustos.
  · enrich_schedule_with_slot_metadata — afegeix reporting_machine i, si
    cal, presencialitat/work_mode a l'schedule generat.

(Abans vivien a `src/main.py`, que feia de fals punt d'entrada amb un
`logging.basicConfig` al import; el pipeline mensual llegat ja s'havia
eliminat. Ara són helpers de servei sense efectes col·laterals.)
"""
from pathlib import Path
import csv

import pandas as pd


def filter_module_to_month(module_data: dict, year: int, month: int) -> dict:
    """Filtra a "totes les setmanes ISO que pertanyen al mes" (regla:
    una setmana pertany al mes del seu DILLUNS). Així una setmana que
    travessa el límit del mes queda assignada a un sol dels mesos."""
    from src.domain.month_scope import in_logical_month
    out = {}
    for key, value in module_data.items():
        if isinstance(value, pd.DataFrame) and "day" in value.columns:
            df = value.copy()
            days = pd.to_datetime(df["day"], errors="coerce")
            out[key] = df.loc[in_logical_month(days, year, month)].copy()
        else:
            out[key] = value
    return out


def export_schedule(rows, path_str: str) -> None:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # is_flipped (7a columna): marca slots NO_PRES forçats a PRES
        # via pres_flip. La UI ho mostra amb prefix "T-".
        has_flip = bool(rows) and len(rows[0]) >= 7
        has_meta = bool(rows) and len(rows[0]) >= 6
        if has_flip:
            writer.writerow([
                "day", "franja", "slot_id", "professional",
                "presentiality", "work_mode", "is_flipped",
            ])
            writer.writerows([r[:7] for r in rows])
        elif has_meta:
            writer.writerow(
                ["day", "franja", "slot_id", "professional", "presentiality", "work_mode"]
            )
            writer.writerows([r[:6] for r in rows])
        else:
            writer.writerow(["day", "franja", "slot_id", "professional"])
            writer.writerows([r[:4] for r in rows])


def load_stability_assignments(path_str: str | None, year: int, month: int) -> pd.DataFrame | None:
    if not path_str:
        return None

    path = Path(path_str)
    if not path.exists() or path.stat().st_size == 0:
        return None

    df = pd.read_csv(path)
    if "day" not in df.columns:
        return None

    from src.domain.month_scope import in_logical_month
    days = pd.to_datetime(df["day"], errors="coerce")
    return df.loc[in_logical_month(days, year, month)].copy()


def enrich_schedule_with_slot_metadata(schedule_csv_path: str) -> None:
    schedule_path = Path(schedule_csv_path)
    if not schedule_path.exists() or schedule_path.stat().st_size == 0:
        return

    schedule_df = pd.read_csv(schedule_path)
    required = {"day", "franja", "slot_id", "professional"}
    if not required.issubset(schedule_df.columns):
        return

    meta_frames = []

    weekday_path = Path("data/weekday/calendar_slots.csv")
    if weekday_path.exists() and weekday_path.stat().st_size > 0:
        weekday_meta = pd.read_csv(weekday_path)
        required_meta = {"day", "franja", "slot_id", "presentiality", "work_mode"}
        if required_meta.issubset(weekday_meta.columns):
            if "reporting_machine" not in weekday_meta.columns:
                weekday_meta["reporting_machine"] = ""
            meta_frames.append(
                weekday_meta[["day", "franja", "slot_id", "reporting_machine", "presentiality", "work_mode"]]
            )

    # La presencialitat/work_mode ja vénen decidides pel solver (export_schedule
    # les escriu). Aquí NOMÉS afegim reporting_machine i només re-derivem
    # presencialitat si falta (compat amb schedules antics).
    has_solver_pres = (
        "presentiality" in schedule_df.columns
        and not schedule_df["presentiality"].isna().all()
        and (schedule_df["presentiality"].astype(str).str.upper() != "NO_DEFINIT").any()
    )

    if not meta_frames:
        if "presentiality" not in schedule_df.columns:
            schedule_df["presentiality"] = "NO_DEFINIT"
        if "work_mode" not in schedule_df.columns:
            schedule_df["work_mode"] = "NO_DEFINIT"
        schedule_df["reporting_machine"] = ""
    elif has_solver_pres:
        slot_meta = (
            pd.concat(meta_frames, ignore_index=True)
            [["day", "franja", "slot_id", "reporting_machine"]]
            .drop_duplicates(subset=["day", "franja", "slot_id"])
        )
        schedule_df = schedule_df.merge(
            slot_meta, on=["day", "franja", "slot_id"], how="left"
        )
        schedule_df["reporting_machine"] = schedule_df["reporting_machine"].fillna("")
        schedule_df["presentiality"] = schedule_df["presentiality"].fillna("NO_DEFINIT")
        schedule_df["work_mode"] = schedule_df["work_mode"].fillna("NO_DEFINIT")
    else:
        # Fallback (schedules sense presencialitat): merge per rang dins de
        # (day, franja, slot_id), PRESENCIAL primer.
        slot_meta = pd.concat(meta_frames, ignore_index=True)
        slot_meta["_pres_order"] = (
            slot_meta["presentiality"].astype(str).str.upper()
            .map(lambda p: 0 if p == "PRESENCIAL" else 1)
        )
        slot_meta = (
            slot_meta.sort_values(["day", "franja", "slot_id", "_pres_order"])
            .drop(columns=["_pres_order"])
            .reset_index(drop=True)
        )
        slot_meta["_rank"] = slot_meta.groupby(["day", "franja", "slot_id"]).cumcount()

        schedule_df = schedule_df.reset_index(drop=True)
        schedule_df = schedule_df.drop(columns=["presentiality", "work_mode"], errors="ignore")
        schedule_df["_rank"] = schedule_df.groupby(["day", "franja", "slot_id"]).cumcount()

        schedule_df = schedule_df.merge(
            slot_meta,
            on=["day", "franja", "slot_id", "_rank"],
            how="left",
        ).drop(columns=["_rank"])

        schedule_df["presentiality"] = schedule_df["presentiality"].fillna("NO_DEFINIT")
        schedule_df["work_mode"] = schedule_df["work_mode"].fillna("NO_DEFINIT")
        schedule_df["reporting_machine"] = schedule_df["reporting_machine"].fillna("")

    preferred_order = [
        "day",
        "franja",
        "slot_id",
        "reporting_machine",
        "professional",
        "presentiality",
        "work_mode",
    ]
    other_cols = [c for c in schedule_df.columns if c not in preferred_order]
    schedule_df = schedule_df[preferred_order + other_cols]

    schedule_df.to_csv(schedule_path, index=False)
