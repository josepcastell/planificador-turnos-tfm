"""Les ex-dures (preassignacions fixes i llocs) ara són TOVES amb el pes
màxim: un xoc de fixos ja no deixa el model INFEASIBLE — es viola el
mínim imprescindible i el solver segueix donant solució."""

import pandas as pd
from ortools.sat.python import cp_model

from src.solver.constraints import _add_preassignment_constraints


def _slot_key(day, franja, slot, pres="PRESENCIAL", mode="NORMAL", pos=1):
    return (day, franja, slot, pres, mode, pos)


def _preassign_df(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "professional_id", "day", "franja", "slot_id",
            "presentiality", "work_mode", "fixed", "source", "notes",
        ],
    )


class TestSoftFixedAssignments:
    def test_conflicting_fixed_rows_stay_feasible_with_one_miss(self):
        # Dues persones FIXADES a la mateixa màquina de capacitat 1:
        # abans el model era INFEASIBLE; ara ha de sortir una solució
        # amb exactament 1 fix incomplert.
        model = cp_model.CpModel()
        sk = _slot_key("2026-01-05", "MATI", "A")
        x = {
            (p, sk): model.NewBoolVar(f"x_{p}")
            for p in ("P1", "P2")
        }
        # Cobertura dura: exactament una persona a la màquina.
        model.Add(sum(x.values()) == 1)
        df = _preassign_df([
            ("P1", "2026-01-05", "MATI", "A", "PRESENCIAL", "NORMAL", 1, "", ""),
            ("P2", "2026-01-05", "MATI", "A", "PRESENCIAL", "NORMAL", 1, "", ""),
        ])
        total_miss = _add_preassignment_constraints(model, x, df, [sk])
        model.Minimize(total_miss)
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(total_miss) == 1

    def test_satisfiable_fixed_is_honored(self):
        model = cp_model.CpModel()
        sk = _slot_key("2026-01-05", "MATI", "A")
        x = {(p, sk): model.NewBoolVar(f"x_{p}") for p in ("P1", "P2")}
        model.Add(sum(x.values()) == 1)
        df = _preassign_df([
            ("P2", "2026-01-05", "MATI", "A", "PRESENCIAL", "NORMAL", 1, "", ""),
        ])
        total_miss = _add_preassignment_constraints(model, x, df, [sk])
        model.Minimize(total_miss)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(total_miss) == 0
        assert solver.Value(x[("P2", sk)]) == 1

    def test_availability_report_pinpoints_day_and_people(self):
        # 3 màquines al matí i només 1 facultatiu disponible (1 absent tot
        # el dia + 1 bloquejat al matí) → l'informe diu dia, franja i noms.
        from src.solver.core import _availability_problem_report
        keys_by_day = {
            "2026-01-05": [
                _slot_key("2026-01-05", "MATI", s) for s in ("A", "B", "C")
            ],
        }
        unav = pd.DataFrame([
            {"professional_id": "P1", "day": "2026-01-05", "franja": "",
             "presentiality": "", "reason": "vacances"},
            {"professional_id": "P2", "day": "2026-01-05", "franja": "MATI",
             "presentiality": "", "reason": "guardia"},
        ])
        report = _availability_problem_report(
            keys_by_day, ["P1", "P2", "P3", "NONE"], unav,
        )
        assert "2026-01-05" in report
        assert "Mati" in report
        assert "P1" in report and "P2" in report
        assert "calen fins a 3" in report and "1 de disponibles" in report

    def test_availability_report_empty_when_enough_people(self):
        from src.solver.core import _availability_problem_report
        keys_by_day = {
            "2026-01-05": [_slot_key("2026-01-05", "MATI", "A")],
        }
        report = _availability_problem_report(
            keys_by_day, ["P1", "P2"], pd.DataFrame(),
        )
        assert report == ""

    def test_non_fixed_rows_are_ignored(self):
        model = cp_model.CpModel()
        sk = _slot_key("2026-01-05", "MATI", "A")
        x = {("P1", sk): model.NewBoolVar("x_P1")}
        df = _preassign_df([
            ("P1", "2026-01-05", "MATI", "A", "PRESENCIAL", "NORMAL", 0, "", ""),
        ])
        total_miss = _add_preassignment_constraints(model, x, df, [sk])
        model.Add(x[("P1", sk)] == 0)
        model.Minimize(total_miss)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(total_miss) == 0
