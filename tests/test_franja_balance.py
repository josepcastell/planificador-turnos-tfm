"""Regles d'equilibri per FRANJA: «equilibrar els matins / les tardes»,
setmanal i mensual. Cas: P1 té fixades totes les tardes; sense regla,
l'equitat del total dona tots els matins a P2 (5 i 5); amb la regla de
matins, els matins es reparteixen entre tots dos."""

import pandas as pd
import pytest

from src.domain.planning_rules import PlanningRules
from src.solver.core import build_and_solve_demo

WEEK = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]


def _mornings(mode):
    slots = [(d, fr, s) for d in WEEK for fr, s in (("MATI", "A"), ("TARDA", "B"))]
    data = {
        "professionals": pd.DataFrame({
            "professional_id": ["P1", "P2"], "name": ["P1", "P2"],
            "fallback": [0, 0], "presence_mode": ["", ""],
        }),
        "calendar_slots": pd.DataFrame({
            "day": [d for d, _, _ in slots], "franja": [f for _, f, _ in slots],
            "slot_id": [s for _, _, s in slots],
            "presentiality": ["NO_PRESENCIAL"] * len(slots),
            "work_mode": ["NORMAL"] * len(slots), "position": [1] * len(slots),
        }),
        "unavailability": pd.DataFrame(columns=["professional_id", "day", "reason"]),
        "preassignments": pd.DataFrame([
            {"professional_id": "P1", "day": d, "franja": "TARDA", "slot_id": "B",
             "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL", "fixed": 1,
             "source": "user"}
            for d in WEEK
        ]),
        "eligibility": pd.DataFrame(columns=["professional_id", "slot_id", "allowed"]),
        "day_info": pd.DataFrame({"day": WEEK, "is_working_day": [1] * 5}),
        "planning_rules": PlanningRules(mode=mode),
    }
    _text, rows, _metrics = build_and_solve_demo(data)
    sched = pd.DataFrame(rows, columns=[
        "day", "franja", "slot_id", "professional", "presentiality", "work_mode", "is_flipped",
    ])
    return sched[sched["franja"] == "MATI"]["professional"].value_counts().to_dict()


def test_without_rule_total_equity_gives_all_mornings_to_one():
    assert _mornings("none").get("P2", 0) == 5


@pytest.mark.parametrize("mode", ["setmanal_matins", "mensual_matins"])
def test_morning_rule_spreads_mornings(mode):
    counts = _mornings(mode)
    assert sorted(counts.values()) == [2, 3]


def test_franja_modes_are_valid_rule_modes(tmp_path):
    for mode in ("setmanal_matins", "setmanal_tardes", "mensual_matins", "mensual_tardes"):
        path = tmp_path / f"{mode}.csv"
        PlanningRules(mode=mode).to_csv(path)
        assert PlanningRules.from_csv(path).mode == mode
