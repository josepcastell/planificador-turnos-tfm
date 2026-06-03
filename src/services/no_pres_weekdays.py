"""Helper per traduir `professionals.no_pres_weekdays` (lista ;-separada
de codis MONDAY..SUNDAY) en un mapa {prof: set(day_str)} per dia
concret. El solver consumeix aquest mapa per imposar una penalització
TOVA: en aquells (prof, dia) NO s'haurien d'assignar slots PRESENCIALS
(les revisions queden fora — no compten com a presencial ordinari).

El cap dur (presence_mode=NO_PRESENCIAL global) es manté independent:
aquest mòdul només cobreix la restricció *per dia de la setmana*."""

from __future__ import annotations

import pandas as pd

from src.domain.constants import WEEKDAY_CODES


WEEKDAY_CODE_BY_IDX = {idx: code for idx, code in enumerate(WEEKDAY_CODES)}


def no_pres_weekday_days(
    professionals_df: pd.DataFrame,
    calendar_slots: pd.DataFrame,
) -> dict[str, set[str]]:
    """Per cada facultatiu amb `no_pres_weekdays` definit (p.ex.
    'MONDAY;FRIDAY'), retorna un dict {professional_id: {day_str, …}}
    amb els dies concrets del calendari que toquen aquells codis.

    Retorna dict buit si:
      - no hi ha facultatius amb la columna,
      - el calendari no té dies,
      - cap codi és vàlid.
    """
    if (
        professionals_df is None or professionals_df.empty
        or "no_pres_weekdays" not in professionals_df.columns
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
            for c in str(getattr(row, "no_pres_weekdays", "") or "").split(";")
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
