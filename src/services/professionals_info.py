"""Metadades lleugeres de `professionals.csv` compartides per la UI.

Abans, `_base_pid` i la detecció de comodins (fallback=1) estaven
duplicades a metrics_tab, target_breakdown i calendar_html — amb una
divergència real: un lloc tenia el comodí «TLD» hardcoded en lloc de
llegir la columna `fallback`. Font única aquí."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.domain.schedule_format import base_pid

__all__ = ["base_pid", "fallback_professional_ids"]


def fallback_professional_ids() -> set[str]:
    """IDs (en majúscules, col·lapsats per base_pid) dels facultatius
    comodí (professionals.csv fallback=1)."""
    pp = Path("data/professionals.csv")
    if not pp.exists() or pp.stat().st_size == 0:
        return set()
    try:
        df = pd.read_csv(pp)
    except Exception:
        return set()
    if not {"professional_id", "fallback"}.issubset(df.columns):
        return set()
    fb = pd.to_numeric(df["fallback"], errors="coerce").fillna(0).astype(int)
    return {base_pid(p) for p in df.loc[fb == 1, "professional_id"]}
