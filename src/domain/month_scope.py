"""Regla "una setmana ISO pertany al mes del seu DILLUNS".

Aquesta regla s'aplica de forma consistent a:
  - El solver (genera per setmanes completes — `filter_module_to_month`)
  - L'esborrat de files al recalcular (`_filter_out_generated_months`)
  - El render del calendari (HTML i PDF)
  - Les mètriques i breakdown per facultatiu
  - L'exportació Excel

Així, "juny" significa "totes les setmanes ISO el dilluns de les quals
cau a juny". Una setmana cross-month (29-jun → 3-jul) pertany sempre
a juny; una setmana 6-jul → 10-jul pertany a juliol."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd

def catalan_month_name(month: int) -> str:
    """Nom del mes en català, en minúscules (1→'gener' … 12→'desembre').
    Buit si està fora de rang. Font única: constants.CATALAN_MONTHS."""
    from src.domain.constants import CATALAN_MONTHS
    try:
        return CATALAN_MONTHS.get(int(month), "").lower()
    except (TypeError, ValueError):
        return ""


def catalan_months_label(months: Iterable[int]) -> str:
    """Etiqueta del període per a noms de fitxer / títols: «juny» per a
    un sol mes, «juny-juliol» per a diversos (separats per guió). Buit si
    no hi ha cap mes vàlid."""
    names = [catalan_month_name(m) for m in (months or []) if 1 <= int(m) <= 12]
    return "-".join(names) if names else ""


def in_logical_month(
    dt_series: pd.Series, year: int, month: int,
) -> pd.Series:
    """Mask boolean: True per a cada data on el Monday de la seva
    setmana ISO és a (year, month). `dt_series` ha de ser una Series
    de datetime64."""
    monday = dt_series - pd.to_timedelta(dt_series.dt.weekday, unit="D")
    return (monday.dt.year == year) & (monday.dt.month == month)


def in_logical_months(
    dt_series: pd.Series, year: int, months: Iterable[int],
) -> pd.Series:
    """Mask boolean: True per a cada data on el Monday de la seva
    setmana ISO és a (year, m ∈ months)."""
    months_set = set(months)
    monday = dt_series - pd.to_timedelta(dt_series.dt.weekday, unit="D")
    return (monday.dt.year == year) & (monday.dt.month.isin(months_set))


