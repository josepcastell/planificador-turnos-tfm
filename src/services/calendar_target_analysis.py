"""Anàlisi de dimensionament del calendari vs els targets setmanals.
S'utilitza per donar diagnòstics precisos quan el solver no assoleix el
target setmanal: la causa estructural és que el calendari té MÉS o
MENYS slots dels que els targets necessiten."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def compute_calendar_vs_targets(
    year: int,
    months: list[int],
    calendar_slots_path: Path | None = None,
    professionals_path: Path | None = None,
    planning_rules_path: Path | None = None,
) -> dict:
    """Compara el dimensionament del calendari amb els targets setmanals.

    Retorna un dict amb:
      calendar_pres: nre. d'slots PRES al calendari (any+mesos)
      calendar_np: nre. d'slots NP al calendari
      target_pres: suma de targets PRES esperats per setmana × prof
      target_np_ord: suma de targets NP_ord esperats
      diff_pres: target_pres − calendar_pres (positiu = manquen PRES al
        calendari → shortfall estructural; negatiu = sobren PRES →
        overage estructural)
      diff_np: idem per NP
    """
    cs_path = Path(calendar_slots_path) if calendar_slots_path else Path(
        "data/weekday/calendar_slots.csv"
    )
    pr_path = Path(professionals_path) if professionals_path else Path(
        "data/professionals.csv"
    )
    plr_path = Path(planning_rules_path) if planning_rules_path else Path(
        "data/planning_rules.csv"
    )

    out = {
        "calendar_pres": 0, "calendar_np": 0,
        "target_pres": 0, "target_np_ord": 0,
        "diff_pres": 0, "diff_np": 0,
    }
    if not cs_path.exists() or not pr_path.exists() or not plr_path.exists():
        return out

    try:
        slots = pd.read_csv(cs_path)
        prof = pd.read_csv(pr_path)
        rules = pd.read_csv(plr_path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return out

    # Filtra slots per any+mesos (mes natural: de l'1 a l'ultim dia).
    from src.domain.month_scope import in_logical_months
    if "day" not in slots.columns:
        return out
    slots["day_dt"] = pd.to_datetime(slots["day"], errors="coerce")
    scope = slots.loc[in_logical_months(slots["day_dt"], year, months)].copy()
    if scope.empty:
        return out

    out["calendar_pres"] = int(
        (scope.get("presentiality", "").astype(str).str.upper()
         == "PRESENCIAL").sum()
    )
    out["calendar_np"] = int(
        (scope.get("presentiality", "").astype(str).str.upper()
         == "NO_PRESENCIAL").sum()
    )

    # Suma de targets per facultatiu per setmana, escalat als dies
    # efectius (eff_days) per professional al mes. Per simplificar, ho
    # fem assumint 5 dies efectius per setmana per a cada regular (és
    # una aproximació; el solver fa el càlcul exacte amb capacities).
    if {"active_days", "target_presential", "target_machines"}.issubset(rules.columns):
        rules_by_days = rules.set_index("active_days")
        # Per a setmanes completes (5 dies):
        target_pres_5 = int(rules_by_days.loc[5, "target_presential"]) \
            if 5 in rules_by_days.index else 3
        target_mach_5 = int(rules_by_days.loc[5, "target_machines"]) \
            if 5 in rules_by_days.index else 4
        target_np_5 = max(0, target_mach_5 - target_pres_5)
    else:
        target_pres_5 = 3
        target_np_5 = 1

    # Nre. de facultatius REGULARS (no fallback, no NONE).
    if {"professional_id", "fallback"}.issubset(prof.columns):
        is_regular = (
            (prof["professional_id"].astype(str).str.strip().str.upper() != "NONE")
            & (pd.to_numeric(prof["fallback"], errors="coerce").fillna(0).astype(int) == 0)
        )
        n_regulars = int(is_regular.sum())
    else:
        n_regulars = 0

    # Nre. de setmanes al scope (aproximat: dies / 5 dies laborables/setm).
    # round() i no //: amb el mes natural les setmanes frontereres son
    # parcials (21-23 dies laborables) i el floor descartava fins a 3 dies.
    n_days = scope["day_dt"].dt.normalize().nunique()
    n_weeks = max(1, round(n_days / 5)) if n_days > 0 else 0

    out["target_pres"] = n_regulars * target_pres_5 * n_weeks
    out["target_np_ord"] = n_regulars * target_np_5 * n_weeks
    out["diff_pres"] = out["target_pres"] - out["calendar_pres"]
    out["diff_np"] = out["target_np_ord"] - out["calendar_np"]
    return out
