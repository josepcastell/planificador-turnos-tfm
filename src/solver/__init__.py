"""CP-SAT planning solver package.

Public API:
    build_and_solve_demo — main entry point used by src.modules.weekday_solver

Helpers re-exported for tests:
    normalize_presentiality, normalize_work_mode, normalize_bool
    _validate_preassignments, _stability_by_slot, _prepare_reductions_df,
"""

from src.solver.constraints import _add_unavailability_constraints
from src.solver.core import build_and_solve_demo
from src.solver.normalize import (
    normalize_bool,
    normalize_presentiality,
    normalize_work_mode,
)
from src.solver.preprocessing import (
    _prepare_reductions_df,
    _stability_by_slot,
    _validate_preassignments,
)

__all__ = [
    "build_and_solve_demo",
    "normalize_bool",
    "normalize_presentiality",
    "normalize_work_mode",
    "_add_unavailability_constraints",
    "_prepare_reductions_df",
    "_stability_by_slot",
    "_validate_preassignments",
]
