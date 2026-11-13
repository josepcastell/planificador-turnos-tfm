"""Tests del comptatge de màquines ordinàries al balanç (`_add_ordinary_machine_balance`).

Regla del domini:
  - Doblades: cada facultatiu que ocupa una posició compta 1, ja sigui
    PRES o NP. Les 2 posicions del slot doblat son grups DIFERENTS.
  - Vinculades: un facultatiu que té el parell sencer compta 1 (les
    dues maquines col·lapsen en una sola).
  - Doblat + Vinculat: la part PRES (linkada al partner) i la part NP
    del doblat son grups SEPARATS. Cada facultatiu compta 1 per grup."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from src.solver.normalize import _make_slot_key
from src.solver.objectives_balance import _add_ordinary_machine_balance


@dataclass
class _Row:
    day: str
    franja: str
    slot_id: str
    presentiality: str
    work_mode: str = "NORMAL"
    position: int = 1


def _solve_machine_counts(model, machine_counts, profs):
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return {p: solver.Value(machine_counts[p]) for p in profs}


class TestOrdinaryBalanceDoubled:
    def test_doubled_pres_and_np_counted_separately(self):
        # Slot RM_A doblat: 2 files (PRES pos 1 + NP pos 1).
        # A esta a PRES, B esta a NP. Cada un compta 1.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL", position=1),
            _Row("2026-01-06", "MATI", "RM_A", "NO_PRESENCIAL", position=1),
        ]
        slot_keys = [_make_slot_key(r) for r in rows]
        x = {}
        for p in ["A", "B", "C"]:
            for sk in slot_keys:
                x[p, sk] = model.NewBoolVar(f"x_{p}_{sk[2]}_{sk[3]}")
        # A cobreix PRES, B cobreix NP.
        model.Add(x[("A", slot_keys[0])] == 1)
        model.Add(x[("B", slot_keys[1])] == 1)
        # Else x=0 per defecte (sense forçar).
        model.Add(x[("A", slot_keys[1])] == 0)
        model.Add(x[("B", slot_keys[0])] == 0)
        model.Add(x[("C", slot_keys[0])] == 0)
        model.Add(x[("C", slot_keys[1])] == 0)

        (_l1, _linf, _cum_l1, _cum_linf, machine_counts, _target) = \
            _add_ordinary_machine_balance(
                model, x, ["A", "B", "C"], ["A", "B", "C"],
                slot_keys, {"A": 100, "B": 100, "C": 100},
                review_slots=set(),
            )
        counts = _solve_machine_counts(model, machine_counts, ["A", "B", "C"])
        assert counts == {"A": 1, "B": 1, "C": 0}, counts


class TestOrdinaryBalanceLinked:
    def test_linked_pair_counts_as_one(self):
        # RM_A i RM_B linkats. A esta als dos -> compta 1.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL", position=1),
            _Row("2026-01-06", "MATI", "RM_B", "PRESENCIAL", position=1),
        ]
        slot_keys = [_make_slot_key(r) for r in rows]
        x = {("A", sk): model.NewBoolVar(f"x_{sk[2]}") for sk in slot_keys}
        model.Add(x[("A", slot_keys[0])] == 1)
        model.Add(x[("A", slot_keys[1])] == 1)
        (_l1, _linf, _cum_l1, _cum_linf, machine_counts, _target) = \
            _add_ordinary_machine_balance(
                model, x, ["A"], ["A"],
                slot_keys, {"A": 100},
                review_slots=set(),
                slot_links=[("RM_B", "RM_A")],
            )
        counts = _solve_machine_counts(model, machine_counts, ["A"])
        assert counts == {"A": 1}, counts


class TestOrdinaryBalanceDoubledAndLinked:
    """Cas combinat: RM_A doblat + linkat a RM_B.
    A esta a RM_A_PRES + RM_B (parell linkat): compta 1.
    B esta a RM_A_NP (la posicio NP del doblat): compta 1.
    Total = 2 ordinaries (una per A, una per B)."""

    def test_doubled_pres_linked_and_doubled_np_count_separately(self):
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL", position=1),
            _Row("2026-01-06", "MATI", "RM_A", "NO_PRESENCIAL", position=1),
            _Row("2026-01-06", "MATI", "RM_B", "PRESENCIAL", position=1),
        ]
        slot_keys = [_make_slot_key(r) for r in rows]
        x = {}
        for p in ["A", "B", "C"]:
            for sk in slot_keys:
                x[p, sk] = model.NewBoolVar(f"x_{p}_{sk[2]}_{sk[3]}")
        # A cobreix RM_A_PRES + RM_B (linkat). B cobreix RM_A_NP.
        model.Add(x[("A", slot_keys[0])] == 1)
        model.Add(x[("A", slot_keys[2])] == 1)
        model.Add(x[("A", slot_keys[1])] == 0)
        model.Add(x[("B", slot_keys[1])] == 1)
        for sk in slot_keys:
            if sk != slot_keys[1]:
                model.Add(x[("B", sk)] == 0)
        for sk in slot_keys:
            model.Add(x[("C", sk)] == 0)

        (_l1, _linf, _cum_l1, _cum_linf, machine_counts, _target) = \
            _add_ordinary_machine_balance(
                model, x, ["A", "B", "C"], ["A", "B", "C"],
                slot_keys, {"A": 100, "B": 100, "C": 100},
                review_slots=set(),
                slot_links=[("RM_B", "RM_A")],
            )
        counts = _solve_machine_counts(model, machine_counts, ["A", "B", "C"])
        assert counts == {"A": 1, "B": 1, "C": 0}, counts


class TestOrdinaryBalanceReviewExcluded:
    def test_review_slots_not_counted(self):
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL", position=1),
            _Row("2026-01-06", "MATI", "REVISIO_RM", "NO_PRESENCIAL", position=1),
        ]
        slot_keys = [_make_slot_key(r) for r in rows]
        x = {("A", sk): model.NewBoolVar(f"x_{sk[2]}") for sk in slot_keys}
        # A te tots dos slots.
        model.Add(x[("A", slot_keys[0])] == 1)
        model.Add(x[("A", slot_keys[1])] == 1)
        (_l1, _linf, _cum_l1, _cum_linf, machine_counts, _target) = \
            _add_ordinary_machine_balance(
                model, x, ["A"], ["A"], slot_keys, {"A": 100},
                review_slots={"REVISIO_RM"},
            )
        counts = _solve_machine_counts(model, machine_counts, ["A"])
        # Nomes RM_A compta (la revisio queda exclosa).
        assert counts == {"A": 1}, counts
