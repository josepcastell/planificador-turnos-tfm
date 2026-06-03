"""Tests dels detectors de conflicte entre restriccions opcionals i
calendari inicial. Cada detector retorna una llista de missatges:
buida si no hi ha cap conflicte, descripcions human-readable si n'hi
ha."""

import pandas as pd

from src.services.restriction_conflicts import (
    detect_absences_conflicts,
    detect_eligibility_conflicts,
    detect_fixed_machines_conflicts,
    detect_guards_conflicts,
    detect_no_pres_weekday_conflicts,
    detect_pres_weekday_conflicts,
)


def _initial(rows):
    return pd.DataFrame(rows, columns=[
        "day", "franja", "slot_id", "professional", "presentiality",
    ])


class TestAbsencesConflicts:
    def test_no_conflict(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        abs_ = pd.DataFrame({
            "professional_id": ["BC"],
            "start_day": ["2026-06-01"], "end_day": ["2026-06-01"],
        })
        assert detect_absences_conflicts(initial, abs_) == []

    def test_conflict_detected(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
            ("2026-06-02", "TARDA", "RM_HUB", "AC", "PRESENCIAL"),
        ])
        abs_ = pd.DataFrame({
            "professional_id": ["AC"],
            "start_day": ["2026-06-01"], "end_day": ["2026-06-02"],
        })
        msgs = detect_absences_conflicts(initial, abs_)
        assert len(msgs) == 1
        assert "AC" in msgs[0]
        assert "2 assignacions" in msgs[0]

    def test_empty_inputs(self):
        assert detect_absences_conflicts(pd.DataFrame(), pd.DataFrame()) == []


class TestEligibilityConflicts:
    def test_conflict_detected(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
            ("2026-06-02", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        elig = pd.DataFrame({
            "professional_id": ["AC"], "slot_id": ["TC4"], "allowed": [0],
        })
        msgs = detect_eligibility_conflicts(initial, elig)
        assert len(msgs) == 1
        assert "AC" in msgs[0]
        assert "TC4" in msgs[0]

    def test_allowed_one_no_conflict(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        elig = pd.DataFrame({
            "professional_id": ["AC"], "slot_id": ["TC4"], "allowed": [1],
        })
        assert detect_eligibility_conflicts(initial, elig) == []


class TestNoPresWeekdayConflicts:
    def test_conflict_detected(self):
        # 2026-06-01 és dilluns.
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        prof = pd.DataFrame({
            "professional_id": ["AC"], "no_pres_weekdays": ["MONDAY"],
        })
        msgs = detect_no_pres_weekday_conflicts(initial, prof)
        assert len(msgs) == 1
        assert "AC" in msgs[0]
        assert "MONDAY" in msgs[0]

    def test_np_assignment_no_conflict(self):
        initial = _initial([
            ("2026-06-01", "TARDA", "RM_HUB", "AC", "NO_PRESENCIAL"),
        ])
        prof = pd.DataFrame({
            "professional_id": ["AC"], "no_pres_weekdays": ["MONDAY"],
        })
        assert detect_no_pres_weekday_conflicts(initial, prof) == []


class TestPresWeekdayConflicts:
    def test_conflict_detected(self):
        initial = _initial([
            ("2026-06-01", "TARDA", "RM_HUB", "AC", "NO_PRESENCIAL"),
        ])
        prof = pd.DataFrame({
            "professional_id": ["AC"], "pres_weekdays": ["MONDAY"],
        })
        msgs = detect_pres_weekday_conflicts(initial, prof)
        assert len(msgs) == 1
        assert "AC" in msgs[0]


class TestFixedMachinesConflicts:
    def test_conflict_detected(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        cat = pd.DataFrame({
            "slot_id": ["TC4"], "assignee": ["BC"],
        })
        msgs = detect_fixed_machines_conflicts(initial, cat)
        assert len(msgs) == 1
        assert "TC4" in msgs[0]
        assert "BC" in msgs[0]
        assert "AC" in msgs[0]

    def test_same_assignee_no_conflict(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        cat = pd.DataFrame({
            "slot_id": ["TC4"], "assignee": ["AC"],
        })
        assert detect_fixed_machines_conflicts(initial, cat) == []

    def test_empty_assignee_no_conflict(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        cat = pd.DataFrame({
            "slot_id": ["TC4"], "assignee": [""],
        })
        assert detect_fixed_machines_conflicts(initial, cat) == []


class TestGuardsConflicts:
    def test_conflict_detected(self):
        initial = _initial([
            ("2026-06-01", "MATI", "TC4", "AC", "PRESENCIAL"),
        ])
        guards = pd.DataFrame({
            "professional_id": ["AC"], "day": ["2026-06-01"],
        })
        msgs = detect_guards_conflicts(initial, guards)
        assert len(msgs) == 1
        assert "AC" in msgs[0]
        assert "2026-06-01" in msgs[0]
