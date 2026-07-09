"""Pertinença d'un dia al MES NATURAL (de l'1 a l'últim dia del mes).

S'aplica de forma consistent a:
  - El solver (genera exactament el mes natural — `filter_module_to_month`)
  - L'esborrat de files al recalcular (`_filter_out_generated_months`)
  - El render del calendari (HTML i PDF)
  - Les mètriques i breakdown per facultatiu
  - L'exportació Excel

Així, "setembre" són els dies 1-30 de setembre, encara que l'1 caigui
en dimarts: la primera setmana del mes es genera i es mostra sencera
(els dies que pertanyen al mes anterior queden en gris al render).
NOTA HISTÒRICA: fins v1.4.0 s'usava la regla "una setmana ISO pertany
al mes del seu dilluns", que deixava els primers dies del mes sense
generar quan el mes no començava en dilluns."""
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
    """Mask boolean: True per a cada data dins del mes natural
    (year, month) — de l'1 a l'últim dia. `dt_series` ha de ser una
    Series de datetime64."""
    return (dt_series.dt.year == year) & (dt_series.dt.month == month)


def in_logical_months(
    dt_series: pd.Series, year: int, months: Iterable[int],
) -> pd.Series:
    """Mask boolean: True per a cada data dins del mes natural
    (year, m ∈ months)."""
    months_set = set(months)
    return (dt_series.dt.year == year) & (dt_series.dt.month.isin(months_set))


