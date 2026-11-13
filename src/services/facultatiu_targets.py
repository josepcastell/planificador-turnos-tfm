"""Objectius tous PER SETMANA per facultatiu editables des de la pestanya
Mètriques: presencialitats i no-presencials objectiu per setmana
completa. El solver intenta acostar-s'hi setmana a setmana (pes alt;
escalat als dies efectius de cada setmana segons planning_rules)."""
from pathlib import Path

import pandas as pd

from src.services.table_io import read_table, save_table

FACULTATIU_TARGETS_COLUMNS = [
    "professional_id", "target_presential", "target_no_presential",
]


def load_facultatiu_targets(path: Path) -> pd.DataFrame:
    df = read_table(Path(path), FACULTATIU_TARGETS_COLUMNS)
    if df.empty:
        return df
    df["professional_id"] = (
        df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    )
    for col in ("target_presential", "target_no_presential"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["professional_id"] != ""].copy()
    df = df[df[["target_presential", "target_no_presential"]].notna().any(axis=1)]
    return df.drop_duplicates(subset=["professional_id"], keep="last")


def _as_int(value) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None
