from pathlib import Path

import pandas as pd

from src.services.table_io import read_table


BASE_CALENDAR_OVERRIDE_COLUMNS = [
    "day",
    "is_ics_holiday",
    "is_extra_holiday",
    "force_working_day",
    "day_type",
    "notes",
]

OVERRIDE_TYPE_TO_FLAGS = {
    "Festiu oficial manual": {
        "is_ics_holiday": 0,
        "is_extra_holiday": 1,
        "force_working_day": 0,
        "day_type": "festivo_general",
    },
    "Festiu ICS": {
        "is_ics_holiday": 1,
        "is_extra_holiday": 0,
        "force_working_day": 0,
        "day_type": "festivo_ics",
    },
    "Festiu intern / extra": {
        "is_ics_holiday": 0,
        "is_extra_holiday": 1,
        "force_working_day": 0,
        "day_type": "festivo_extra",
    },
    "Forçar laborable": {
        "is_ics_holiday": 0,
        "is_extra_holiday": 0,
        "force_working_day": 1,
        "day_type": "laborable",
    },
}


def load_base_calendar_overrides(path: Path) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path)
    else:
        df = pd.DataFrame(columns=BASE_CALENDAR_OVERRIDE_COLUMNS)

    for col in BASE_CALENDAR_OVERRIDE_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in {"day", "day_type", "notes"} else 0

    df = df[BASE_CALENDAR_OVERRIDE_COLUMNS].copy()
    for col in ["is_ics_holiday", "is_extra_holiday", "force_working_day"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["day"] = df["day"].fillna("").astype(str)
    df["day_type"] = df["day_type"].fillna("").astype(str)
    df["notes"] = df["notes"].fillna("").astype(str)
    return df


def override_row_type(row) -> str:
    day_type = str(getattr(row, "day_type", "") or "").strip().lower()
    if int(getattr(row, "force_working_day", 0) or 0) == 1 or day_type == "laborable":
        return "Forçar laborable"
    if int(getattr(row, "is_ics_holiday", 0) or 0) == 1 or day_type == "festivo_ics":
        return "Festiu ICS"
    if day_type == "festivo_general":
        return "Festiu oficial manual"
    return "Festiu intern / extra"


def overrides_to_manual_editor(df: pd.DataFrame) -> pd.DataFrame:
    out = load_base_calendar_overrides(Path("__missing__")) if df is None else df.copy()
    for col in BASE_CALENDAR_OVERRIDE_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col in {"day", "day_type", "notes"} else 0
    out["day"] = pd.to_datetime(out["day"], errors="coerce")
    out = out.dropna(subset=["day"]).copy()
    out["tipus"] = [override_row_type(row) for row in out.itertuples(index=False)]
    out["notes"] = out["notes"].fillna("").astype(str)
    return out[["day", "tipus", "notes"]].sort_values("day").reset_index(drop=True)


def manual_editor_to_overrides(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=BASE_CALENDAR_OVERRIDE_COLUMNS)
    out = df.copy()
    if "tipus" not in out.columns:
        return out
    out["day"] = pd.to_datetime(out["day"], errors="coerce")
    out = out.dropna(subset=["day"]).copy()
    out["tipus"] = out["tipus"].fillna("").astype(str)
    out["notes"] = out["notes"].fillna("").astype(str)
    rows = []
    for row in out.itertuples(index=False):
        flags = OVERRIDE_TYPE_TO_FLAGS.get(str(row.tipus), OVERRIDE_TYPE_TO_FLAGS["Festiu intern / extra"])
        rows.append({
            "day": row.day,
            "is_ics_holiday": flags["is_ics_holiday"],
            "is_extra_holiday": flags["is_extra_holiday"],
            "force_working_day": flags["force_working_day"],
            "day_type": flags["day_type"],
            "notes": row.notes,
        })
    return pd.DataFrame(rows, columns=BASE_CALENDAR_OVERRIDE_COLUMNS)


def save_base_calendar_overrides(path: Path, df: pd.DataFrame) -> None:
    out = manual_editor_to_overrides(df) if "tipus" in df.columns else df.copy()
    out["day"] = pd.to_datetime(out["day"], errors="coerce")
    out = out.dropna(subset=["day"]).copy()
    out["day"] = out["day"].dt.strftime("%Y-%m-%d")

    for col in ["is_ics_holiday", "is_extra_holiday", "force_working_day"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)

    out["day_type"] = out["day_type"].fillna("").astype(str)
    out["notes"] = out["notes"].fillna("").astype(str)
    out = out.drop_duplicates(subset=["day"], keep="last").sort_values("day")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)


def load_public_holidays_table(path: Path) -> pd.DataFrame:
    df = read_table(path, ["day", "location"])
    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    df["location"] = df["location"].fillna("").astype(str)
    return df


def load_absences_by_day(year: int) -> dict[str, list[str]]:
    """Llegeix les indisponibilitats reals (absències) per dia, EXCLOENT els
    motius de guàrdia (guàrdia/reforç/postguàrdia, que es mostren a part).
    Retorna {'YYYY-MM-DD': [professional_id, ...]} ordenat. Si no hi ha cap
    fitxer retorna {}."""
    candidates = [
        Path(f"data/derived/unavailability_weekday_{year}.csv"),
        Path(f"data/derived/unavailability_{year}.csv"),
    ]
    guard_reasons = {
        "guardia_day_tarda", "refuerzo_afternoon", "post_guard_free",
    }
    for path in candidates:
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = pd.read_csv(path)
        if not {"professional_id", "day"}.issubset(df.columns):
            continue
        df["day"] = pd.to_datetime(df["day"], errors="coerce")
        df = df.dropna(subset=["day"]).copy()
        if "reason" in df.columns:
            df = df[~df["reason"].astype(str).isin(guard_reasons)].copy()
        result: dict[str, set] = {}
        for row in df.itertuples(index=False):
            prof = str(row.professional_id).strip()
            if not prof:
                continue
            result.setdefault(row.day.strftime("%Y-%m-%d"), set()).add(prof)
        return {k: sorted(v) for k, v in result.items()}
    return {}


def load_guard_schedule_by_day(year: int) -> dict[str, dict]:
    """Llegeix data/derived/guard_constraints_{year}.csv i retorna, per dia
    (clau 'YYYY-MM-DD'), els facultatius de guàrdia i de postguàrdia:

        {"2026-05-27": {"guards": [("MV", "guardia")], "post": []},
         "2026-05-28": {"guards": [], "post": ["MV"]}}

    'guards' prové de constraint_type == 'guard_day' (kind = guardia |
    refuerzo). 'post' prové de constraint_type == 'post_guard_free'.
    Si el fitxer no existeix retorna {}."""
    path = Path(f"data/derived/guard_constraints_{year}.csv")
    if not path.exists() or path.stat().st_size == 0:
        return {}
    df = pd.read_csv(path)
    needed = {"professional_id", "day", "constraint_type"}
    if not needed.issubset(df.columns):
        return {}
    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    df = df.dropna(subset=["day"]).copy()
    has_kind = "source_guard_kind" in df.columns
    result: dict[str, dict] = {}
    for row in df.itertuples(index=False):
        day_key = row.day.strftime("%Y-%m-%d")
        entry = result.setdefault(day_key, {"guards": [], "post": []})
        prof = str(row.professional_id).strip()
        if not prof:
            continue
        ctype = str(row.constraint_type).strip()
        if ctype == "guard_day":
            kind = (
                str(getattr(row, "source_guard_kind", "") or "").strip().lower()
                if has_kind else ""
            ) or "guardia"
            entry["guards"].append((prof, kind))
        elif ctype == "post_guard_free":
            entry["post"].append(prof)
    return result
