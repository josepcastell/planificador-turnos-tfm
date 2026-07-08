"""Configurable weekly target rules.

These rules define, per number of effective working days in a week:
  - target_machines:   objective machine count per professional per week
                       (acts as a hard cap AND a soft floor — solver aims
                       to hit it exactly for every professional).
  - target_presential: objective presential machine count per professional
                       per week (hard cap + soft floor, same semantics).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


# Targets per defecte a 0: una instal·lació nova no porta cap norma de càrrega
# del servei. Cada servei defineix els seus valors a «Regles d'equilibri
# setmanal». (Els valors reals viuen al planning_rules.csv de cada usuari.)
_DEFAULT_TARGET_MACHINES = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
_DEFAULT_TARGET_PRESENTIAL = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

_CSV_COLUMNS = ["active_days", "target_machines", "target_presential"]


@dataclass
class PlanningRules:
    target_machines: dict[int, int] = field(default_factory=lambda: dict(_DEFAULT_TARGET_MACHINES))
    target_presential: dict[int, int] = field(default_factory=lambda: dict(_DEFAULT_TARGET_PRESENTIAL))

    # ── serialisation ──────────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        rows = [
            {
                "active_days": days,
                "target_machines": self.target_machines.get(days, 0),
                "target_presential": self.target_presential.get(days, 0),
            }
            for days in range(1, 6)
        ]
        return pd.DataFrame(rows, columns=_CSV_COLUMNS)

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> "PlanningRules":
        if df.empty or "active_days" not in df.columns:
            return cls()
        target_machines: dict[int, int] = {}
        target_presential: dict[int, int] = {}
        # Backwards-compat: older CSVs used max_machines / max_presential
        # (or min_machines / min_presential as the soft objective).
        machines_col = (
            "target_machines" if "target_machines" in df.columns
            else "max_machines" if "max_machines" in df.columns
            else "min_machines" if "min_machines" in df.columns
            else None
        )
        presential_col = (
            "target_presential" if "target_presential" in df.columns
            else "max_presential" if "max_presential" in df.columns
            else "min_presential" if "min_presential" in df.columns
            else None
        )
        for row in df.itertuples(index=False):
            days = int(getattr(row, "active_days"))
            if machines_col is not None:
                target_machines[days] = int(getattr(row, machines_col))
            if presential_col is not None:
                target_presential[days] = int(getattr(row, presential_col))
        if not target_machines:
            target_machines = dict(_DEFAULT_TARGET_MACHINES)
        if not target_presential:
            target_presential = dict(_DEFAULT_TARGET_PRESENTIAL)
        return cls(target_machines=target_machines, target_presential=target_presential)

    def to_csv(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_dataframe().to_csv(path, index=False)

    @classmethod
    def from_csv(cls, path: Path) -> "PlanningRules":
        path = Path(path)
        if not path.exists() or path.stat().st_size == 0:
            return cls()
        try:
            return cls.from_dataframe(pd.read_csv(path))
        except Exception:
            return cls()

    # ── convenience ────────────────────────────────────────────────────────────

    @classmethod
    def defaults(cls) -> "PlanningRules":
        return cls()
