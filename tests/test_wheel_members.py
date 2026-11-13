"""Roda d'assignació: només els integrants poden fer l'activitat els dies de
la roda (si no n'hi ha cap de lliure, queda SENSE COBRIR), i dues rodes del
mateix dia no volen la mateixa persona. Cas real: dues rodes el dimecres
(RM1 i TC1) amb els mateixos integrants i el mateix ordre — cada setmana
demanaven la mateixa persona i el solver n'havia de trencar una."""

import pandas as pd

from src.domain.constants import UNCOVERED_PROFESSIONAL
from src.services.wheel_assignments import (
    expand_wheel_preassignments,
    save_wheel,
    wheel_members_by_day_slot,
)
from src.solver.core import build_and_solve_demo

MONDAYS = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]
PROFS = pd.DataFrame({"professional_id": ["P1", "P2", "P3"], "fallback": [0, 0, 0]})


def _month_cal(slots):
    return pd.DataFrame([
        {"day": d, "franja": "MATI", "slot_id": s,
         "presentiality": "PRESENCIAL", "work_mode": "NORMAL"}
        for d in MONDAYS for s in slots
    ])


def _setup(tmp_path, monkeypatch, wheels, slots):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "weekday").mkdir(parents=True)
    save_wheel(pd.DataFrame(wheels))
    _month_cal(slots).to_csv("data/weekday/calendar_slots.csv", index=False)


def test_two_wheels_same_day_do_not_want_the_same_person(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [
        {"slot_id": "RM1", "weekday_name": "MONDAY", "professionals": "P1;P2;P3"},
        {"slot_id": "TC1", "weekday_name": "MONDAY", "professionals": "P1;P2;P3"},
    ], ["RM1", "TC1"])
    rows = expand_wheel_preassignments(_month_cal(["RM1", "TC1"]), PROFS)
    turn = {(r.slot_id, r.day): r.professional_id for r in rows.itertuples()}
    rm1 = [turn[("RM1", d)] for d in MONDAYS]
    tc1 = [turn[("TC1", d)] for d in MONDAYS]
    assert rm1 == ["P1", "P2", "P3", "P1"]
    assert tc1 == ["P2", "P3", "P1", "P2"]  # el següent de la seva llista
    assert all(a != b for a, b in zip(rm1, tc1))


def test_members_only_for_wheels_with_a_list(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [
        {"slot_id": "RM1", "weekday_name": "MONDAY", "professionals": "P2;P3"},
        {"slot_id": "TC1", "weekday_name": "MONDAY", "professionals": ""},
    ], ["RM1", "TC1"])
    members = wheel_members_by_day_slot(_month_cal(["RM1", "TC1"]), PROFS)
    assert members == {(d, "RM1"): frozenset({"P2", "P3"}) for d in MONDAYS}


DAY = "2026-12-09"


def _solve(absent=()):
    data = {
        "professionals": pd.DataFrame({
            "professional_id": ["P1", "P2"], "name": ["P1", "P2"],
            "fallback": [0, 0], "presence_mode": ["", ""],
        }),
        "calendar_slots": pd.DataFrame({
            "day": [DAY, DAY], "franja": ["MATI", "TARDA"], "slot_id": ["A", "B"],
            "presentiality": ["NO_PRESENCIAL"] * 2, "work_mode": ["NORMAL"] * 2,
            "position": [1, 1],
        }),
        "unavailability": pd.DataFrame(
            [{"professional_id": p, "day": DAY, "reason": "vacances"} for p in absent],
            columns=["professional_id", "day", "reason"],
        ),
        "preassignments": pd.DataFrame(columns=[
            "professional_id", "day", "franja", "slot_id", "presentiality",
            "work_mode", "fixed", "source",
        ]),
        "eligibility": pd.DataFrame(columns=["professional_id", "slot_id", "allowed"]),
        "day_info": pd.DataFrame({"day": [DAY], "is_working_day": [1]}),
        "wheel_members": {(DAY, "A"): frozenset({"P1"})},
    }
    _text, rows, _metrics = build_and_solve_demo(data)
    return {r[2]: r[3] for r in rows}


def test_only_members_cover_the_wheel_activity():
    assert _solve()["A"] == "P1"


def test_no_free_member_leaves_it_uncovered_not_to_an_outsider(capsys):
    got = _solve(absent=["P1"])
    assert got["A"] == UNCOVERED_PROFESSIONAL
    assert got["B"] == "P2"
    tagged = [l for l in capsys.readouterr().out.splitlines() if l.startswith("SENSE_COBRIR\t")]
    assert len(tagged) == 1 and "només la poden fer els de la roda (P1)" in tagged[0]
