"""Tests del cap dur «màx 1 PRESENCIAL per dia per facultatiu» amb les
excepcions del domini:

1) Parells de slots VINCULATS: els dos slots del parell compten com a 1
   sola màquina (no bloca encara que el mateix facultatiu tingui ambdós
   el mateix dia, fins i tot tots dos presencials).
2) Slots de franja NIT: NO entren al cap diari. La nit és un torn
   diferent i pot coexistir amb una màquina diürna (MATI/TARDA) sense
   violar el límit. Així PRES MATI + PRES NIT al mateix dia és factible.

L'objectiu d'aquests tests és garantir que les dues excepcions queden
codificades al `_add_daily_compat_constraints` i no es trenquin per
errors futurs."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from src.solver.constraints import _add_daily_compat_constraints
from src.solver.normalize import _make_slot_key


@dataclass
class _Row:
    day: str
    franja: str
    slot_id: str
    presentiality: str
    work_mode: str = "NORMAL"
    position: int = 1


def _build_x(model, prof: str, rows: list[_Row]) -> dict:
    x = {}
    for r in rows:
        sk = _make_slot_key(r)
        x[prof, sk] = model.NewBoolVar(
            f"x_{prof}_{r.day}_{r.franja}_{r.slot_id}".replace("-", "_")
        )
    return x


def _is_feasible(model: cp_model.CpModel) -> bool:
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


class TestDailyPresCapBasic:
    def test_two_pres_same_day_blocked(self):
        # Cas de control: 2 PRES (MATI + TARDA) sense vincle, mateix dia
        # -> ha de ser INFEASIBLE quan forcem ambdues a 1.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "TC_A", "PRESENCIAL"),
            _Row("2026-01-06", "TARDA", "MAMO_A", "PRESENCIAL"),
        ]
        x = _build_x(model, "P1", rows)
        _add_daily_compat_constraints(
            model, x, ["P1"], rows, ["2026-01-06"], review_slots=set(),
            links_by_wf={},
        )
        # Forcem totes dues assignades
        for r in rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        assert not _is_feasible(model)

    def test_one_pres_one_no_pres_feasible(self):
        # 1 PRES + 1 NO_PRES mateix dia: ha de ser factible.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "TC_A", "PRESENCIAL"),
            _Row("2026-01-06", "TARDA", "MAMO_A", "NO_PRESENCIAL"),
        ]
        x = _build_x(model, "P1", rows)
        _add_daily_compat_constraints(
            model, x, ["P1"], rows, ["2026-01-06"], review_slots=set(),
            links_by_wf={},
        )
        for r in rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        assert _is_feasible(model)


class TestDailyPresCapLinkedException:
    """Excepció #1: parells vinculats compten com a 1 màquina."""

    def test_two_linked_pres_same_franja_feasible(self):
        # 2 PRES vinculades a MATI: factible (col·lapse OR -> 1 màquina).
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL"),
            _Row("2026-01-06", "MATI", "RM_B", "PRESENCIAL"),
        ]
        x = _build_x(model, "P1", rows)
        _add_daily_compat_constraints(
            model, x, ["P1"], rows, ["2026-01-06"], review_slots=set(),
            links_by_wf={("", ""): [("RM_B", "RM_A")]},
        )
        for r in rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        assert _is_feasible(model)

    def test_linked_pres_plus_extra_pres_blocked(self):
        # 2 PRES vinculades (= 1) + 1 PRES extra no vinculada (= 1):
        # suma = 2 -> infeasible.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL"),
            _Row("2026-01-06", "MATI", "RM_B", "PRESENCIAL"),
            _Row("2026-01-06", "TARDA", "TC_C", "PRESENCIAL"),
        ]
        x = _build_x(model, "P1", rows)
        _add_daily_compat_constraints(
            model, x, ["P1"], rows, ["2026-01-06"], review_slots=set(),
            links_by_wf={("", ""): [("RM_B", "RM_A")]},
        )
        for r in rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        assert not _is_feasible(model)


class TestDailyPresCapNitException:
    """Excepció #2: les màquines NIT no entren al cap diari de PRES."""

    def test_pres_nit_plus_pres_mati_feasible(self):
        # 1 PRES MATI + 1 PRES NIT: factible (NIT exempt del cap diari).
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "TC_A", "PRESENCIAL"),
            _Row("2026-01-06", "NIT", "TC_NIT", "PRESENCIAL"),
        ]
        x = _build_x(model, "P1", rows)
        _add_daily_compat_constraints(
            model, x, ["P1"], rows, ["2026-01-06"], review_slots=set(),
            links_by_wf={},
        )
        for r in rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        assert _is_feasible(model)

    def test_pres_nit_plus_two_diurnes_blocked(self):
        # 2 PRES diurnes (MATI + TARDA) + 1 PRES NIT: les dues diurnes
        # sumen 2 (per sobre del cap 1), el NIT no compta -> infeasible.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "TC_A", "PRESENCIAL"),
            _Row("2026-01-06", "TARDA", "MAMO_A", "PRESENCIAL"),
            _Row("2026-01-06", "NIT", "TC_NIT", "PRESENCIAL"),
        ]
        x = _build_x(model, "P1", rows)
        _add_daily_compat_constraints(
            model, x, ["P1"], rows, ["2026-01-06"], review_slots=set(),
            links_by_wf={},
        )
        for r in rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        assert not _is_feasible(model)

    def test_linked_pres_plus_nit_feasible(self):
        # Combinació de les dues excepcions: 2 PRES vinculades (MATI,
        # compten com 1) + 1 PRES NIT (exempt) -> factible.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL"),
            _Row("2026-01-06", "MATI", "RM_B", "PRESENCIAL"),
            _Row("2026-01-06", "NIT", "TC_NIT", "PRESENCIAL"),
        ]
        x = _build_x(model, "P1", rows)
        _add_daily_compat_constraints(
            model, x, ["P1"], rows, ["2026-01-06"], review_slots=set(),
            links_by_wf={("", ""): [("RM_B", "RM_A")]},
        )
        for r in rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        assert _is_feasible(model)
