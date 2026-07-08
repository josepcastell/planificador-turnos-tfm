"""Tests de la vinculació de màquines PER (dia-setmana, franja):

  - Servei de grups al template (`set/clear/linked_groups_in_template`):
    múltiples grups, dissolució de grups previs solapats, límit de 5,
    localitat per (dia, franja).
  - Motor: l'acoblament dur i la compatibilitat diària només apliquen els
    (dia-setmana, franja) on el vincle existeix; el recompte setmanal mai
    deixa una màquina invisible els dies no vinculats; un bloc NP-NP no
    compta com a presencial; les cadenes (A,B)+(B,C) són UN sol bloc.
"""

from dataclasses import dataclass

import pandas as pd
from ortools.sat.python import cp_model

from src.services.slot_catalog import (
    MAX_LINKED_GROUP,
    clear_linked_group_in_template,
    linked_groups_in_template,
    set_linked_group_in_template,
)
from src.solver.constraints import (
    _add_coverage_constraints,
    _add_daily_compat_constraints,
    _add_structural_coupling,
    _build_machine_term_specs,
    _collect_machine_terms_for_day,
    _slot_groups_from_pairs,
)
from src.solver.normalize import _make_slot_key

# 2026-01-05 és DILLUNS; 2026-01-06 és DIMARTS.
MONDAY = "2026-01-05"
TUESDAY = "2026-01-06"


@dataclass
class _Row:
    day: str
    franja: str
    slot_id: str
    presentiality: str
    work_mode: str = "NORMAL"
    position: int = 1


def _template(rows) -> pd.DataFrame:
    """rows = [(weekday_name, franja, slot_id, linked_to), ...]"""
    return pd.DataFrame(
        [
            {
                "weekday_name": wd, "franja": fr, "slot_id": sid,
                "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
                "required_staff": 1, "is_active": 1, "linked_to": lk,
            }
            for wd, fr, sid, lk in rows
        ]
    )


def _build_x(model, professionals, slot_rows):
    x = {}
    for p in professionals:
        for r in slot_rows:
            sk = _make_slot_key(r)
            x[p, sk] = model.NewBoolVar(
                f"x_{p}_{r.day}_{r.franja}_{r.slot_id}_{r.position}"
                .replace("-", "_").replace(" ", "_")
            )
    return x


def _is_feasible(model: cp_model.CpModel) -> bool:
    solver = cp_model.CpSolver()
    return solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


class TestSlotGroupsFromPairs:
    def test_chain_is_one_block(self):
        assert _slot_groups_from_pairs([("A", "B"), ("B", "C")]) == [["A", "B", "C"]]

    def test_two_independent_blocks(self):
        assert _slot_groups_from_pairs([("A", "B"), ("C", "D")]) == [
            ["A", "B"], ["C", "D"],
        ]

    def test_empty(self):
        assert _slot_groups_from_pairs([]) == []
        assert _slot_groups_from_pairs(None) == []


class TestTemplateGroupService:
    def test_set_and_read_group_local_to_daykey(self):
        t = _template([
            ("MONDAY", "MATI", "A", ""),
            ("MONDAY", "MATI", "B", ""),
            ("MONDAY", "MATI", "C", ""),
            ("TUESDAY", "MATI", "A", ""),
            ("TUESDAY", "MATI", "B", ""),
        ])
        t = set_linked_group_in_template(t, "MONDAY", "MATI", ["A", "B", "C"])
        assert linked_groups_in_template(t, "MONDAY", "MATI") == [["A", "B", "C"]]
        # El MATEIX parell de màquines el dimarts NO està vinculat.
        assert linked_groups_in_template(t, "TUESDAY", "MATI") == []

    def test_new_group_dissolves_overlapping_prior_group(self):
        t = _template([
            ("MONDAY", "MATI", s, "") for s in ["A", "B", "C", "D"]
        ])
        t = set_linked_group_in_template(t, "MONDAY", "MATI", ["A", "B", "C"])
        # Nou grup [B, D]: el grup previ que contenia B es dissol sencer —
        # C NO pot quedar penjant apuntant a A.
        t = set_linked_group_in_template(t, "MONDAY", "MATI", ["B", "D"])
        assert linked_groups_in_template(t, "MONDAY", "MATI") == [["B", "D"]]

    def test_multiple_groups_same_daykey(self):
        t = _template([
            ("MONDAY", "MATI", s, "") for s in ["A", "B", "C", "D"]
        ])
        t = set_linked_group_in_template(t, "MONDAY", "MATI", ["A", "B"])
        t = set_linked_group_in_template(t, "MONDAY", "MATI", ["C", "D"])
        assert linked_groups_in_template(t, "MONDAY", "MATI") == [
            ["A", "B"], ["C", "D"],
        ]

    def test_max_group_size_truncates(self):
        slots = [f"S{i}" for i in range(MAX_LINKED_GROUP + 2)]
        t = _template([("MONDAY", "MATI", s, "") for s in slots])
        t = set_linked_group_in_template(t, "MONDAY", "MATI", slots)
        (group,) = linked_groups_in_template(t, "MONDAY", "MATI")
        assert len(group) == MAX_LINKED_GROUP

    def test_less_than_two_members_is_noop(self):
        t = _template([("MONDAY", "MATI", "A", "")])
        t2 = set_linked_group_in_template(t, "MONDAY", "MATI", ["A"])
        assert linked_groups_in_template(t2, "MONDAY", "MATI") == []

    def test_clear_group_only_in_daykey(self):
        t = _template([
            ("MONDAY", "MATI", "A", ""),
            ("MONDAY", "MATI", "B", ""),
            ("TUESDAY", "MATI", "A", ""),
            ("TUESDAY", "MATI", "B", ""),
        ])
        t = set_linked_group_in_template(t, "MONDAY", "MATI", ["A", "B"])
        t = set_linked_group_in_template(t, "TUESDAY", "MATI", ["A", "B"])
        t = clear_linked_group_in_template(t, "MONDAY", "MATI", "A")
        assert linked_groups_in_template(t, "MONDAY", "MATI") == []
        assert linked_groups_in_template(t, "TUESDAY", "MATI") == [["A", "B"]]

    def test_clear_nonmember_is_noop(self):
        t = _template([
            ("MONDAY", "MATI", "A", ""),
            ("MONDAY", "MATI", "B", ""),
        ])
        t = set_linked_group_in_template(t, "MONDAY", "MATI", ["A", "B"])
        t = clear_linked_group_in_template(t, "MONDAY", "MATI", "Z")
        assert linked_groups_in_template(t, "MONDAY", "MATI") == [["A", "B"]]


class TestPerDayStructuralCoupling:
    def _rows_both_days(self):
        return [
            _Row(MONDAY, "MATI", "A", "PRESENCIAL"),
            _Row(MONDAY, "MATI", "B", "PRESENCIAL"),
            _Row(TUESDAY, "MATI", "A", "PRESENCIAL"),
            _Row(TUESDAY, "MATI", "B", "PRESENCIAL"),
        ]

    def _build(self, links_by_wf):
        model = cp_model.CpModel()
        rows = self._rows_both_days()
        professionals = ["P1", "P2"]
        x = _build_x(model, professionals, rows)
        keys_by_day = {}
        for r in rows:
            keys_by_day.setdefault(r.day, []).append(_make_slot_key(r))
        _add_coverage_constraints(
            model, x, professionals, [_make_slot_key(r) for r in rows]
        )
        _add_structural_coupling(
            model, x, professionals, keys_by_day, links_by_wf=links_by_wf
        )
        return model, x, rows

    def test_link_applies_on_monday_not_on_tuesday(self):
        links = {("MONDAY", "MATI"): [("A", "B")]}
        # DILLUNS: persones diferents a A i B → infactible.
        model, x, rows = self._build(links)
        model.Add(x[("P1", _make_slot_key(rows[0]))] == 1)
        model.Add(x[("P2", _make_slot_key(rows[1]))] == 1)
        assert not _is_feasible(model)
        # DIMARTS: persones diferents a A i B → factible (no vinculades).
        model, x, rows = self._build(links)
        model.Add(x[("P1", _make_slot_key(rows[2]))] == 1)
        model.Add(x[("P2", _make_slot_key(rows[3]))] == 1)
        assert _is_feasible(model)


class TestPerDayDailyCompat:
    def _build(self, links_by_wf, force_day):
        model = cp_model.CpModel()
        rows = [
            _Row(MONDAY, "MATI", "A", "PRESENCIAL"),
            _Row(MONDAY, "MATI", "B", "NO_PRESENCIAL"),
            _Row(TUESDAY, "MATI", "A", "PRESENCIAL"),
            _Row(TUESDAY, "MATI", "B", "NO_PRESENCIAL"),
        ]
        professionals = ["P1"]
        x = _build_x(model, professionals, rows)
        _add_daily_compat_constraints(
            model, x, professionals, rows, [MONDAY, TUESDAY],
            review_slots=set(), links_by_wf=links_by_wf,
        )
        day_rows = [r for r in rows if r.day == force_day]
        for r in day_rows:
            model.Add(x[("P1", _make_slot_key(r))] == 1)
        return model

    def test_two_machines_same_franja_only_allowed_on_linked_day(self):
        links = {("MONDAY", "MATI"): [("A", "B")]}
        # DILLUNS (vinculades): P1 pot ocupar A i B a la mateixa franja.
        assert _is_feasible(self._build(links, MONDAY))
        # DIMARTS (no vinculades): P1 a A i B alhora → infactible. Sense el
        # filtre per dia, la unió global permetria aquest forat.
        assert not _is_feasible(self._build(links, TUESDAY))


class TestWeeklyCountingSpecs:
    def test_linked_slot_counts_on_non_linked_days(self):
        # A i B vinculades NOMÉS el dilluns: el dimarts han de ser màquines
        # NORMALS del recompte setmanal (mai invisibles).
        rows = [
            _Row(MONDAY, "MATI", "A", "PRESENCIAL"),
            _Row(MONDAY, "MATI", "B", "NO_PRESENCIAL"),
            _Row(TUESDAY, "MATI", "A", "PRESENCIAL"),
            _Row(TUESDAY, "MATI", "B", "NO_PRESENCIAL"),
        ]
        keys_by_day = {}
        for r in rows:
            keys_by_day.setdefault(r.day, []).append(_make_slot_key(r))
        specs = _build_machine_term_specs(
            keys_by_day, review_slots=set(),
            links_by_wf={("MONDAY", "MATI"): [("A", "B")]},
        )
        coupling_mon, machine_mon, pres_mon, _flip_mon = specs[MONDAY]
        assert len(coupling_mon) == 1  # un grup [A, B]
        assert machine_mon == []       # cap màquina fora del grup
        coupling_tue, machine_tue, pres_tue, flip_tue = specs[TUESDAY]
        assert coupling_tue == []
        assert {sk[2] for sk in machine_tue} == {"A", "B"}
        assert {sk[2] for sk in pres_tue} == {"A"}
        assert {sk[2] for sk in flip_tue} == {"B"}

    def test_group_presential_only_if_any_member_is(self):
        rows_np = [
            _Row(MONDAY, "MATI", "A", "NO_PRESENCIAL"),
            _Row(MONDAY, "MATI", "B", "NO_PRESENCIAL"),
        ]
        keys_by_day = {MONDAY: [_make_slot_key(r) for r in rows_np]}
        specs = _build_machine_term_specs(
            keys_by_day, review_slots=set(),
            links_by_wf={("MONDAY", "MATI"): [("A", "B")]},
        )
        model = cp_model.CpModel()
        x = _build_x(model, ["P1"], rows_np)
        machine_terms, pres_terms = _collect_machine_terms_for_day(
            model, x, "P1", MONDAY, specs[MONDAY], "t",
        )
        # El bloc NP-NP compta 1 màquina però CAP presencial.
        assert len(machine_terms) == 1
        assert pres_terms == []

    def test_two_groups_same_day_count_two_machines(self):
        rows = [
            _Row(MONDAY, "MATI", "A", "PRESENCIAL"),
            _Row(MONDAY, "MATI", "B", "NO_PRESENCIAL"),
            _Row(MONDAY, "TARDA", "C", "PRESENCIAL"),
            _Row(MONDAY, "TARDA", "D", "NO_PRESENCIAL"),
        ]
        keys_by_day = {MONDAY: [_make_slot_key(r) for r in rows]}
        specs = _build_machine_term_specs(
            keys_by_day, review_slots=set(),
            links_by_wf={
                ("MONDAY", "MATI"): [("A", "B")],
                ("MONDAY", "TARDA"): [("C", "D")],
            },
        )
        model = cp_model.CpModel()
        x = _build_x(model, ["P1"], rows)
        machine_terms, pres_terms = _collect_machine_terms_for_day(
            model, x, "P1", MONDAY, specs[MONDAY], "t",
        )
        # Dos blocs diferents = 2 màquines (mai col·lapsats en un únic max).
        assert len(machine_terms) == 2
        assert len(pres_terms) == 2

    def test_chain_counts_as_single_block(self):
        rows = [
            _Row(MONDAY, "MATI", "A", "PRESENCIAL"),
            _Row(MONDAY, "MATI", "B", "NO_PRESENCIAL"),
            _Row(MONDAY, "MATI", "C", "NO_PRESENCIAL"),
        ]
        keys_by_day = {MONDAY: [_make_slot_key(r) for r in rows]}
        specs = _build_machine_term_specs(
            keys_by_day, review_slots=set(),
            links_by_wf={("MONDAY", "MATI"): [("A", "B"), ("B", "C")]},
        )
        coupling, machine, _pres, _flip = specs[MONDAY]
        assert len(coupling) == 1
        assert len(coupling[0]) == 3
        assert machine == []
