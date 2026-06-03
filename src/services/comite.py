"""Comitè assignments per facultatiu — força una màquina del grup HUB o DIR aquell dia."""

from pathlib import Path

import pandas as pd

from src.domain.constants import COMITE_TYPES, WEEKDAY_CODES
from src.services.table_io import read_table, save_table


COMITE_COLUMNS = [
    "professional_id",
    "comite_name",
    "comite_type",
    "specific_day",
    "weekday",
    "notes",
]


def load_comite_assignments(path: Path) -> pd.DataFrame:
    df = read_table(path, COMITE_COLUMNS)
    df["professional_id"] = df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    df["comite_name"] = df["comite_name"].fillna("").astype(str).str.strip()
    df["comite_type"] = df["comite_type"].fillna("").astype(str).str.strip().str.upper()
    df["specific_day"] = pd.to_datetime(df["specific_day"], errors="coerce")
    df["weekday"] = df["weekday"].fillna("").astype(str).str.strip().str.upper()
    df["notes"] = df["notes"].fillna("").astype(str)
    return df


def save_comite_assignments(
    path: Path, df: pd.DataFrame, valid_professionals: set[str]
) -> None:
    out = df.copy()
    for col in COMITE_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["comite_name"] = out["comite_name"].fillna("").astype(str).str.strip()
    out["comite_type"] = out["comite_type"].fillna("").astype(str).str.strip().str.upper()
    out["specific_day"] = pd.to_datetime(out["specific_day"], errors="coerce")
    out["weekday"] = out["weekday"].fillna("").astype(str).str.strip().str.upper()
    out["notes"] = out["notes"].fillna("").astype(str)

    out = out[out["professional_id"].isin(valid_professionals)].copy()
    out = out[out["comite_type"].isin(COMITE_TYPES)].copy()
    has_date = out["specific_day"].notna()
    has_weekday = out["weekday"].isin(WEEKDAY_CODES)
    out = out[has_date | has_weekday].copy()
    # specific_day takes precedence over weekday when both are set
    out.loc[out["specific_day"].notna(), "weekday"] = ""

    out["specific_day"] = out["specific_day"].dt.strftime("%Y-%m-%d").fillna("")
    out = out.drop_duplicates(
        subset=["professional_id", "comite_name", "comite_type", "specific_day", "weekday"],
        keep="last",
    )
    out = out.sort_values(
        ["professional_id", "specific_day", "weekday", "comite_name"]
    ).reset_index(drop=True)
    save_table(path, out, COMITE_COLUMNS)


