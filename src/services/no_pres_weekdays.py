"""`professionals.no_pres_weekdays` → mapa {prof: set(day_str)}. El solver
hi imposa una penalització TOVA: en aquells (prof, dia) NO s'haurien
d'assignar slots PRESENCIALS (les revisions queden fora).

El cap dur (presence_mode=NO_PRESENCIAL global) es manté independent:
aquest mòdul només cobreix la restricció *per dia de la setmana*.
Implementació única a `presence_weekdays.weekday_mode_days`."""

from __future__ import annotations

import pandas as pd

from src.services.presence_weekdays import WEEKDAY_CODE_BY_IDX, weekday_mode_days

__all__ = ["WEEKDAY_CODE_BY_IDX", "no_pres_weekday_days"]


def no_pres_weekday_days(
    professionals_df: pd.DataFrame,
    calendar_slots: pd.DataFrame,
) -> dict[str, set[str]]:
    return weekday_mode_days(professionals_df, calendar_slots, "no_pres_weekdays")
