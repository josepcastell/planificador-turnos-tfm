from pathlib import Path

import pandas as pd

from src.domain.schedule_format import franja_sort_key, slot_sort_key


def load_schedule_for_display(path_str: str) -> pd.DataFrame | None:
    path = Path(path_str)
    if not path.exists() or path.stat().st_size == 0:
        return None

    df = pd.read_csv(path)

    required = {"day", "slot_id", "professional"}
    if not required.issubset(df.columns):
        return df

    df = df.copy()

    if "franja" not in df.columns:
        df["franja"] = ""
    if "presentiality" not in df.columns:
        df["presentiality"] = "NO_DEFINIT"
    if "work_mode" not in df.columns:
        df["work_mode"] = "NO_DEFINIT"

    df["day"] = df["day"].astype(str)
    df["franja"] = df["franja"].fillna("").astype(str)
    df["slot_id"] = df["slot_id"].astype(str)
    df["professional"] = df["professional"].fillna("NONE").astype(str)
    df["presentiality"] = df["presentiality"].fillna("NO_DEFINIT").astype(str)
    df["work_mode"] = df["work_mode"].fillna("NO_DEFINIT").astype(str)

    df["franja_order"] = df["franja"].apply(franja_sort_key)
    df["slot_order"] = df["slot_id"].apply(slot_sort_key)

    df = df.sort_values(
        ["day", "franja_order", "slot_order", "slot_id", "professional"]
    ).reset_index(drop=True)

    return df
