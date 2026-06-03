"""Tests directes per als termes tous del solver (objectives_*).

Cobertura ampla i lleugera: per a cada funció, comprovem la branca
degenerada (input buit → retorna IntVar amb valor 0) i, quan és barat
de fer, una branca activa amb un model CP-SAT minúscul.

Aquests tests són un backstop del split objectives.py → 3 submoduls:
si algun re-export es trenca o una funció s'oblida, fallen aquí
sense haver d'esperar la generació real."""

import pandas as pd
from ortools.sat.python import cp_model

from src.solver.objectives import (
    _add_comite_preferred_machine_terms,
    _add_eligibility_soft,
    _add_facultatiu_targets,
    _add_fallback_usage_penalty,
    _add_guard_morning_telework_terms,
    _add_machine_targets,
    _add_stability_terms,
    _facultatiu_target_num,
)


def _solve_value(model, var) -> int:
    """Resol un model i retorna el valor entit per a `var`. Falla si infactible."""
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return solver.Value(var)


# ────────────────────────── _facultatiu_target_num ──────────────────────────


class TestFacultatiuTargetNum:
    def test_none_returns_none(self):
        assert _facultatiu_target_num(None) is None

    def test_nan_returns_none(self):
        assert _facultatiu_target_num(float("nan")) is None

    def test_numeric_returns_float(self):
        assert _facultatiu_target_num(3) == 3.0
        assert _facultatiu_target_num("2.5") == 2.5

    def test_unparseable_returns_none(self):
        assert _facultatiu_target_num("abc") is None


# ─────────────────────── _add_fallback_usage_penalty ────────────────────────


class TestFallbackUsagePenalty:
    def test_no_fallback_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_fallback_usage_penalty(model, {}, set(), [], set())
        assert _solve_value(model, total) == 0

    def test_counts_fallback_assignments(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("TLD", sk): model.NewBoolVar("x_tld")}
        model.Add(x[("TLD", sk)] == 1)
        total = _add_fallback_usage_penalty(
            model, x, {"TLD"}, [sk], review_slots=set()
        )
        assert _solve_value(model, total) == 1

    def test_skips_review_slots(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "REVIEW_RM", "PRESENCIAL", "NORMAL", 1)
        x = {("TLD", sk): model.NewBoolVar("x_rev")}
        model.Add(x[("TLD", sk)] == 1)
        total = _add_fallback_usage_penalty(
            model, x, {"TLD"}, [sk], review_slots={"REVIEW_RM"}
        )
        # L'slot de revisió no es compta (revisions són forçades per nom).
        assert _solve_value(model, total) == 0


# ─────────────────────── _add_comite_preferred_machine_terms ─────────────────


class TestComitePreferredMachineTerms:
    def test_no_entries_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_comite_preferred_machine_terms(
            model, {}, [], ["P1"], comite_entries=[], review_slots=set()
        )
        assert _solve_value(model, total) == 0

    def test_no_machine_no_penalty_term(self):
        # Sense slots/màquines disponibles per al professional aquell dia,
        # la funció filtra l'entrada i no genera cap terme.
        model = cp_model.CpModel()
        total = _add_comite_preferred_machine_terms(
            model, {}, [], ["P1"],
            comite_entries=[("P1", "2026-01-06", "HUB")],
            review_slots=set(),
        )
        assert _solve_value(model, total) == 0


# ─────────────────────── _add_guard_morning_telework_terms ───────────────────


class TestGuardMorningTeleworkTerms:
    def test_no_guards_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_guard_morning_telework_terms(
            model, {}, [], [], review_slots=set()
        )
        assert _solve_value(model, total) == 0

    def test_no_candidate_morning_np_no_term(self):
        # Hi ha guàrdia però cap màquina NP-MATI ordinària disponible
        # per al professional → cap penalització.
        model = cp_model.CpModel()
        total = _add_guard_morning_telework_terms(
            model, {}, [], [("P1", "2026-01-06")], review_slots=set()
        )
        assert _solve_value(model, total) == 0


# ─────────────────────── _add_eligibility_soft ───────────────────────────────


class TestEligibilitySoft:
    def test_none_df_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_eligibility_soft(model, {}, ["P1"], [], None)
        assert _solve_value(model, total) == 0

    def test_empty_df_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_eligibility_soft(model, {}, ["P1"], [], pd.DataFrame())
        assert _solve_value(model, total) == 0

    def test_penalizes_non_eligible_assignment(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        df = pd.DataFrame({
            "professional_id": ["P1"],
            "slot_id": ["RM_HUB"],
            "allowed": [0],
        })
        total = _add_eligibility_soft(model, x, ["P1"], [sk], df)
        # P1 forçat a un slot no elegible → penalització 1.
        assert _solve_value(model, total) == 1

    def test_fallback_is_exempted(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("TLD", sk): model.NewBoolVar("x")}
        model.Add(x[("TLD", sk)] == 1)
        df = pd.DataFrame({
            "professional_id": ["TLD"],
            "slot_id": ["RM_HUB"],
            "allowed": [0],
        })
        # TLD (comodí) ha de ser exempt → 0 penalització encara que el
        # mapa digui que no és elegible.
        total = _add_eligibility_soft(
            model, x, ["TLD"], [sk], df, fallback_professionals={"TLD"}
        )
        assert _solve_value(model, total) == 0


# ─────────────────────── _add_stability_terms ────────────────────────────────


class TestStabilityTerms:
    def test_empty_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_stability_terms(model, {}, {})
        assert _solve_value(model, total) == 0

    def test_counts_changes_when_x_zero(self):
        # Si l'assignació anterior era P1 i x[P1, sk] = 0 → 1 canvi.
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 0)
        total = _add_stability_terms(model, x, {sk: "P1"})
        assert _solve_value(model, total) == 1

    def test_no_change_when_x_one(self):
        # Si l'assignació anterior era P1 i x[P1, sk] = 1 → 0 canvis.
        model = cp_model.CpModel()
        sk = ("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        model.Add(x[("P1", sk)] == 1)
        total = _add_stability_terms(model, x, {sk: "P1"})
        assert _solve_value(model, total) == 0


# ─────────────────────── _add_facultatiu_targets ─────────────────────────────


class TestFacultatiuTargets:
    def test_none_df_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_facultatiu_targets(
            model, None, {}, [], set(), {}, [], [], {}, {}, {}, {},
            planning_rules=None, active_professionals=[],
        )
        assert _solve_value(model, total) == 0

    def test_empty_df_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_facultatiu_targets(
            model, pd.DataFrame(), {}, [], set(), {}, [], [], {}, {}, {}, {},
            planning_rules=None, active_professionals=[],
        )
        assert _solve_value(model, total) == 0


# ─────────────────────── _add_machine_targets ────────────────────────────────


class TestMachineTargets:
    def test_none_df_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_machine_targets(model, {}, None, ["P1"], [], [])
        assert _solve_value(model, total) == 0

    def test_empty_df_returns_zero(self):
        model = cp_model.CpModel()
        total = _add_machine_targets(model, {}, pd.DataFrame(), ["P1"], [], [])
        assert _solve_value(model, total) == 0


# ─────────────────────── re-export integrity ────────────────────────────────


class TestObjectivesReExport:
    """Garanteix que l'API de `src.solver.objectives` exposa totes les
    funcions que `core.py` importa. Si el split en submoduls oblida
    qualsevol re-export, aquest test falla aquí en comptes que falli
    `core.py` només quan es genera de debò."""

    def test_all_functions_importable_from_facade(self):
        from src.solver import objectives
        expected = {
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
            "_add_facultatiu_targets",
            "_add_machine_targets",
            "_add_metric_targets",
            "_add_peonada_monthly_cap",
            "_add_weekly_soft_terms",
            "_facultatiu_target_num",
        }
        missing = {n for n in expected if not hasattr(objectives, n)}
        assert not missing, f"Falten re-exports: {missing}"

    def test_core_imports_resolve(self):
        # Smoke: core.py es pot importar sense errors d'import.
        from src.solver import core
        assert hasattr(core, "build_and_solve_demo")
