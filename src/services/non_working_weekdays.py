"""Helpers per traduir `professionals.non_working_weekdays` en estructures
que el solver consumeix:
  - `non_working_weekdays_unavailability`: files d'unavailability full-day
    per a cada dia del calendari que coincideix amb un codi MON..SUN del
    professional.
  - `reductions_from_non_working_weekdays`: files de reducció derivades
    automàticament (1 dia setmanal off = 100/N % reducció, on N és el
    nombre de dies de la setmana que es comptabilitzen).

Ambdós helpers són cridats des de `src/modules/weekday_solver.py`.
"""

from __future__ import annotations

import pandas as pd

from src.domain.constants import WEEKDAY_CODES


WEEKDAY_CODE_BY_IDX = {idx: code for idx, code in enumerate(WEEKDAY_CODES)}
WEEKDAY_CODES_SET = set(WEEKDAY_CODES[:5])   # MONDAY..FRIDAY
WEEKEND_CODES_SET = set(WEEKDAY_CODES[5:])   # SATURDAY..SUNDAY

_UNAV_COLS = [
    "professional_id", "day", "franja", "presentiality",
    "reason", "source", "notes",
]
_RED_COLS = ["professional_id", "start_day", "end_day", "reduction_pct", "notes"]


def non_working_weekdays_unavailability(
    professionals_df: pd.DataFrame,
    calendar_slots: pd.DataFrame,
) -> pd.DataFrame:
    """For each professional with non_working_weekdays set (e.g. 'MONDAY;FRIDAY'),
    emit full-day unavailability rows for every matching weekday in the
    calendar's date range. Tagged with `reason="non_working_weekday"`.
    """
    if (
        professionals_df is None or professionals_df.empty
        or "non_working_weekdays" not in professionals_df.columns
        or calendar_slots is None or calendar_slots.empty
    ):
        return pd.DataFrame(columns=_UNAV_COLS)

    unique_days = pd.to_datetime(calendar_slots["day"], errors="coerce").dropna().dt.normalize().unique()
    if len(unique_days) == 0:
        return pd.DataFrame(columns=_UNAV_COLS)

    days_by_weekday: dict[str, list[str]] = {}
    for day in unique_days:
        code = WEEKDAY_CODE_BY_IDX.get(day.weekday())
        if code:
            days_by_weekday.setdefault(code, []).append(pd.Timestamp(day).strftime("%Y-%m-%d"))

    rows = []
    for row in professionals_df.itertuples(index=False):
        pid = str(getattr(row, "professional_id", "") or "").strip().upper()
        if not pid:
            continue
        codes = [
            c.strip().upper()
            for c in str(getattr(row, "non_working_weekdays", "") or "").split(";")
            if c.strip()
        ]
        for code in codes:
            for day_str in days_by_weekday.get(code, ()):
                rows.append({
                    "professional_id": pid, "day": day_str,
                    "franja": "", "presentiality": "",
                    "reason": "non_working_weekday",
                    "source": "professionals",
                    "notes": "",
                })
    return pd.DataFrame(rows, columns=_UNAV_COLS)


def reductions_from_non_working_weekdays(
    professionals_df: pd.DataFrame,
    target_codes_set: set[str],
    days_in_week: int,
) -> pd.DataFrame:
    """Derive a reductions DataFrame from `non_working_weekdays`.

    For each pro, count how many of their `non_working_weekdays` fall in
    `target_codes_set` (e.g. MON-FRI for weekday solver, SAT-SUN for
    weekend). Each missing weekday counts as `100 // days_in_week` %
    reduction. Range open-ended (2000-01-01..2099-12-31).
    """
    if professionals_df is None or professionals_df.empty:
        return pd.DataFrame(columns=_RED_COLS)
    if "non_working_weekdays" not in professionals_df.columns:
        return pd.DataFrame(columns=_RED_COLS)
    pct_per_day = 100 // max(1, days_in_week)
    rows = []
    for row in professionals_df.itertuples(index=False):
        pid = str(getattr(row, "professional_id", "") or "").strip().upper()
        if not pid:
            continue
        codes = {
            c.strip().upper()
            for c in str(getattr(row, "non_working_weekdays", "") or "").split(";")
            if c.strip()
        }
        offs = codes & target_codes_set
        if not offs:
            continue
        rows.append({
            "professional_id": pid,
            "start_day": pd.Timestamp("2000-01-01"),
            "end_day": pd.Timestamp("2099-12-31"),
            "reduction_pct": min(100, len(offs) * pct_per_day),
            "notes": "",
        })
    return pd.DataFrame(rows, columns=_RED_COLS)
