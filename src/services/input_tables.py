from pathlib import Path

import pandas as pd

from src.domain.constants import (
    CORE_SLOT_IDS,
    FRANJA_ORDER,
    PRESENTIALITY_ORDER,
    WEEKDAY_NAMES_BY_INDEX,
    WEEKDAY_TEMPLATE_COLUMNS,
    WORK_MODE_ORDER,
)
from src.services.table_io import normalize_bool_value, read_table, save_table


# Buit a propòsit: cap slot per defecte a l'editor d'eligibilitat. Una
# instal·lació nova comença en blanc, sense cap nom de màquina real del servei.
DEFAULT_WEEKDAY_ELIGIBILITY_SLOTS: set[str] = set()


PRESENCE_MODE_VALUES = ("", "PRESENCIAL", "NO_PRESENCIAL")


def _coerce_presence_mode_column(series: pd.Series) -> pd.Series:
    """Normalitza presence_mode a {'', 'PRESENCIAL', 'NO_PRESENCIAL'}.
    Buit = el facultatiu pot fer les dues presencialitats."""
    text = series.fillna("").astype(str).str.strip().str.upper()
    return text.where(text.isin(PRESENCE_MODE_VALUES), "")


def save_professionals(df: pd.DataFrame, professionals_path: Path, eligibility_path: Path) -> None:
    out = df.copy()
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
    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    out["non_working_weekdays"] = _coerce_weekdays_column(out["non_working_weekdays"])
    out["no_pres_weekdays"] = _coerce_weekdays_column(out["no_pres_weekdays"])
    out["pres_weekdays"] = _coerce_weekdays_column(out["pres_weekdays"])
    out["fallback"] = pd.to_numeric(out["fallback"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    out["presence_mode"] = _coerce_presence_mode_column(out["presence_mode"])
    out = out[out["professional_id"] != ""].copy()
    out = out.drop_duplicates(subset=["professional_id"], keep="last")

    if "NONE" not in set(out["professional_id"]):
        out = pd.concat(
            [out, pd.DataFrame([{
                "professional_id": "NONE", "name": "Sin refuerzo",
                "non_working_weekdays": "",
                "no_pres_weekdays": "", "pres_weekdays": "",
                "fallback": 0, "presence_mode": "",
            }])],
            ignore_index=True,
        )

    out = out.sort_values("professional_id").reset_index(drop=True)
    save_table(
        professionals_path, out,
        ["professional_id", "name", "non_working_weekdays",
         "no_pres_weekdays", "pres_weekdays", "fallback", "presence_mode"],
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
    weekday = weekday_professionals_df.copy()
    for col in ["professional_id", "name"]:
        if col not in weekday.columns:
            weekday[col] = ""
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
            "non_working_weekdays": getattr(row, "non_working_weekdays", "") or "",
            "no_pres_weekdays": getattr(row, "no_pres_weekdays", "") or "",
            "pres_weekdays": getattr(row, "pres_weekdays", "") or "",
        }

    columns = ["professional_id", "name", "dies_laborables",
               "fallback", "presence_mode",
               "non_working_weekdays", "no_pres_weekdays", "pres_weekdays"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows.values())[columns].sort_values("professional_id").reset_index(drop=True)


PROFESSIONALS_COLUMNS = [
    "professional_id", "name", "non_working_weekdays",
    "no_pres_weekdays", "pres_weekdays", "fallback", "presence_mode",
]
# Columnes de professionals.csv que NO s'editen a la pestanya Facultatius
# sinó a Restriccions (tipus d'activitat i dies). El comodí sí que es marca
# a Facultatius.
_SETTINGS_EDITED_ELSEWHERE = [
    "presence_mode",
    "non_working_weekdays", "no_pres_weekdays", "pres_weekdays",
]


def with_settings_from_disk(
    df: pd.DataFrame, professionals_path: Path, renamed: dict | None = None,
) -> pd.DataFrame:
    """Torna `df` (l'esborrany de Facultatius) amb les columnes que
    s'editen a Restriccions preses del DISC. L'esborrany es carrega un cop
    per sessió: sense això, desar un nom a Facultatius tornava al valor
    antic el tipus d'activitat o els dies canviats a Restriccions. `renamed` = {id antic: id nou} si s'ha canviat l'id."""
    if not Path(professionals_path).exists():
        return df
    disk = read_table(Path(professionals_path), ["professional_id", *_SETTINGS_EDITED_ELSEWHERE])
    by_id = {
        str(r["professional_id"]).strip().upper(): r for _, r in disk.iterrows()
    }
    back = {str(new).upper(): str(old).upper() for old, new in (renamed or {}).items()}
    out = df.copy()
    for col in _SETTINGS_EDITED_ELSEWHERE:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].astype(object)
    for idx, pid in out["professional_id"].items():
        pu = str(pid).strip().upper()
        src = by_id.get(back.get(pu, pu))
        if src is None:
            continue
        for col in _SETTINGS_EDITED_ELSEWHERE:
            out.at[idx, col] = src[col]
    return out


def set_presence_mode(professionals_path: Path, professional_id: str, mode: str) -> None:
    """Desa el tipus d'activitat d'un facultatiu ('' = totes,
    'PRESENCIAL', 'NO_PRESENCIAL') sense tocar la resta de columnes."""
    df = read_table(Path(professionals_path), PROFESSIONALS_COLUMNS)
    ids = df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    # Columna tota buida → pandas la llegeix com a float (NaN): text abans.
    df["presence_mode"] = df["presence_mode"].fillna("").astype(str)
    df.loc[ids == str(professional_id).strip().upper(), "presence_mode"] = mode
    df["presence_mode"] = _coerce_presence_mode_column(df["presence_mode"])
    save_table(Path(professionals_path), df, PROFESSIONALS_COLUMNS)


def save_professional_scope(
    df: pd.DataFrame,
    professionals_path: Path,
    eligibility_path: Path,
) -> int:
    """Persist the (weekday-only) professional scope. Returns 0 (kept for
    call-site compatibility; previously returned the auto-fill count)."""
    out = df.copy()
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
        ["professional_id", "name", "non_working_weekdays",
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


_WEEKDAYS = WEEKDAY_TEMPLATE_COLUMNS  # MONDAY..FRIDAY


BLOCKED_SHIFTS_PATH = Path("data/blocked_shifts.csv")
BLOCKED_SHIFTS_COLUMNS = ["professional_id", "weekday", "day", "franja"]
_SHIFT_FRANJAS = ("MATI", "TARDA", "NIT")


def _normalize_blocked_shifts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in BLOCKED_SHIFTS_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    for col in ("professional_id", "weekday", "franja"):
        df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
    day = pd.to_datetime(df["day"].fillna("").astype(str), errors="coerce")
    df["day"] = day.dt.strftime("%Y-%m-%d").fillna("")
    # Un dia concret mana sobre el dia de la setmana (mai les dues).
    df["weekday"] = df["weekday"].where(day.isna() & df["weekday"].isin(_WEEKDAYS), "")
    df = df[
        (df["professional_id"] != "") & df["franja"].isin(_SHIFT_FRANJAS)
        & ((df["day"] != "") | (df["weekday"] != ""))
    ].drop_duplicates(subset=BLOCKED_SHIFTS_COLUMNS)
    # Primer les setmanals (de dilluns a divendres), després les dates.
    df = df.assign(
        _w=df["weekday"].map(lambda w: _WEEKDAYS.index(w) if w else 99),
        _f=df["franja"].map(_SHIFT_FRANJAS.index),
    ).sort_values(["_w", "day", "_f", "professional_id"])
    return df.reset_index(drop=True)[BLOCKED_SHIFTS_COLUMNS]


def load_blocked_shifts(path: Path = BLOCKED_SHIFTS_PATH) -> pd.DataFrame:
    """Elegibilitat per TORN: (facultatiu, franja) que no ha de tenir
    programació un dia de la setmana (cada setmana, p. ex. els dilluns a la
    tarda) o un dia concret. Si el fitxer no hi és, buida."""
    return _normalize_blocked_shifts(read_table(Path(path), BLOCKED_SHIFTS_COLUMNS))


def add_blocked_shift(
    path: Path, professional_id: str, franja: str, weekday: str = "", day=None,
) -> None:
    row = pd.DataFrame([{
        "professional_id": professional_id, "franja": franja,
        "weekday": weekday or "",
        "day": pd.to_datetime(day).strftime("%Y-%m-%d") if day else "",
    }])
    merged = pd.concat([load_blocked_shifts(path), row], ignore_index=True)
    save_table(Path(path), _normalize_blocked_shifts(merged), BLOCKED_SHIFTS_COLUMNS)


def remove_blocked_shift(
    path: Path, professional_id: str, franja: str, weekday: str = "", day: str = "",
) -> None:
    df = load_blocked_shifts(path)
    keep = ~(
        (df["professional_id"] == str(professional_id).strip().upper())
        & (df["franja"] == str(franja).strip().upper())
        & (df["weekday"] == str(weekday or "").strip().upper())
        & (df["day"] == str(day or "")[:10])
    )
    save_table(Path(path), df[keep], BLOCKED_SHIFTS_COLUMNS)


def blocked_shift_checker(df: pd.DataFrame | None):
    """Funció (facultatiu, dia 'YYYY-MM-DD', franja) → True si aquell torn
    no l'ha de fer (per dia concret o per dia de la setmana)."""
    dated: set = set()
    weekly: set = set()
    if df is not None and not df.empty:
        for r in _normalize_blocked_shifts(df).itertuples(index=False):
            if r.day:
                dated.add((r.professional_id, r.day, r.franja))
            else:
                weekly.add((r.professional_id, r.weekday, r.franja))

    def is_blocked(professional_id, day, franja) -> bool:
        pid = str(professional_id).strip().upper()
        d = str(day)[:10]
        fr = str(franja).strip().upper()
        if (pid, d, fr) in dated:
            return True
        if not weekly:
            return False
        try:
            wd = WEEKDAY_NAMES_BY_INDEX[pd.Timestamp(d).weekday()]
        except (ValueError, TypeError):
            return False
        return (pid, wd, fr) in weekly

    is_blocked.empty = not (dated or weekly)
    return is_blocked


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
