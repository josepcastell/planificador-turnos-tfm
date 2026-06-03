"""Soft objective terms (equity spreads, weekly targets, stability, metric
targets). Aquesta capa és un re-export dels tres submòduls temàtics:
- `objectives_balance`  · equitat/spread per facultatiu (PRES/NO_PRES,
  màquines ordinàries, dies de feina, TC/RM mensual i total, revisions).
- `objectives_targets`  · objectius tous a partir de targets editats
  (setmanals, per facultatiu, mètrics TC/RM/peonades, per màquina).
- `objectives_penalties` · penalitzacions diverses (ús del comodí, cap
  de peonades, comitè, teletreball post-guàrdia, elegibilitat tova,
  estabilitat respecte a la solució anterior).

Es manté aquest mòdul per compatibilitat amb codi extern que importa de
`src.solver.objectives` (p.ex. `core.py` i tests futurs)."""

from src.solver.objectives_balance import (
    _add_count_balance,
    _add_ordinary_machine_balance,
    _add_presentiality_balance,
    _add_review_balance,
    _add_tc_rm_balance,
)
from src.solver.objectives_penalties import (
    _add_comite_preferred_machine_terms,
    _add_eligibility_soft,
    _add_fallback_usage_penalty,
    _add_guard_morning_telework_terms,
    _add_no_pres_weekday_soft,
    _add_pres_weekday_soft,
    _add_stability_terms,
)
from src.solver.objectives_targets import (
    _add_facultatiu_targets,
    _add_peonada_monthly_cap,
    _add_weekly_soft_terms,
    _facultatiu_target_num,
)

__all__ = [
    "_add_count_balance",
    "_add_ordinary_machine_balance",
    "_add_presentiality_balance",
    "_add_review_balance",
    "_add_tc_rm_balance",
    "_add_comite_preferred_machine_terms",
    "_add_eligibility_soft",
    "_add_fallback_usage_penalty",
    "_add_guard_morning_telework_terms",
    "_add_stability_terms",
    "_add_no_pres_weekday_soft",
    "_add_pres_weekday_soft",
    "_add_facultatiu_targets",
    "_add_peonada_monthly_cap",
    "_add_weekly_soft_terms",
    "_facultatiu_target_num",
]
