from pathlib import Path

import pandas as pd

from src.domain.constants import (
    CORE_SLOT_IDS,
    FRANJA_ORDER,
    PRESENTIALITY_ORDER,
    WEEKDAY_TEMPLATE_COLUMNS,
    WORK_MODE_ORDER,
)
from src.services.table_io import normalize_bool_value, read_table, save_table


# Buit a propòsit: cap slot per defecte a l'editor d'eligibilitat. Una
# instal·lació nova comença en blanc, sense cap nom de màquina real del servei.
DEFAULT_WEEKDAY_ELIGIBILITY_SLOTS: set[str] = set()


_DOUBLED_MACHINES_NULL_TOKENS = {"nan", "none", "null", "na", ""}


def normalize_doubled_machines(value) -> str:
    """Normalise a 'doubled_machines' cell into a sorted ';'-separated upper string."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = str(value).split(";")
    cleaned = sorted({
        str(item).strip().upper()
        for item in items
        if str(item).strip().lower() not in _DOUBLED_MACHINES_NULL_TOKENS
    })
    return ";".join(cleaned)


def _coerce_doubled_machines_column(series_or_value) -> pd.Series | str:
    if isinstance(series_or_value, pd.Series):
        return series_or_value.fillna("").astype(str).apply(normalize_doubled_machines)
    return normalize_doubled_machines(series_or_value)


PRESENCE_MODE_VALUES = ("", "PRESENCIAL", "NO_PRESENCIAL")


def _coerce_areas_column(series_or_value):
    """Normalitza un valor de `allowed_areas` ("ZONA_A;ZONA_B") a string
    sorted en MAJÚSCULES."""
    def _norm(value) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ""
        if isinstance(value, (list, tuple, set)):
            items = value
        else:
            items = str(value).split(";")
        cleaned = sorted({
            str(item).strip().upper()
            for item in items
            if str(item).strip() and str(item).strip().lower() not in {"nan", "none", "na"}
        })
        return ";".join(cleaned)
    if isinstance(series_or_value, pd.Series):
        return series_or_value.fillna("").astype(str).apply(_norm)
    return _norm(series_or_value)


def _coerce_presence_mode_column(series: pd.Series) -> pd.Series:
    """Normalitza presence_mode a {'', 'PRESENCIAL', 'NO_PRESENCIAL'}.
    Buit = el facultatiu pot fer les dues presencialitats."""
    text = series.fillna("").astype(str).str.strip().str.upper()
    return text.where(text.isin(PRESENCE_MODE_VALUES), "")


def _ensure_doubled_machines_column(df: pd.DataFrame) -> pd.DataFrame:
    """Garanteix la columna `doubled_machines` (buida si no existeix)."""
    out = df.copy()
    if "doubled_machines" not in out.columns:
        out["doubled_machines"] = ""
    out["doubled_machines"] = _coerce_doubled_machines_column(out["doubled_machines"])
    return out


def save_professionals(df: pd.DataFrame, professionals_path: Path, eligibility_path: Path) -> None:
    out = _ensure_doubled_machines_column(df)
    if "non_working_weekdays" not in out.columns:
        out["non_working_weekdays"] = ""
    if "no_pres_weekdays" not in out.columns:
        out["no_pres_weekdays"] = ""
    if "pres_weekdays" not in out.columns:
        out["pres_weekdays"] = ""
    if "fallback" not in out.columns:
        out["fallback"] = 0
    if "presence_mode" not in out.columns:
        out["presence_mode"] = ""
    if "allowed_areas" not in out.columns:
        out["allowed_areas"] = ""
    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    out["non_working_weekdays"] = _coerce_weekdays_column(out["non_working_weekdays"])
    out["no_pres_weekdays"] = _coerce_weekdays_column(out["no_pres_weekdays"])
    out["pres_weekdays"] = _coerce_weekdays_column(out["pres_weekdays"])
    out["fallback"] = pd.to_numeric(out["fallback"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    out["presence_mode"] = _coerce_presence_mode_column(out["presence_mode"])
    out["allowed_areas"] = _coerce_areas_column(out["allowed_areas"])
    out = out[out["professional_id"] != ""].copy()
    out = out.drop_duplicates(subset=["professional_id"], keep="last")

    if "NONE" not in set(out["professional_id"]):
        out = pd.concat(
            [out, pd.DataFrame([{
                "professional_id": "NONE", "name": "Sin refuerzo",
                "doubled_machines": "", "non_working_weekdays": "",
                "no_pres_weekdays": "", "pres_weekdays": "",
                "fallback": 0, "presence_mode": "",
                "allowed_areas": "",
            }])],
            ignore_index=True,
        )

    out = out.sort_values("professional_id").reset_index(drop=True)
    save_table(
        professionals_path, out,
        ["professional_id", "name", "doubled_machines", "non_working_weekdays",
         "no_pres_weekdays", "pres_weekdays", "fallback", "presence_mode",
         "allowed_areas"],
    )

    professionals = set(out["professional_id"])
    eligibility = read_table(eligibility_path, ["professional_id", "slot_id", "allowed"])
    eligibility["professional_id"] = eligibility["professional_id"].fillna("").astype(str).str.strip().str.upper()
    eligibility["slot_id"] = eligibility["slot_id"].fillna("").astype(str).str.strip()
    eligibility = eligibility[eligibility["professional_id"].isin(professionals)].copy()

    known_slots = sorted(set(eligibility["slot_id"].dropna().astype(str)) | DEFAULT_WEEKDAY_ELIGIBILITY_SLOTS)
    existing = set(zip(eligibility["professional_id"], eligibility["slot_id"]))
    new_rows = []
    for professional_id in sorted(professionals):
        for slot_id in known_slots:
            if (professional_id, slot_id) not in existing:
                new_rows.append(
                    {
                        "professional_id": professional_id,
                        "slot_id": slot_id,
                        "allowed": 0 if professional_id == "NONE" else 1,
                    }
                )
    if new_rows:
        eligibility = pd.concat([eligibility, pd.DataFrame(new_rows)], ignore_index=True)

    eligibility["allowed"] = pd.to_numeric(eligibility["allowed"], errors="coerce").fillna(1).astype(int)
    eligibility = eligibility.drop_duplicates(subset=["professional_id", "slot_id"], keep="last")
    eligibility = eligibility.sort_values(["professional_id", "slot_id"]).reset_index(drop=True)
    save_table(eligibility_path, eligibility, ["professional_id", "slot_id", "allowed"])


def _coerce_weekdays_column(series: pd.Series) -> pd.Series:
    """Normalise a ';'-separated list of weekday codes (MONDAY, TUESDAY…)."""
    valid = {"MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"}
    out = []
    for value in series.fillna("").astype(str):
        items = sorted({code.strip().upper() for code in value.split(";") if code.strip()} & valid)
        out.append(";".join(items))
    return pd.Series(out, index=series.index)


def professional_scope_df(
    weekday_professionals_df: pd.DataFrame,
) -> pd.DataFrame:
    weekday = _ensure_doubled_machines_column(weekday_professionals_df)
    for col in ["professional_id", "name"]:
        if col not in weekday.columns:
            weekday[col] = ""
    if "doubled_machines" not in weekday.columns:
        weekday["doubled_machines"] = ""
    if "non_working_weekdays" not in weekday.columns:
        weekday["non_working_weekdays"] = ""
    if "no_pres_weekdays" not in weekday.columns:
        weekday["no_pres_weekdays"] = ""
    if "pres_weekdays" not in weekday.columns:
        weekday["pres_weekdays"] = ""
    if "fallback" not in weekday.columns:
        weekday["fallback"] = 0
    if "presence_mode" not in weekday.columns:
        weekday["presence_mode"] = ""
    weekday["professional_id"] = weekday["professional_id"].fillna("").astype(str).str.strip().str.upper()
    weekday["name"] = weekday["name"].fillna("").astype(str).str.strip()
    weekday["doubled_machines"] = _coerce_doubled_machines_column(weekday["doubled_machines"])
    weekday["non_working_weekdays"] = _coerce_weekdays_column(weekday["non_working_weekdays"])
    weekday["no_pres_weekdays"] = _coerce_weekdays_column(weekday["no_pres_weekdays"])
    weekday["pres_weekdays"] = _coerce_weekdays_column(weekday["pres_weekdays"])
    weekday["fallback"] = pd.to_numeric(weekday["fallback"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    weekday["presence_mode"] = _coerce_presence_mode_column(weekday["presence_mode"])
    weekday = weekday[(weekday["professional_id"] != "") & (weekday["professional_id"] != "NONE")].copy()

    rows = {}
    for row in weekday.itertuples(index=False):
        rows[row.professional_id] = {
            "professional_id": row.professional_id,
            "name": row.name,
            "dies_laborables": True,
            "fallback": int(getattr(row, "fallback", 0) or 0),
            "presence_mode": str(getattr(row, "presence_mode", "") or "").upper(),
            "doubled_machines": getattr(row, "doubled_machines", "") or "",
            "non_working_weekdays": getattr(row, "non_working_weekdays", "") or "",
            "no_pres_weekdays": getattr(row, "no_pres_weekdays", "") or "",
            "pres_weekdays": getattr(row, "pres_weekdays", "") or "",
        }

    columns = ["professional_id", "name", "dies_laborables",
               "fallback", "presence_mode", "doubled_machines",
               "non_working_weekdays", "no_pres_weekdays", "pres_weekdays"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows.values())[columns].sort_values("professional_id").reset_index(drop=True)


def save_professional_scope(
    df: pd.DataFrame,
    professionals_path: Path,
    eligibility_path: Path,
) -> int:
    """Persist the (weekday-only) professional scope. Returns 0 (kept for
    call-site compatibility; previously returned the auto-fill count)."""
    out = _ensure_doubled_machines_column(df)
    for col in ["professional_id", "name"]:
        if col not in out.columns:
            out[col] = ""
    if "non_working_weekdays" not in out.columns:
        out["non_working_weekdays"] = ""
    if "no_pres_weekdays" not in out.columns:
        out["no_pres_weekdays"] = ""
    if "pres_weekdays" not in out.columns:
        out["pres_weekdays"] = ""
    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    out["non_working_weekdays"] = _coerce_weekdays_column(out["non_working_weekdays"])
    out["no_pres_weekdays"] = _coerce_weekdays_column(out["no_pres_weekdays"])
    out["pres_weekdays"] = _coerce_weekdays_column(out["pres_weekdays"])
    out = out[(out["professional_id"] != "") & (out["professional_id"] != "NONE")].copy()

    out = out.drop_duplicates(subset=["professional_id"], keep="last").sort_values("professional_id")

    # Preserva 'fallback'/'presence_mode' existents si l'editor no els porta.
    if ("fallback" not in out.columns or "presence_mode" not in out.columns) and professionals_path.exists():
        prev = read_table(
            professionals_path,
            ["professional_id", "fallback", "presence_mode"],
        )
        by_id = {str(r.professional_id).strip().upper(): r for r in prev.itertuples(index=False)}
        if "fallback" not in out.columns:
            out["fallback"] = out["professional_id"].map(
                lambda pid: getattr(by_id.get(str(pid).strip().upper()), "fallback", 0)
            )
        if "presence_mode" not in out.columns:
            out["presence_mode"] = out["professional_id"].map(
                lambda pid: getattr(by_id.get(str(pid).strip().upper()), "presence_mode", "")
            )
    out["fallback"] = pd.to_numeric(out.get("fallback"), errors="coerce").fillna(0).astype(int)
    out["presence_mode"] = _coerce_presence_mode_column(
        out["presence_mode"] if "presence_mode" in out.columns else pd.Series("", index=out.index)
    )

    weekday_df = out[
        ["professional_id", "name", "doubled_machines", "non_working_weekdays",
         "no_pres_weekdays", "pres_weekdays", "fallback", "presence_mode"]
    ].copy()
    save_professionals(weekday_df, professionals_path, eligibility_path)
    return 0


def save_eligibility_for_professional(
    eligibility_df: pd.DataFrame,
    selected_professional: str,
    edited_prof_eligibility: pd.DataFrame,
    eligibility_path: Path,
) -> None:
    selected_professional = str(selected_professional).strip().upper()
    updated_prof = edited_prof_eligibility.copy()
    updated_prof["professional_id"] = selected_professional
    other_eligibility = eligibility_df[
        eligibility_df["professional_id"].fillna("").astype(str).str.strip().str.upper() != selected_professional
    ].copy()
    merged = pd.concat(
        [other_eligibility, updated_prof[["professional_id", "slot_id", "allowed"]]],
        ignore_index=True,
    )
    merged["professional_id"] = merged["professional_id"].fillna("").astype(str).str.strip().str.upper()
    merged["slot_id"] = merged["slot_id"].fillna("").astype(str).str.strip()
    merged["allowed"] = pd.to_numeric(merged["allowed"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    merged = merged[(merged["professional_id"] != "") & (merged["slot_id"] != "")].copy()
    merged = merged.drop_duplicates(subset=["professional_id", "slot_id"], keep="last")
    merged = merged.sort_values(["professional_id", "slot_id"]).reset_index(drop=True)
    save_table(eligibility_path, merged, ["professional_id", "slot_id", "allowed"])


def save_absences(df: pd.DataFrame, absences_path: Path, valid_professionals: set[str]) -> None:
    out = df.copy()
    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["start_day"] = pd.to_datetime(out["start_day"], errors="coerce")
    out["end_day"] = pd.to_datetime(out["end_day"], errors="coerce")
    out["absence_type"] = out["absence_type"].fillna("").astype(str).str.strip()
    out["notes"] = out["notes"].fillna("").astype(str)

    out = out[
        (out["professional_id"] != "")
        & out["professional_id"].isin(valid_professionals)
        & out["start_day"].notna()
        & out["end_day"].notna()
        & (out["absence_type"] != "")
    ].copy()
    out = out[out["end_day"] >= out["start_day"]].copy()
    out["start_day"] = out["start_day"].dt.strftime("%Y-%m-%d")
    out["end_day"] = out["end_day"].dt.strftime("%Y-%m-%d")
    out = out.sort_values(["absence_type", "start_day", "professional_id"]).reset_index(drop=True)
    save_table(absences_path, out, ["absence_type", "professional_id", "start_day", "end_day", "notes"])


def save_guards(df: pd.DataFrame, guards_path: Path, valid_professionals: set[str]) -> None:
    out = df.copy()
    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["day"] = pd.to_datetime(out["day"], errors="coerce")
    out["guard_kind"] = out["guard_kind"].fillna("").astype(str).str.strip().str.lower()
    out["notes"] = out["notes"].fillna("").astype(str)

    aliases = {
        "guardia": "guardia",
        "guàrdia": "guardia",
        "refuerzo": "refuerzo",
        "reforç": "refuerzo",
    }
    out["guard_kind"] = out["guard_kind"].map(lambda value: aliases.get(value, value))
    out = out[
        (out["professional_id"] != "")
        & out["professional_id"].isin(valid_professionals)
        & out["day"].notna()
        & out["guard_kind"].isin(["guardia", "refuerzo"])
    ].copy()
    out["day"] = out["day"].dt.strftime("%Y-%m-%d")
    out = out.drop_duplicates(subset=["day", "professional_id", "guard_kind"], keep="last")
    out = out.sort_values(["day", "professional_id", "guard_kind"]).reset_index(drop=True)
    save_table(guards_path, out, ["day", "professional_id", "guard_kind", "notes"])


def save_manual_assignments(
    df: pd.DataFrame,
    manual_assignments_path: Path,
    valid_professionals: set[str],
) -> None:
    out = df.copy()
    for col in ["franja", "presentiality", "work_mode", "source"]:
        if col not in out.columns:
            out[col] = ""
    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["day"] = pd.to_datetime(out["day"], errors="coerce")
    out["franja"] = out["franja"].fillna("").astype(str).str.strip().str.upper()
    out["slot_id"] = out["slot_id"].fillna("").astype(str).str.strip()
    out["presentiality"] = out["presentiality"].fillna("").astype(str).str.strip().str.upper()
    out["work_mode"] = out["work_mode"].fillna("").astype(str).str.strip().str.upper()
    out["source"] = out["source"].fillna("manual").astype(str).str.strip().replace("", "manual")
    out["fixed"] = pd.to_numeric(out["fixed"], errors="coerce").fillna(1).astype(int).clip(0, 1)

    out = out[
        (out["professional_id"] != "")
        & out["professional_id"].isin(valid_professionals)
        & out["day"].notna()
        & (out["slot_id"] != "")
        & (out["fixed"] == 1)
    ].copy()
    out["day"] = out["day"].dt.strftime("%Y-%m-%d")
    out = out.drop_duplicates(
        subset=["day", "franja", "slot_id", "presentiality", "work_mode"],
        keep="last",
    )
    out = out.sort_values(["day", "franja", "slot_id", "professional_id"]).reset_index(drop=True)
    save_table(
        manual_assignments_path,
        out,
        ["professional_id", "day", "franja", "slot_id", "presentiality", "work_mode", "fixed", "source"],
    )


def save_weekly_slot_templates(df: pd.DataFrame, templates_path: Path) -> None:
    out = df.copy()
    if "required_staff" not in out.columns:
        out["required_staff"] = 1
    if "doubled" not in out.columns:
        out["doubled"] = 0
    if "linked_to" not in out.columns:
        out["linked_to"] = ""
    out["weekday_name"] = out["weekday_name"].fillna("").astype(str).str.strip().str.upper()
    out["franja"] = out["franja"].fillna("").astype(str).str.strip().str.upper()
    out["slot_id"] = out["slot_id"].fillna("").astype(str).str.strip()
    out["presentiality"] = out["presentiality"].fillna("PRESENCIAL").astype(str).str.strip().str.upper()
    out["work_mode"] = out["work_mode"].fillna("NORMAL").astype(str).str.strip().str.upper()
    out["required_staff"] = pd.to_numeric(out["required_staff"], errors="coerce").fillna(1).astype(int).clip(lower=1, upper=6)
    out["is_active"] = pd.to_numeric(out["is_active"], errors="coerce").fillna(1).astype(int).clip(0, 1)
    # Alternança setmanal: cada N setmanes (1 = totes) + quina setmana del
    # cicle (offset segons setmana ISO % interval).
    if "week_interval" not in out.columns:
        out["week_interval"] = 1
    if "week_offset" not in out.columns:
        out["week_offset"] = 0
    out["week_interval"] = pd.to_numeric(out["week_interval"], errors="coerce").fillna(1).astype(int).clip(1, 4)
    out["week_offset"] = pd.to_numeric(out["week_offset"], errors="coerce").fillna(0).astype(int).clip(0, 3)
    out["doubled"] = pd.to_numeric(out["doubled"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    out["linked_to"] = out["linked_to"].fillna("").astype(str).str.strip().str.upper()

    out = out[
        out["weekday_name"].isin(["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"])
        & out["franja"].isin(["MATI", "TARDA", "NIT"])
        & (out["slot_id"] != "")
        & out["presentiality"].isin(["PRESENCIAL", "NO_PRESENCIAL"])
        & out["work_mode"].isin(["NORMAL", "PEONADA"])
    ].copy()
    out = out.drop_duplicates(
        subset=["weekday_name", "franja", "slot_id", "presentiality", "work_mode"],
        keep="last",
    )
    out["weekday_order"] = out["weekday_name"].map(
        {weekday_name: idx for idx, weekday_name in enumerate(WEEKDAY_TEMPLATE_COLUMNS)}
    ).fillna(99).astype(int)
    out["franja_order"] = out["franja"].map(FRANJA_ORDER).fillna(99).astype(int)
    out["slot_order"] = out["slot_id"].map(
        {slot_id: idx for idx, slot_id in enumerate(CORE_SLOT_IDS)}
    ).fillna(len(CORE_SLOT_IDS)).astype(int)
    out["presentiality_order"] = out["presentiality"].map(PRESENTIALITY_ORDER).fillna(99).astype(int)
    out["work_mode_order"] = out["work_mode"].map(WORK_MODE_ORDER).fillna(99).astype(int)
    out = out.sort_values(
        [
            "weekday_order",
            "franja_order",
            "slot_order",
            "slot_id",
            "presentiality_order",
            "work_mode_order",
        ]
    ).drop(
        columns=["weekday_order", "franja_order", "slot_order", "presentiality_order", "work_mode_order"]
    ).reset_index(drop=True)
    save_table(
        templates_path,
        out,
        ["weekday_name", "franja", "slot_id", "presentiality", "work_mode",
         "required_staff", "is_active", "doubled", "linked_to",
         "week_interval", "week_offset"],
    )
