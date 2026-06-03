"""Tests unitaris per als helpers del solver."""

import pandas as pd
import pytest
from ortools.sat.python import cp_model
from src.solver import (
    _add_unavailability_constraints,
    _validate_preassignments,
    _stability_by_slot,
    _prepare_reductions_df,
    _scaled_metric_target,
)
from src.solver.objectives_balance import _apportion_by_capacity
from src.solver.normalize import _norm_set


class TestValidatePreassignments:
    def test_empty_df_passes(self):
        _validate_preassignments(pd.DataFrame(), ["P1", "P2"], [])

    def test_raises_on_missing_columns(self):
        df = pd.DataFrame({"professional_id": ["P1"], "day": ["2026-01-01"]})
        with pytest.raises(ValueError, match="missing required columns"):
            _validate_preassignments(df, ["P1"], [])

    def test_raises_on_unknown_professional(self):
        df = pd.DataFrame({
            "professional_id": ["DESCONEGUT"],
            "day": ["2026-01-01"],
            "slot_id": ["RM_HUB"],
            "fixed": [1],
        })
        with pytest.raises(ValueError, match="DESCONEGUT"):
            _validate_preassignments(df, ["P1", "P2"], [])

    def test_non_fixed_rows_ignored(self):
        df = pd.DataFrame({
            "professional_id": ["DESCONEGUT"],
            "day": ["2026-01-01"],
            "slot_id": ["RM_HUB"],
            "fixed": [0],
        })
        # fixed=0 → no valida professional ni slot
        _validate_preassignments(df, ["P1"], [])


class TestStabilityBySlot:
    def test_empty_returns_empty(self):
        result = _stability_by_slot(None, ["P1"], [])
        assert result == {}

    def test_empty_df_returns_empty(self):
        result = _stability_by_slot(pd.DataFrame(), ["P1"], [])
        assert result == {}

    def test_missing_required_columns_returns_empty(self):
        df = pd.DataFrame({"day": ["2026-01-01"]})
        result = _stability_by_slot(df, ["P1"], [])
        assert result == {}

    def test_maps_slot_to_professional(self):
        sk = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        df = pd.DataFrame({
            "day": ["2026-01-06"],
            "slot_id": ["RM_HUB"],
            "professional": ["P1"],
            "franja": ["MATI"],
            "presentiality": ["PRESENCIAL"],
            "work_mode": ["NORMAL"],
        })
        result = _stability_by_slot(df, ["P1", "P2"], [sk])
        assert result.get(sk) == "P1"

    def test_ignores_unknown_professional(self):
        sk = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        df = pd.DataFrame({
            "day": ["2026-01-06"],
            "slot_id": ["RM_HUB"],
            "professional": ["DESCONEGUT"],
            "franja": ["MATI"],
            "presentiality": ["PRESENCIAL"],
            "work_mode": ["NORMAL"],
        })
        result = _stability_by_slot(df, ["P1"], [sk])
        assert sk not in result


class TestPrepareReductionsDf:
    def test_empty_input_returns_correct_columns(self):
        result = _prepare_reductions_df(None, [])
        assert list(result.columns) == ["professional_id", "start_day", "end_day", "reduction_pct"]
        assert result.empty

    def test_clips_reduction_to_100(self):
        df = pd.DataFrame({
            "professional_id": ["P1"],
            "start_day": ["2026-01-01"],
            "end_day": ["2026-01-31"],
            "reduction_pct": [150],
        })
        result = _prepare_reductions_df(df, ["P1"])
        assert result.iloc[0]["reduction_pct"] == 100

    def test_filters_unknown_professionals(self):
        df = pd.DataFrame({
            "professional_id": ["DESCONEGUT"],
            "start_day": ["2026-01-01"],
            "end_day": ["2026-01-31"],
            "reduction_pct": [50],
        })
        result = _prepare_reductions_df(df, ["P1"])
        assert result.empty


class TestScaledMetricTarget:
    def test_none_value_returns_none(self):
        assert _scaled_metric_target(float("nan"), 1, 0) is None

    def test_divisor_1_returns_target(self):
        assert _scaled_metric_target(10, 1, 0) == 10

    def test_divides_evenly(self):
        # target=6, divisor=3, position=0 → base=2, remainder=0 → 2
        assert _scaled_metric_target(6, 3, 0) == 2

    def test_distributes_remainder_to_first_positions(self):
        # target=7, divisor=3 → base=2, remainder=1 → position 0 gets +1 = 3
        assert _scaled_metric_target(7, 3, 0) == 3
        # position 1 does NOT get +1 = 2
        assert _scaled_metric_target(7, 3, 1) == 2
        assert _scaled_metric_target(7, 3, 2) == 2

    def test_negative_target_clamped_to_zero(self):
        assert _scaled_metric_target(-5, 1, 0) == 0


class TestAddUnavailabilityConstraints:
    def test_empty_df_is_noop(self):
        model = cp_model.CpModel()
        _add_unavailability_constraints(model, {}, [], pd.DataFrame())

    def test_missing_columns_raises(self):
        model = cp_model.CpModel()
        df = pd.DataFrame({"professional_id": ["P1"]})
        with pytest.raises(ValueError, match="missing required columns"):
            _add_unavailability_constraints(model, {}, [], df)

    def test_blocks_only_matching_day(self):
        model = cp_model.CpModel()
        sk_match = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        sk_other = ("2026-01-07", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {
            ("P1", sk_match): model.NewBoolVar("x_match"),
            ("P1", sk_other): model.NewBoolVar("x_other"),
        }
        df = pd.DataFrame({"professional_id": ["P1"], "day": ["2026-01-06"]})

        _add_unavailability_constraints(model, x, [sk_match, sk_other], df)

        solver = cp_model.CpSolver()
        assert solver.Solve(model) == cp_model.OPTIMAL
        assert solver.Value(x[("P1", sk_match)]) == 0
        # The other-day variable is unconstrained → solver may pick either value.


class TestApportionByCapacity:
    def test_empty_or_nonpositive_returns_empty(self):
        assert _apportion_by_capacity(10, [], {}) == {}
        assert _apportion_by_capacity(0, ["A", "B"], {"A": 100, "B": 100}) == {}
        assert _apportion_by_capacity(-3, ["A"], {"A": 100}) == {}

    def test_zero_capacity_returns_empty(self):
        assert _apportion_by_capacity(5, ["A", "B"], {"A": 0, "B": 0}) == {}

    def test_sum_equals_total_and_balanced(self):
        t = _apportion_by_capacity(10, ["A", "B", "C"], {"A": 100, "B": 100, "C": 100})
        assert sum(t.values()) == 10
        assert max(t.values()) - min(t.values()) <= 1

    def test_proportional_to_capacity(self):
        t = _apportion_by_capacity(9, ["A", "B"], {"A": 200, "B": 100})
        assert sum(t.values()) == 9
        assert t["A"] > t["B"]

    def test_largest_remainder_favours_higher_capacity(self):
        t = _apportion_by_capacity(4, ["A", "B", "C"], {"A": 100, "B": 100, "C": 100})
        assert sum(t.values()) == 4
        assert sorted(t.values()) == [1, 1, 2]

    def test_deterministic(self):
        args = (7, ["A", "B", "C"], {"A": 100, "B": 80, "C": 60})
        assert _apportion_by_capacity(*args) == _apportion_by_capacity(*args)


class TestNormSet:
    def test_none_returns_empty(self):
        assert _norm_set(None) == set()
        assert _norm_set([]) == set()

    def test_strip_and_upper(self):
        assert _norm_set([" rm_hub ", "Tc3", "REV TC"]) == {"RM_HUB", "TC3", "REV TC"}

    def test_dedup(self):
        assert _norm_set(["a", "A", " a "]) == {"A"}
