"""Proposta de les regles d'equilibri amb ACCEPTACIÓ de l'usuari.

Quan hi ha un mode d'equilibri actiu, «Generar» produeix DOS calendaris:
  - outputs/schedule_weekday.csv           → BASE (les franges manen)
  - outputs/schedule_weekday_proposta.csv  → amb les regles aplicades
Aquest servei calcula la diferència entre tots dos i aplica o descarta
la proposta segons el que triï l'usuari."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

SCHEDULE_PATH = Path("outputs/schedule_weekday.csv")
PROPOSAL_PATH = Path("outputs/schedule_weekday_proposta.csv")
METRICS_PATH = Path("outputs/metrics_weekday.csv")
METRICS_PROPOSAL_PATH = Path("outputs/metrics_weekday_proposta.csv")

_KEY_COLS = ["day", "franja", "slot_id", "presentiality", "work_mode"]


def proposal_exists() -> bool:
    return (
        PROPOSAL_PATH.exists() and PROPOSAL_PATH.stat().st_size > 0
        and SCHEDULE_PATH.exists() and SCHEDULE_PATH.stat().st_size > 0
    )


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["day"] = pd.to_datetime(out["day"], errors="coerce").dt.strftime("%Y-%m-%d")
    for c in _KEY_COLS[1:] + ["professional"]:
        if c not in out.columns:
            out[c] = ""
        out[c] = out[c].fillna("").astype(str).str.strip().str.upper()
    # Discriminador d'ocurrència per a claus repetides (required_staff ≥ 2).
    out["_occ"] = out.groupby(_KEY_COLS).cumcount()
    return out


def load_proposal_diff() -> pd.DataFrame:
    """Canvis que la proposta (regles d'equilibri) fa sobre la base.
    Columnes: dia, franja, activitat, de (professional base), a (proposta)."""
    if not proposal_exists():
        return pd.DataFrame(columns=["dia", "franja", "activitat", "de", "a"])
    base = _norm(pd.read_csv(SCHEDULE_PATH))
    prop = _norm(pd.read_csv(PROPOSAL_PATH))
    merged = base.merge(
        prop[_KEY_COLS + ["_occ", "professional"]],
        on=_KEY_COLS + ["_occ"],
        how="outer",
        suffixes=("_base", "_prop"),
        indicator=False,
    )
    for c in ("professional_base", "professional_prop"):
        merged[c] = merged[c].fillna("")
    changed = merged[merged["professional_base"] != merged["professional_prop"]]
    out = pd.DataFrame({
        "dia": changed["day"],
        "franja": changed["franja"].str.title(),
        "activitat": changed["slot_id"],
        "de": changed["professional_base"].replace("", "—"),
        "a": changed["professional_prop"].replace("", "—"),
    })
    return out.sort_values(["dia", "franja", "activitat"]).reset_index(drop=True)


def apply_proposal() -> int:
    """Substitueix el calendari (i mètriques) per la proposta. Retorna el
    nombre de canvis aplicats."""
    n = len(load_proposal_diff())
    if PROPOSAL_PATH.exists():
        os.replace(PROPOSAL_PATH, SCHEDULE_PATH)
    if METRICS_PROPOSAL_PATH.exists():
        os.replace(METRICS_PROPOSAL_PATH, METRICS_PATH)
    return n


def discard_proposal() -> None:
    """Es queda la BASE (franges tal com estan) i esborra la proposta."""
    PROPOSAL_PATH.unlink(missing_ok=True)
    METRICS_PROPOSAL_PATH.unlink(missing_ok=True)
