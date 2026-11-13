"""Quan falta gent i algú fa doble feina, les activitats que s'agrupen en un
mateix facultatiu són primer del mateix LLOC i, si no pot ser, de la
mateixa ACTIVITAT (camps del catàleg, pestanya Activitat). Ho fan igual el
solver i la substitució ràpida del Calendari."""

import pandas as pd

from src.solver.core import build_and_solve_demo
from src.ui.quick_add_panels import _cover_professional_cells

DAY = "2026-12-09"


def _doubled_pair(area: dict, activity: dict) -> set:
    """3 activitats al matí i 2 facultatius: un ha de fer-ne dues."""
    slots = ["A", "B", "C"]
    data = {
        "professionals": pd.DataFrame({
            "professional_id": ["P1", "P2"], "name": ["P1", "P2"],
            "fallback": [0, 0], "presence_mode": ["", ""],
        }),
        "calendar_slots": pd.DataFrame({
            "day": [DAY] * 3, "franja": ["MATI"] * 3, "slot_id": slots,
            "presentiality": ["NO_PRESENCIAL"] * 3, "work_mode": ["NORMAL"] * 3,
            "position": [1] * 3,
        }),
        "unavailability": pd.DataFrame(columns=["professional_id", "day", "reason"]),
        "preassignments": pd.DataFrame(columns=[
            "professional_id", "day", "franja", "slot_id", "presentiality",
            "work_mode", "fixed", "source",
        ]),
        "eligibility": pd.DataFrame(columns=["professional_id", "slot_id", "allowed"]),
        "day_info": pd.DataFrame({"day": [DAY], "is_working_day": [1]}),
        "slot_area": area,
        "slot_activity": activity,
    }
    _text, rows, _metrics = build_and_solve_demo(data)
    by_prof: dict = {}
    for r in rows:
        by_prof.setdefault(r[3], set()).add(r[2])
    (pair,) = [s for s in by_prof.values() if len(s) == 2]
    return pair


def test_same_place_first():
    # B i C són al lloc X; A a Y. Per activitat s'agruparien A i B (RM), però
    # el lloc passa per davant. (Sense cap preferència sortiria A+B.)
    pair = _doubled_pair(
        {"A": "Y", "B": "X", "C": "X"},
        {"A": "RM", "B": "RM", "C": "TC"},
    )
    assert pair == {"B", "C"}


def test_same_activity_when_place_is_the_same():
    pair = _doubled_pair(
        {"A": "X", "B": "X", "C": "X"},
        {"A": "RM", "B": "TC", "C": "RM"},
    )
    assert pair == {"A", "C"}


def test_quick_substitute_picks_who_is_already_in_the_same_place(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "reductions").mkdir(parents=True)
    pd.DataFrame({
        "slot_id": ["A", "B", "C"], "metric_family": ["RM", "TC", "RM"],
        "area": ["X", "Y", "X"],
    }).to_csv(tmp_path / "data" / "slot_catalog.csv", index=False)
    professionals = tmp_path / "professionals.csv"
    pd.DataFrame(
        [{"professional_id": p, "name": "", "non_working_weekdays": "",
          "presence_mode": "", "fallback": 0} for p in ("P1", "P2", "P3")]
    ).to_csv(professionals, index=False)
    # P1 és absent i deixa A (lloc X). P2 (lloc Y) té menys càrrega, però
    # P3 ja fa C, que és del mateix lloc: la doble feina va a P3.
    df = pd.DataFrame([
        {"day": DAY, "franja": "MATI", "slot_id": "A", "professional": "P1",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
        {"day": DAY, "franja": "MATI", "slot_id": "B", "professional": "P2",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
        {"day": DAY, "franja": "MATI", "slot_id": "C", "professional": "P3",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
        {"day": "2026-12-10", "franja": "MATI", "slot_id": "C", "professional": "P3",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
    ])
    _cover_professional_cells(
        df, df["professional"] == "P1", "P1", ["P1", "P2", "P3"],
        tmp_path / "absences.csv", tmp_path / "guards.csv", professionals,
    )
    assert df.loc[0, "professional"] == "P3"


def test_a_linked_block_is_not_grouping(capsys):
    # A i B (activitats diferents) són un bloc vinculat el dimecres al matí:
    # qui el fa no fa doble feina ni «agrupa» activitats.
    data = {
        "professionals": pd.DataFrame({
            "professional_id": ["P1"], "name": ["P1"],
            "fallback": [0], "presence_mode": [""],
        }),
        "calendar_slots": pd.DataFrame({
            "day": [DAY] * 2, "franja": ["MATI"] * 2, "slot_id": ["A", "B"],
            "presentiality": ["PRESENCIAL"] * 2, "work_mode": ["NORMAL"] * 2,
            "position": [1] * 2,
        }),
        "unavailability": pd.DataFrame(columns=["professional_id", "day", "reason"]),
        "preassignments": pd.DataFrame(columns=[
            "professional_id", "day", "franja", "slot_id", "presentiality",
            "work_mode", "fixed", "source",
        ]),
        "eligibility": pd.DataFrame(columns=["professional_id", "slot_id", "allowed"]),
        "day_info": pd.DataFrame({"day": [DAY], "is_working_day": [1]}),
        "links_by_wf": {("WEDNESDAY", "MATI"): [("A", "B")]},
        "slot_area": {"A": "X", "B": "Y"},
        "slot_activity": {"A": "RM", "B": "TC"},
    }
    build_and_solve_demo(data)
    log = capsys.readouterr().out
    assert "total_overload = 0" in log
    assert "total_double_other_place = 0" in log
    assert "total_double_other_activity = 0" in log
