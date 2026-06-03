"""Tests del helper `pres_weekday_days` i del penal tou
`_add_pres_weekday_soft`. Simètrics als del cas no_pres_weekdays:
penalitzen NP en dies marcats, revisions excloses, PRES no afecta."""

import pandas as pd
from ortools.sat.python import cp_model

from src.services.pres_weekdays import pres_weekday_days
from src.solver.objectives import _add_pres_weekday_soft


def _calendar(days: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"day": days, "slot_id": ["X"] * len(days)})


class TestPresWeekdayDays:
    def test_empty_inputs(self):
        assert pres_weekday_days(pd.DataFrame(), _calendar(["2026-01-05"])) == {}
        assert pres_weekday_days(
            pd.DataFrame({"professional_id": ["P1"], "pres_weekdays": ["MONDAY"]}),
            pd.DataFrame(),
        ) == {}

    def test_column_missing(self):
        df = pd.DataFrame({"professional_id": ["P1"], "name": ["Alice"]})
        assert pres_weekday_days(df, _calendar(["2026-01-05"])) == {}

    def test_expands_codes_to_days(self):
        cal = _calendar(["2026-01-05", "2026-01-06", "2026-01-09", "2026-01-12"])
        df = pd.DataFrame({
            "professional_id": ["P1", "P2"],
            "pres_weekdays": ["MONDAY;FRIDAY", "TUESDAY"],
        })
        result = pres_weekday_days(df, cal)
        assert result["P1"] == {"2026-01-05", "2026-01-09", "2026-01-12"}
        assert result["P2"] == {"2026-01-06"}

    def test_none_and_empty_excluded(self):
        cal = _calendar(["2026-01-05"])
        df = pd.DataFrame({
            "professional_id": ["NONE", "P1"],
            "pres_weekdays": ["MONDAY", ""],
        })
        assert pres_weekday_days(df, cal) == {}


class TestAddPresWeekdaySoft:
    def test_no_map_returns_zero(self):
        model = cp_model.CpModel()
        sk = ("2026-01-05", "MATI", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        total = _add_pres_weekday_soft(model, x, [sk], {})
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 0

    def test_penalizes_np_on_marked_day(self):
        # P1 PRES-only dilluns, té un NP dilluns → penalitza 1.
        model = cp_model.CpModel()
        sk = ("2026-01-05", "MATI", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        total = _add_pres_weekday_soft(
            model, x, [sk], {"P1": {"2026-01-05"}},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 1

    def test_pres_not_penalized(self):
        # PRES slot: cap penalització.
        model = cp_model.CpModel()
        sk = ("2026-01-05", "MATI", "TC_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        total = _add_pres_weekday_soft(
            model, x, [sk], {"P1": {"2026-01-05"}},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 0

    def test_review_excluded(self):
        model = cp_model.CpModel()
        sk_review = ("2026-01-05", "MATI", "REVISIO_RM", "NO_PRESENCIAL", "NORMAL", 1)
        sk_normal = ("2026-01-05", "MATI", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {
            ("P1", sk_review): model.NewBoolVar("x_rev"),
            ("P1", sk_normal): model.NewBoolVar("x_norm"),
        }
        model.Add(x[("P1", sk_review)] == 1)
        model.Add(x[("P1", sk_normal)] == 1)
        total = _add_pres_weekday_soft(
            model, x, [sk_review, sk_normal],
            {"P1": {"2026-01-05"}},
            review_slots={"REVISIO_RM"},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        # Només el TC_HUB compta (revisió fora).
        assert solver.Value(total) == 1

    def test_other_day_not_penalized(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        total = _add_pres_weekday_soft(
            model, x, [sk], {"P1": {"2026-01-05"}},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 0
