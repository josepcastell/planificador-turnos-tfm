"""Slot normalization, key construction, and DataFrame canonicalization."""

import pandas as pd

from src.core.utils import normalize_slot


def _norm_set(values) -> set:
    """Conjunt de cadenes normalitzades (strip + upper). Tolera None/buit.
    S'usa per a conjunts de slot_ids (revisions, secundaris…) que es
    comparen contra `str(sk[2]).strip().upper()`."""
    return {str(s).strip().upper() for s in (values or ())}


def normalize_presentiality(value: str) -> str:
    value = str(value).strip().upper()
    if value in {"PRESENCIAL", "NO_PRESENCIAL"}:
        return value
    return "PRESENCIAL"


def normalize_work_mode(value: str) -> str:
    value = str(value).strip().upper()
    if value in {"NORMAL", "PEONADA"}:
        return value
    return "NORMAL"


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "si", "sí", "y", "x"}


def _normalize_slots_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "franja" not in df.columns:
        df["franja"] = ""

    if "presentiality" not in df.columns:
        df["presentiality"] = "PRESENCIAL"

    if "work_mode" not in df.columns:
        df["work_mode"] = "NORMAL"
    if "position" not in df.columns:
        df["position"] = 1

    df["slot_id"] = df["slot_id"].apply(normalize_slot)
    df["franja"] = df["franja"].fillna("").astype(str).str.upper()
    df["presentiality"] = df["presentiality"].apply(normalize_presentiality)
    df["work_mode"] = df["work_mode"].apply(normalize_work_mode)
    df["position"] = pd.to_numeric(df["position"], errors="coerce").fillna(1).astype(int)

    return df


def _make_slot_key(row) -> tuple:
    return (
        str(row.day),
        str(row.franja),
        str(row.slot_id),
        str(row.presentiality),
        str(row.work_mode),
        int(getattr(row, "position", 1)),
    )


def _slot_label(row) -> str:
    return str(row.slot_id)
