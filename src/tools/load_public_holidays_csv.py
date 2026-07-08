from __future__ import annotations

from pathlib import Path
from typing import Iterable
import pandas as pd


YEAR_CANDIDATES = [
    "Any calendari", "Any", "Año", "Year"
]

DATE_CANDIDATES = [
    "Data", "Fecha", "Date"
]

LOCATION_CANDIDATES = [
    "Localització", "Localizacion", "Ubicació", "Ubicacion", "Location"
]


def _find_column(columns: Iterable[str], candidates: list[str]) -> str | None:
    cols = {str(c).strip(): c for c in columns}
    for cand in candidates:
        if cand in cols:
            return cols[cand]
    return None


def load_public_holidays_from_csv(csv_path: str | Path, year: int) -> pd.DataFrame:
    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError("El fitxer de festius no existeix o està buit")

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("El fitxer de festius està buit")

    year_col = _find_column(df.columns, YEAR_CANDIDATES)
    date_col = _find_column(df.columns, DATE_CANDIDATES)
    location_col = _find_column(df.columns, LOCATION_CANDIDATES)

    if date_col is None:
        raise ValueError("No s'ha trobat cap columna de data al CSV de festius")

    work = df.copy()

    # Data
    work[date_col] = pd.to_datetime(work[date_col], dayfirst=True, errors="coerce")
    work = work.dropna(subset=[date_col]).copy()

    # Any
    if year_col is not None:
        work[year_col] = pd.to_numeric(work[year_col], errors="coerce")
        work = work[work[year_col] == year].copy()
    else:
        work = work[work[date_col].dt.year == year].copy()

    if work.empty:
        return pd.DataFrame(columns=["day", "location"])

    if location_col is None:
        work["location"] = ""
    else:
        work["location"] = work[location_col].fillna("").astype(str).str.strip()

    out = pd.DataFrame({
        "day": work[date_col].dt.strftime("%Y-%m-%d"),
        "location": work["location"],
    })

    out = out.drop_duplicates(subset=["day"]).sort_values("day").reset_index(drop=True)
    return out
