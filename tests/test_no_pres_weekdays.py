"""Tests del helper `no_pres_weekday_days` i del penal tou
`_add_no_pres_weekday_soft`. Verifiquen que la restricció es resol bé:
PRES penalitzats en dies marcats, revisions excloses, NP no afecta."""

import pandas as pd
from ortools.sat.python import cp_model

from src.services.no_pres_weekdays import no_pres_weekday_days
from src.solver.objectives import _add_no_pres_weekday_soft


def _calendar(days: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"day": days, "slot_id": ["X"] * len(days)})


class TestNoPresWeekdayDays:
    def test_empty_inputs(self):
        assert no_pres_weekday_days(pd.DataFrame(), _calendar(["2026-01-05"])) == {}
        assert no_pres_weekday_days(
            pd.DataFrame({"professional_id": ["P1"], "no_pres_weekdays": ["MONDAY"]}),
            pd.DataFrame(),
        ) == {}

    def test_column_missing(self):
        # Si la columna no_pres_weekdays no existeix, retorna buit.
        df = pd.DataFrame({"professional_id": ["P1"], "name": ["Alice"]})
        assert no_pres_weekday_days(df, _calendar(["2026-01-05"])) == {}

    def test_expands_codes_to_days(self):
        # 2026-01-05 és dilluns, 2026-01-06 dimarts, 2026-01-09 divendres.
        cal = _calendar(["2026-01-05", "2026-01-06", "2026-01-09", "2026-01-12"])
        df = pd.DataFrame({
            "professional_id": ["P1", "P2"],
            "no_pres_weekdays": ["MONDAY;FRIDAY", "TUESDAY"],
        })
        result = no_pres_weekday_days(df, cal)
        assert result["P1"] == {"2026-01-05", "2026-01-09", "2026-01-12"}
        assert result["P2"] == {"2026-01-06"}

    def test_empty_codes_skipped(self):
        cal = _calendar(["2026-01-05"])
        df = pd.DataFrame({
            "professional_id": ["P1", "P2"],
            "no_pres_weekdays": ["", "MONDAY"],
        })
        result = no_pres_weekday_days(df, cal)
        assert "P1" not in result
        assert result["P2"] == {"2026-01-05"}

    def test_none_excluded(self):
        # El facultatiu 'NONE' (Sin refuerzo) no genera restriccions.
        cal = _calendar(["2026-01-05"])
        df = pd.DataFrame({
            "professional_id": ["NONE"],
            "no_pres_weekdays": ["MONDAY"],
        })
        assert no_pres_weekday_days(df, cal) == {}

    def test_invalid_codes_ignored(self):
        cal = _calendar(["2026-01-05"])
        df = pd.DataFrame({
            "professional_id": ["P1"],
            "no_pres_weekdays": ["NOTADAY;MONDAY;FUNNYDAY"],
        })
        # Només MONDAY té dies vàlids al calendari.
        result = no_pres_weekday_days(df, cal)
        assert result["P1"] == {"2026-01-05"}


class TestAddNoPresWeekdaySoft:
    def test_no_map_returns_zero(self):
        model = cp_model.CpModel()
        sk = ("2026-01-05", "MATI", "TC_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        total = _add_no_pres_weekday_soft(model, x, [sk], {})
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 0

    def test_penalizes_pres_on_marked_day(self):
        # Si P1 té dilluns NP-only, i tenim un PRES dilluns, penalitza 1.
        model = cp_model.CpModel()
        sk = ("2026-01-05", "MATI", "TC_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        total = _add_no_pres_weekday_soft(
            model, x, [sk], {"P1": {"2026-01-05"}},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 1

    def test_np_not_penalized(self):
        # NP slot: cap penalització encara que el facultatiu el tingui NP-only.
        model = cp_model.CpModel()
        sk = ("2026-01-05", "TARDA", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        total = _add_no_pres_weekday_soft(
            model, x, [sk], {"P1": {"2026-01-05"}},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 0

    def test_review_excluded(self):
        # Slot PRES de revisió en dia marcat: NO penalitza.
        model = cp_model.CpModel()
        sk_review = ("2026-01-05", "MATI", "REVISIO_RM", "PRESENCIAL", "NORMAL", 1)
        sk_normal = ("2026-01-05", "MATI", "TC_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {
            ("P1", sk_review): model.NewBoolVar("x_rev"),
            ("P1", sk_normal): model.NewBoolVar("x_norm"),
        }
        model.Add(x[("P1", sk_review)] == 1)
        model.Add(x[("P1", sk_normal)] == 1)
        total = _add_no_pres_weekday_soft(
            model, x, [sk_review, sk_normal],
            {"P1": {"2026-01-05"}},
            review_slots={"REVISIO_RM"},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        # Només el TC_HUB compta (la revisió queda fora).
        assert solver.Value(total) == 1

    def test_other_day_not_penalized(self):
        # P1 NP-only dilluns, però el slot és dimarts: cap penalització.
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "TC_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        total = _add_no_pres_weekday_soft(
            model, x, [sk], {"P1": {"2026-01-05"}},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 0

    def test_other_prof_not_penalized(self):
        # Slot assignat a P2; restricció és per P1 → no penalitza.
        model = cp_model.CpModel()
        sk = ("2026-01-05", "MATI", "TC_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {
            ("P1", sk): model.NewBoolVar("x_p1"),
            ("P2", sk): model.NewBoolVar("x_p2"),
        }
        model.Add(x[("P1", sk)] == 0)
        model.Add(x[("P2", sk)] == 1)
        total = _add_no_pres_weekday_soft(
            model, x, [sk], {"P1": {"2026-01-05"}},
        )
        solver = cp_model.CpSolver()
        solver.Solve(model)
        assert solver.Value(total) == 0
