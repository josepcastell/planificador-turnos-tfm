"""Implementació ÚNICA per traduir una columna de `professionals.csv` amb
codis de dia de la setmana ;-separats (MONDAY..SUNDAY) en un mapa
{professional_id: {day_str, …}} amb els dies concrets del calendari.

La consumeixen `no_pres_weekdays` (dies només-NP) i `pres_weekdays`
(dies només-PRES), que abans eren dos mòduls quasi clònics — un bug
arreglat en un i no a l'altre era qüestió de temps."""

from __future__ import annotations

import pandas as pd

from src.domain.constants import WEEKDAY_CODES

WEEKDAY_CODE_BY_IDX = {idx: code for idx, code in enumerate(WEEKDAY_CODES)}


def weekday_mode_days(
    professionals_df: pd.DataFrame,
    calendar_slots: pd.DataFrame,
    column: str,
) -> dict[str, set[str]]:
    """Per cada facultatiu amb `column` definida (p.ex. 'MONDAY;FRIDAY'),
    retorna {professional_id: {day_str, …}} amb els dies concrets del
    calendari que toquen aquells codis. Dict buit si no hi ha facultatius
    amb la columna, el calendari no té dies, o cap codi és vàlid."""
    if (
        professionals_df is None or professionals_df.empty
        or column not in professionals_df.columns
        or calendar_slots is None or calendar_slots.empty
    ):
        return {}

    unique_days = (
        pd.to_datetime(calendar_slots["day"], errors="coerce")
        .dropna().dt.normalize().unique()
    )
    if len(unique_days) == 0:
        return {}

    days_by_weekday: dict[str, list[str]] = {}
    for day in unique_days:
        code = WEEKDAY_CODE_BY_IDX.get(day.weekday())
        if code:
            days_by_weekday.setdefault(code, []).append(
                pd.Timestamp(day).strftime("%Y-%m-%d")
            )

    out: dict[str, set[str]] = {}
    for row in professionals_df.itertuples(index=False):
        pid = str(getattr(row, "professional_id", "") or "").strip().upper()
        if not pid or pid == "NONE":
            continue
        codes = {
            c.strip().upper()
            for c in str(getattr(row, column, "") or "").split(";")
            if c.strip()
        }
        if not codes:
            continue
        day_set: set[str] = set()
        for code in codes:
            day_set.update(days_by_weekday.get(code, ()))
        if day_set:
            out[pid] = day_set
    return out
