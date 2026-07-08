"""Test que el cap de cobertura per slot DOBLAT impedeix que un mateix
facultatiu cobreixi múltiples instàncies de la mateixa màquina el
mateix dia + franja.

Cas patològic abans del fix: TC3 doblat (PRES + NP a la mateixa franja
MATI) podia ser cobert per UN sol facultatiu (mateix prof a TC3 PRES
i a TC3 NP). El doblat perdia el sentit. Ara: instàncies a profs
DIFERENTS (obligatori)."""

from ortools.sat.python import cp_model

from src.solver.constraints import (
    _add_coverage_constraints,
    _build_decision_variables,
)


def test_doubled_machine_must_go_to_different_profs():
    """TC3 doblat (PRES + NP) MONDAY MATI: el solver ha d'assignar
    professionals DIFERENTS a les 2 instàncies."""
    sk_pres = ("2026-06-01", "MATI", "TC3", "PRESENCIAL", "NORMAL", 1)
    sk_np = ("2026-06-01", "MATI", "TC3", "NO_PRESENCIAL", "NORMAL", 2)
    slot_keys = [sk_pres, sk_np]
    professionals = ["A", "B"]
    model = cp_model.CpModel()
    x = _build_decision_variables(model, professionals, slot_keys)
    _add_coverage_constraints(model, x, professionals, slot_keys)
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # Cada instància ha de tenir exactament 1 prof.
    assert solver.Value(x[("A", sk_pres)]) + solver.Value(x[("B", sk_pres)]) == 1
    assert solver.Value(x[("A", sk_np)]) + solver.Value(x[("B", sk_np)]) == 1
    # I no poden ser els mateixos: si A cobreix PRES, ha de ser B qui
    # cobreix NP (o viceversa).
    if solver.Value(x[("A", sk_pres)]) == 1:
        assert solver.Value(x[("A", sk_np)]) == 0
        assert solver.Value(x[("B", sk_np)]) == 1
    else:
        assert solver.Value(x[("B", sk_pres)]) == 1
        assert solver.Value(x[("A", sk_np)]) == 1


def test_single_machine_only_one_prof():
    """Slot no doblat: un sol prof l'ocupa (com sempre)."""
    sk = ("2026-06-01", "MATI", "RM_A", "PRESENCIAL", "NORMAL", 1)
    professionals = ["A", "B"]
    model = cp_model.CpModel()
    x = _build_decision_variables(model, professionals, [sk])
    _add_coverage_constraints(model, x, professionals, [sk])
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(x[("A", sk)]) + solver.Value(x[("B", sk)]) == 1


def test_tld_exempt_can_cover_doubled():
    """El comodí TLD està exempt del cap de doblat: pot cobrir múltiples
    instàncies de la mateixa màquina si fa falta."""
    sk_pres = ("2026-06-01", "MATI", "TC3", "PRESENCIAL", "NORMAL", 1)
    sk_np = ("2026-06-01", "MATI", "TC3", "NO_PRESENCIAL", "NORMAL", 2)
    slot_keys = [sk_pres, sk_np]
    professionals = ["TLD"]
    model = cp_model.CpModel()
    x = _build_decision_variables(model, professionals, slot_keys)
    _add_coverage_constraints(
        model, x, professionals, slot_keys,
        unlimited_professionals=["TLD"],
    )
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(x[("TLD", sk_pres)]) == 1
    assert solver.Value(x[("TLD", sk_np)]) == 1
