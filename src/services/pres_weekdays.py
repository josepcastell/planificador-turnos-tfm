"""`professionals.pres_weekdays` → mapa {prof: set(day_str)}. Simètric a
`no_pres_weekdays`: en aquells (prof, dia) els NO_PRESENCIALS es
penalitzen (tou; revisions fora).
Implementació única a `presence_weekdays.weekday_mode_days`."""

from __future__ import annotations

import pandas as pd

from src.services.presence_weekdays import WEEKDAY_CODE_BY_IDX, weekday_mode_days

__all__ = ["WEEKDAY_CODE_BY_IDX", "pres_weekday_days"]


def pres_weekday_days(
    professionals_df: pd.DataFrame,
    calendar_slots: pd.DataFrame,
) -> dict[str, set[str]]:
    return weekday_mode_days(professionals_df, calendar_slots, "pres_weekdays")
