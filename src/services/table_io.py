from pathlib import Path

import pandas as pd


def read_table(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path)
    else:
        df = pd.DataFrame(columns=columns)

    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns].copy()


def save_table(path: Path, df: pd.DataFrame, columns: list[str]) -> None:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    out = out[columns].copy()
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)


def normalize_bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "si", "sí", "y", "x"}


def normalize_for_comparison(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.reindex(columns=columns).copy().reset_index(drop=True)
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]) or col == "day" or col.endswith("_day"):
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_bool_dtype(out[col]):
            out[col] = out[col].astype(int)
        elif pd.api.types.is_numeric_dtype(out[col]):
            numeric = pd.to_numeric(out[col], errors="coerce")
            out[col] = numeric.map(lambda value: "" if pd.isna(value) else f"{value:g}")
        else:
            out[col] = out[col].map(
                lambda value: int(value)
                if isinstance(value, bool)
                else str(value).strip()
                if not pd.isna(value)
                else ""
            )
    out = out.fillna("")
    if not out.empty:
        out = out.sort_values(list(out.columns), kind="mergesort").reset_index(drop=True)
    return out


def dataframe_changed(left: pd.DataFrame, right: pd.DataFrame, columns: list[str] | None = None) -> bool:
    compare_columns = columns or list(dict.fromkeys(list(left.columns) + list(right.columns)))
    left_cmp = normalize_for_comparison(left, compare_columns)
    right_cmp = normalize_for_comparison(right, compare_columns)
    return not left_cmp.equals(right_cmp)


def ensure_csv_file(path: Path, columns: list[str]) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    save_table(path, pd.DataFrame(columns=columns), columns)
