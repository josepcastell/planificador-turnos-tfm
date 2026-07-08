"""Màquines fixes per facultatiu, GRANULAR per (dia de la setmana, franja).

Taula `data/weekday/fixed_machines.csv` amb columnes:
    professional_id, slot_id, weekday_name, franja

`weekday_name` i `franja` poden ser buits o "*" → s'apliquen a TOTS els
dies / TOTES les franges (equivalent al comportament global del catàleg).

A diferència de l'`assignee` del catàleg (global), aquesta taula permet
fixar la mateixa màquina a facultatius diferents segons el dia/franja, i
diverses màquines fixes per facultatiu. L'expansió a preassignacions
(weekday_solver._granular_fixed_preassignments) filtra per dia+franja.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

FIXED_MACHINES_COLUMNS = ["professional_id", "slot_id", "weekday_name", "franja"]


def load_fixed_machines(path: Path) -> pd.DataFrame:
    """Carrega la taula de màquines fixes granulars. Sempre retorna les
    columnes canòniques (buides si el fitxer no existeix)."""
    if path is not None and Path(path).exists() and Path(path).stat().st_size > 0:
        df = pd.read_csv(path, dtype=str).fillna("")
        for col in FIXED_MACHINES_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[FIXED_MACHINES_COLUMNS].copy()
    return pd.DataFrame(columns=FIXED_MACHINES_COLUMNS)


def save_fixed_machines(path: Path, df: pd.DataFrame) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy() if df is not None else pd.DataFrame(columns=FIXED_MACHINES_COLUMNS)
    for col in FIXED_MACHINES_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out[FIXED_MACHINES_COLUMNS].to_csv(path, index=False)


def slot_schedule_options(templates_df: pd.DataFrame) -> dict[str, list[tuple[str, str]]]:
    """Retorna {slot_id (UPPER): [(weekday_name, franja), ...]} a partir de les
    plantilles setmanals: on (i amb quina franja) està programada cada activitat.
    Només files actives (is_active != 0). Ordenat per dia de la setmana i franja."""
    order = {c: i for i, c in enumerate(
        ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    )}
    out: dict[str, set[tuple[str, str]]] = {}
    if templates_df is None or templates_df.empty:
        return {}
    if "slot_id" not in templates_df.columns:
        return {}
    for r in templates_df.itertuples(index=False):
        try:
            active = int(float(getattr(r, "is_active", 1) or 1))
        except (TypeError, ValueError):
            active = 1
        if active == 0:
            continue
        slot = str(getattr(r, "slot_id", "") or "").strip().upper()
        wd = str(getattr(r, "weekday_name", "") or "").strip().upper()
        fr = str(getattr(r, "franja", "") or "").strip().upper()
        if not slot or not wd or not fr:
            continue
        out.setdefault(slot, set()).add((wd, fr))
    return {
        slot: sorted(pairs, key=lambda p: (order.get(p[0], 99), p[1]))
        for slot, pairs in out.items()
    }
