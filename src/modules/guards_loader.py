import pandas as pd


def build_guard_constraints(guards_df: pd.DataFrame) -> pd.DataFrame:
    """Return an empty preassignment DataFrame compatible with the solver.

    Guards are processed upstream in the annual pipeline (tools/), which
    generates derived files:
      - guard_constraints_{year}.csv   → merged into weekday preassignments
      - unavailability derived entries → POST_GUARDIA free days

    This function exists only as a stable call-site so main.py does not need
    conditional logic. If guard preprocessing is ever integrated here, replace
    this body with the actual transformation.
    """
    return pd.DataFrame(columns=["professional_id", "day", "slot_id", "fixed"])
