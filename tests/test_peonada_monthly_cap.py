"""Tests directes per `_add_peonada_monthly_cap`.

Model cap-only: el solver crea `pn[p, sk]` per cada NO_PRES no-revisió
i facultatiu regular, amb una restricció DURA `sum(pn) ≤ cap(p)`. No
hi ha objectiu tou directe: les peonades emergeixen al tier NP per
absorbir l'excedent."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from src.solver.objectives import _add_peonada_monthly_cap


@dataclass
class _Row:
    day: str
    franja: str
    slot_id: str
    presentiality: str
    work_mode: str = "NORMAL"
    position: int = 1


def _solve(model) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return solver


class TestPeonadaMonthlyCapDegenerate:
    """Branques degenerades: input buit, cap 0, comodí, jornada 0, etc."""

    def test_no_no_pres_returns_empty(self):
        model = cp_model.CpModel()
        slot_keys = [("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL", "NORMAL", 1)]
        pn_vars, _ = _add_peonada_monthly_cap(
            model, {}, ["P1"], slot_keys, {"P1": 100},
        )
        assert pn_vars == {}

    def test_zero_cap_returns_empty(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "TARDA", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], [sk], {"P1": 100},
            cap_per_month_full_time=0,
        )
        assert pn_vars == {}

    def test_fallback_excluded(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "TARDA", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {("TLD", sk): model.NewBoolVar("x_tld")}
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["TLD"], [sk], {"TLD": 100},
            fallback_professionals={"TLD"},
        )
        # El comodi no genera peonades — esta exempt.
        assert pn_vars == {}

    def test_zero_capacity_no_cap(self):
        model = cp_model.CpModel()
        sk = ("2026-01-06", "TARDA", "TC_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        x = {("P1", sk): model.NewBoolVar("x")}
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], [sk], {"P1": 0},
            cap_per_month_full_time=3,
        )
        # round(3 * 0 / 100) = 0 -> sense cap útil -> cap pn var.
        assert pn_vars == {}


class TestPeonadaMonthlyCapVariables:
    """Verifica que es creen `pn` per cada NO_PRES no-revisió assignat
    al facultatiu regular, i que el cap mensual es respecta."""

    def test_one_pn_per_no_pres(self):
        model = cp_model.CpModel()
        slot_keys = [
            ("2026-01-06", "TARDA", f"SLOT{i}", "NO_PRESENCIAL", "NORMAL", 1)
            for i in range(1, 5)
        ]
        x = {("P1", sk): model.NewBoolVar(f"x_{i}") for i, sk in enumerate(slot_keys)}
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
        )
        # 4 NO_PRES -> 4 pn vars.
        assert len(pn_vars) == 4
        for sk in slot_keys:
            assert (("P1", sk)) in pn_vars

    def test_cap_enforced_full_time(self):
        # 5 NO_PRES disponibles, totes assignades. Cap = 3 -> sum(pn) <= 3.
        # Maximitzem sum(pn) per verificar el cap.
        model = cp_model.CpModel()
        slot_keys = [
            ("2026-01-06", "TARDA", f"SLOT{i}", "NO_PRESENCIAL", "NORMAL", 1)
            for i in range(1, 6)
        ]
        x = {("P1", sk): model.NewBoolVar(f"x_{i}") for i, sk in enumerate(slot_keys)}
        for v in x.values():
            model.Add(v == 1)
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
        )
        model.Maximize(sum(pn_vars.values()))
        solver = _solve(model)
        assert solver.ObjectiveValue() == 3.0

    def test_cap_scaled_by_capacity(self):
        # Jornada 70%, cap = round(3 * 70 / 100) = 2.
        model = cp_model.CpModel()
        slot_keys = [
            ("2026-01-06", "TARDA", f"SLOT{i}", "NO_PRESENCIAL", "NORMAL", 1)
            for i in range(1, 5)
        ]
        x = {("P1", sk): model.NewBoolVar(f"x_{i}") for i, sk in enumerate(slot_keys)}
        for v in x.values():
            model.Add(v == 1)
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 70},
            cap_per_month_full_time=3,
        )
        model.Maximize(sum(pn_vars.values()))
        solver = _solve(model)
        # round(3 * 0.7) = 2.
        assert solver.ObjectiveValue() == 2.0

    def test_pn_limited_by_x(self):
        # Cap = 3, només 1 slot assignat → max pn = 1.
        model = cp_model.CpModel()
        slot_keys = [
            ("2026-01-06", "TARDA", f"SLOT{i}", "NO_PRESENCIAL", "NORMAL", 1)
            for i in range(1, 4)
        ]
        x = {("P1", sk): model.NewBoolVar(f"x_{i}") for i, sk in enumerate(slot_keys)}
        model.Add(x[("P1", slot_keys[0])] == 1)
        model.Add(x[("P1", slot_keys[1])] == 0)
        model.Add(x[("P1", slot_keys[2])] == 0)
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
        )
        model.Maximize(sum(pn_vars.values()))
        solver = _solve(model)
        assert solver.ObjectiveValue() == 1.0


class TestPeonadaMonthlyCapReviewsExcluded:
    """Les revisions NO poden ser peonades (queden fora del conjunt
    elegible)."""

    def test_review_slot_not_eligible(self):
        model = cp_model.CpModel()
        sk_review = ("2026-01-06", "MATI", "REVISIO_RM", "NO_PRESENCIAL", "NORMAL", 1)
        sk_normal = ("2026-01-06", "MATI", "RM_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        slot_keys = [sk_review, sk_normal]
        x = {("P1", sk): model.NewBoolVar(f"x_{sk[2]}") for sk in slot_keys}
        for v in x.values():
            model.Add(v == 1)
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
            review_slots={"REVISIO_RM"},
        )
        assert (("P1", sk_review)) not in pn_vars
        assert (("P1", sk_normal)) in pn_vars


class TestPeonadaMonthlyCapDoubledExcluded:
    """Els slots DOBLATS (mateix (day, franja, slot_id) que apareix
    més d'un cop) NO poden ser peonades — només màquines d'un sol
    facultatiu."""

    def test_doubled_slot_not_eligible(self):
        model = cp_model.CpModel()
        # TC3 doblat: PRES + NP. Cap dels dos pot ser peonada.
        sk_doubled_pres = (
            "2026-01-06", "MATI", "TC3", "PRESENCIAL", "NORMAL", 1,
        )
        sk_doubled_np = (
            "2026-01-06", "MATI", "TC3", "NO_PRESENCIAL", "NORMAL", 1,
        )
        # RM_HUB únic NP: SÍ pot ser peonada.
        sk_single_np = (
            "2026-01-06", "MATI", "RM_HUB", "NO_PRESENCIAL", "NORMAL", 1,
        )
        slot_keys = [sk_doubled_pres, sk_doubled_np, sk_single_np]
        x = {("P1", sk): model.NewBoolVar(f"x_{sk[2]}_{sk[3]}") for sk in slot_keys}
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
        )
        # NP doblat → exclòs
        assert (("P1", sk_doubled_np)) not in pn_vars
        # PRES (sempre exclòs per ser PRES)
        assert (("P1", sk_doubled_pres)) not in pn_vars
        # NP únic → inclòs
        assert (("P1", sk_single_np)) in pn_vars

    def test_doubled_np_only_not_eligible(self):
        # Doblat amb 2 NP: no és peonada (tampoc).
        model = cp_model.CpModel()
        sk_np1 = ("2026-01-06", "MATI", "TC3", "NO_PRESENCIAL", "NORMAL", 1)
        sk_np2 = ("2026-01-06", "MATI", "TC3", "NO_PRESENCIAL", "NORMAL", 2)
        slot_keys = [sk_np1, sk_np2]
        x = {("P1", sk): model.NewBoolVar(f"x_{sk[5]}") for sk in slot_keys}
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
        )
        assert pn_vars == {}


class TestPeonadaMonthlyCapSecondaryExcluded:
    """Les màquines SECUNDÀRIES (les del camp `linked_to` del catàleg)
    no poden ser peonades encara que siguin NP i d'un sol facultatiu."""

    def test_secondary_not_eligible(self):
        model = cp_model.CpModel()
        # URG_DIR és secundària (TC3 té linked_to=URG_DIR al catàleg).
        sk_secondary = ("2026-01-06", "MATI", "URG_DIR", "NO_PRESENCIAL", "NORMAL", 1)
        # RM_HUB és primària única → SÍ pot ser peonada.
        sk_primary = ("2026-01-06", "MATI", "RM_HUB", "NO_PRESENCIAL", "NORMAL", 1)
        slot_keys = [sk_secondary, sk_primary]
        x = {("P1", sk): model.NewBoolVar(f"x_{sk[2]}") for sk in slot_keys}
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
            secondary_slot_ids={"URG_DIR"},
        )
        assert (("P1", sk_secondary)) not in pn_vars
        assert (("P1", sk_primary)) in pn_vars


class TestPeonadaMonthlyCapMultipleMonths:
    """Cap separat per mes."""

    def test_separate_monthly_caps(self):
        # Gener: 5 NO_PRES, cap = 3 -> max pn_gener = 3.
        # Febrer: 5 NO_PRES, cap = 3 -> max pn_febrer = 3.
        # Suma maxima = 6.
        model = cp_model.CpModel()
        jan_keys = [
            ("2026-01-06", "TARDA", f"SLOT{i}", "NO_PRESENCIAL", "NORMAL", 1)
            for i in range(1, 6)
        ]
        feb_keys = [
            ("2026-02-03", "TARDA", f"SLOT{i}", "NO_PRESENCIAL", "NORMAL", 1)
            for i in range(1, 6)
        ]
        slot_keys = jan_keys + feb_keys
        x = {("P1", sk): model.NewBoolVar(f"x_{i}") for i, sk in enumerate(slot_keys)}
        for v in x.values():
            model.Add(v == 1)
        pn_vars, _ = _add_peonada_monthly_cap(
            model, x, ["P1"], slot_keys, {"P1": 100},
            cap_per_month_full_time=3,
        )
        model.Maximize(sum(pn_vars.values()))
        solver = _solve(model)
        assert solver.ObjectiveValue() == 6.0
