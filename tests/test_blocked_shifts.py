"""Elegibilitat per TORN (restricció pròpia): un facultatiu no ha de tenir
programació en una franja (matí, tarda o nit) un dia de la setmana — cada
setmana — o un dia concret. Es desa a data/blocked_shifts.csv i es
converteix en indisponibilitat de franja: dura al solver; la substitució
ràpida i l'avís de conflictes també la miren."""

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.services.input_tables import (
    add_blocked_shift,
    blocked_shift_checker,
    load_blocked_shifts,
    remove_blocked_shift,
)
from src.services.non_working_weekdays import blocked_shifts_unavailability
from src.services.restriction_conflicts import detect_blocked_shift_conflicts
from src.solver.core import build_and_solve_demo

MON, TUE, MON2 = "2026-01-05", "2026-01-06", "2026-01-12"


def test_weekly_and_dated_shifts(tmp_path):
    path = tmp_path / "blocked_shifts.csv"
    assert load_blocked_shifts(path).empty  # sense fitxer: buida
    add_blocked_shift(path, "fd", "tarda", weekday="monday")
    add_blocked_shift(path, "FD", "TARDA", weekday="MONDAY")  # no es repeteix
    add_blocked_shift(path, "FD", "MATI", day=TUE)
    assert load_blocked_shifts(path).values.tolist() == [
        ["FD", "MONDAY", "", "TARDA"], ["FD", "", TUE, "MATI"],
    ]
    blocked = blocked_shift_checker(load_blocked_shifts(path))
    assert blocked("FD", MON, "TARDA") and blocked("fd", MON2, "tarda")  # cada dilluns
    assert not blocked("FD", MON, "MATI")
    assert blocked("FD", TUE, "MATI")                                   # només aquell dia
    assert not blocked("FD", "2026-01-13", "MATI")
    assert not blocked("FA", MON, "TARDA")
    remove_blocked_shift(path, "FD", "TARDA", weekday="MONDAY")
    assert load_blocked_shifts(path).values.tolist() == [["FD", "", TUE, "MATI"]]


def test_becomes_franja_unavailability_on_matching_days():
    shifts = pd.DataFrame([
        {"professional_id": "FD", "weekday": "MONDAY", "day": "", "franja": "TARDA"},
        {"professional_id": "FA", "weekday": "", "day": TUE, "franja": "MATI"},
        {"professional_id": "FA", "weekday": "", "day": "2027-01-01", "franja": "MATI"},
    ])
    cal = pd.DataFrame({"day": [MON, TUE, MON2], "franja": ["TARDA"] * 3})
    unav = blocked_shifts_unavailability(shifts, cal)
    assert sorted(unav[["professional_id", "day", "franja"]].values.tolist()) == [
        ["FA", TUE, "MATI"], ["FD", MON, "TARDA"], ["FD", MON2, "TARDA"],
    ]
    assert set(unav["presentiality"]) == {""}


def _solve(unavailability):
    days = [MON, MON, TUE, TUE]
    data = {
        "professionals": pd.DataFrame({
            "professional_id": ["P1", "P2"], "name": ["P1", "P2"],
            "fallback": [0, 0], "presence_mode": ["", ""],
        }),
        "calendar_slots": pd.DataFrame({
            "day": days, "franja": ["MATI", "TARDA"] * 2, "slot_id": ["A", "B"] * 2,
            "presentiality": ["NO_PRESENCIAL"] * 4, "work_mode": ["NORMAL"] * 4,
            "position": [1] * 4,
        }),
        "unavailability": unavailability,
        "preassignments": pd.DataFrame(columns=[
            "professional_id", "day", "franja", "slot_id", "presentiality",
            "work_mode", "fixed", "source",
        ]),
        "eligibility": pd.DataFrame(columns=["professional_id", "slot_id", "allowed"]),
        "day_info": pd.DataFrame({"day": [MON, TUE], "is_working_day": [1, 1]}),
    }
    _text, rows, _metrics = build_and_solve_demo(data)
    return {(r[0], r[1]): r[3] for r in rows}


def _p1_absent_tuesday(extra=()):
    return pd.concat([
        *extra,
        pd.DataFrame([{"professional_id": "P1", "day": TUE, "franja": "",
                       "presentiality": "", "reason": "vacances",
                       "source": "absences", "notes": ""}]),
    ], ignore_index=True)


def test_solver_never_puts_him_in_that_shift():
    # P1 és absent dimarts (P2 ho fa tot). Sense la restricció, l'equitat
    # li donaria tot el dilluns a P1.
    assert _solve(_p1_absent_tuesday())[(MON, "TARDA")] == "P1"
    # P1 no ha de tenir programació dilluns a la tarda: la fa P2, encara que
    # vagi contra l'equitat. El dilluns al matí P1 sí que hi pot ser.
    for shift in (
        {"professional_id": "P1", "weekday": "MONDAY", "day": "", "franja": "TARDA"},
        {"professional_id": "P1", "weekday": "", "day": MON, "franja": "TARDA"},
    ):
        cal = pd.DataFrame({"day": [MON, TUE], "franja": ["TARDA", "TARDA"]})
        unav = blocked_shifts_unavailability(pd.DataFrame([shift]), cal)
        got = _solve(_p1_absent_tuesday([unav]))
        assert got[(MON, "TARDA")] == "P2"
        assert got[(MON, "MATI")] == "P1"


def test_quick_substitute_respects_the_blocked_shift(tmp_path, monkeypatch):
    from src.ui.quick_add_panels import _cover_professional_cells
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "reductions").mkdir(parents=True)
    add_blocked_shift(tmp_path / "data" / "blocked_shifts.csv", "P2", "TARDA", weekday="MONDAY")
    professionals = tmp_path / "professionals.csv"
    pd.DataFrame(
        [{"professional_id": p, "name": "", "non_working_weekdays": "",
          "presence_mode": "", "fallback": 0} for p in ("P1", "P2", "P3")]
    ).to_csv(professionals, index=False)
    # P1 deixa la tarda del dilluns. P2 té menys càrrega, però no ha de
    # tenir programació dilluns a la tarda → va a P3.
    df = pd.DataFrame([
        {"day": MON, "franja": "TARDA", "slot_id": "B", "professional": "P1",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
        {"day": TUE, "franja": "MATI", "slot_id": "A", "professional": "P3",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
    ])
    _cover_professional_cells(
        df, df["professional"] == "P1", "P1", ["P1", "P2", "P3"],
        tmp_path / "absences.csv", tmp_path / "guards.csv", professionals,
    )
    assert df.loc[0, "professional"] == "P3"


def test_conflict_with_the_current_calendar_is_reported():
    shifts = pd.DataFrame([
        {"professional_id": "FD", "weekday": "MONDAY", "day": "", "franja": "TARDA"},
        {"professional_id": "FA", "weekday": "", "day": TUE, "franja": "MATI"},
    ])
    cal = pd.DataFrame([
        {"day": MON, "franja": "TARDA", "slot_id": "B", "professional": "FD"},
        {"day": MON2, "franja": "TARDA", "slot_id": "B", "professional": "FD"},
        {"day": MON, "franja": "MATI", "slot_id": "A", "professional": "FD"},
        {"day": TUE, "franja": "MATI", "slot_id": "A", "professional": "FA"},
    ])
    assert detect_blocked_shift_conflicts(cal, shifts) == [
        "**FD** treballa 2 dilluns a la tarda al calendari (05/01, 12/01), "
        "però els dilluns a la tarda no pot treballar.",
        "**FA** treballa el 06/01/2026 al matí, però aquell dia al matí no "
        "pot treballar.",
    ]


def _editor(path: str) -> None:
    from pathlib import Path

    from src.ui.blocked_shifts_editor import render_blocked_shifts_editor
    render_blocked_shifts_editor(Path(path), ["FA", "FD"])


def test_own_editor_adds_weekly_and_dated_shifts(tmp_path):
    from datetime import date
    path = tmp_path / "blocked_shifts.csv"
    at = AppTest.from_function(_editor, args=(str(path),), default_timeout=30).run()
    assert not at.exception
    at.selectbox(key="bshift_prof_0").set_value("FD")
    at.selectbox(key="bshift_wd_0").set_value("THURSDAY")
    at.selectbox(key="bshift_fr_0").set_value("MATI")
    at.button[0].click().run()
    at.selectbox(key="bshift_prof_1").set_value("FA")
    at.date_input(key="bshift_day_1").set_value(date(2026, 12, 15))
    at.selectbox(key="bshift_fr_1").set_value("TARDA")
    at.button[0].click().run()
    assert not at.exception
    assert load_blocked_shifts(path).values.tolist() == [
        ["FD", "THURSDAY", "", "MATI"], ["FA", "", "2026-12-15", "TARDA"],
    ]
    texts = [m.value for m in at.markdown]
    assert "**FD** · cada **dijous** al **matí**" in texts
    assert "**FA** · **dimarts 15/12/2026** a la **tarda**" in texts
