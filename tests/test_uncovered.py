"""Quan un dia hi ha menys facultatius disponibles que activitats, el
solver ja no torna INFEASIBLE (abans no sortia cap calendari). Els llocs de
feina s'omplen sí o sí: primer amb DOBLES FEINES (algú n'assumeix més d'una)
i, només si ningú no la pot fer, l'activitat queda SENSE COBRIR, en vermell
a l'app, al PDF i a l'Excel. Cas real: una secció de 4 facultatius on els
dimecres tenen 4 presencials i n'hi ha 1 d'absent."""

from types import SimpleNamespace

import pandas as pd

from src.domain.constants import UNCOVERED_PROFESSIONAL
from src.domain.schedule_format import (
    UNCOVERED_BG_HEX,
    UNCOVERED_LABEL,
    calendar_display_assignment_class,
    calendar_display_professional_label,
)
from src.solver.core import build_and_solve_demo

DAY = "2026-12-09"  # dimecres


def _data(profs, slots, absent=()):
    return {
        "professionals": pd.DataFrame({
            "professional_id": list(profs), "name": list(profs),
            "fallback": [0] * len(profs), "presence_mode": [""] * len(profs),
        }),
        "calendar_slots": pd.DataFrame({
            "day": [DAY] * len(slots), "franja": ["MATI"] * len(slots),
            "slot_id": list(slots), "presentiality": ["PRESENCIAL"] * len(slots),
            "work_mode": ["NORMAL"] * len(slots), "position": [1] * len(slots),
        }),
        "unavailability": pd.DataFrame(
            [{"professional_id": p, "day": DAY, "reason": "vacances"} for p in absent],
            columns=["professional_id", "day", "reason"],
        ),
        "preassignments": pd.DataFrame(columns=[
            "professional_id", "day", "franja", "slot_id", "presentiality",
            "work_mode", "fixed", "source", "notes",
        ]),
        "eligibility": pd.DataFrame(columns=["professional_id", "slot_id", "allowed"]),
        "day_info": pd.DataFrame({"day": [DAY], "is_working_day": [1]}),
    }


def _solve(profs, slots, absent=()):
    _text, rows, _metrics = build_and_solve_demo(_data(profs, slots, absent))
    return pd.DataFrame(rows, columns=[
        "day", "franja", "slot_id", "professional", "presentiality",
        "work_mode", "is_flipped",
    ])


def test_missing_staff_means_a_double_shift_not_an_empty_post(capsys):
    # Els llocs de feina s'omplen sí o sí: si falta gent, algú en fa dos.
    slots = ["ING", "RM1", "TC1", "URG"]
    sched = _solve(["P1", "P2", "P3", "P4"], slots, absent=["P4"])
    assert len(sched) == 4
    assert UNCOVERED_PROFESSIONAL not in set(sched["professional"])
    assert sorted(sched["professional"].value_counts().tolist()) == [1, 1, 2]
    out = capsys.readouterr().out
    doubles = [line for line in out.splitlines() if line.startswith("DOBLE_FEINA\t")]
    assert len(doubles) == 1
    assert "calen almenys 4 facultatius" in doubles[0]
    assert "no disponibles: P4" in doubles[0]


def test_uncovered_only_when_nobody_can_do_it(capsys):
    sched = _solve(["P1", "P2"], ["ING", "RM1"], absent=["P1", "P2"])
    assert list(sched["professional"]) == [UNCOVERED_PROFESSIONAL] * 2
    tagged = [l for l in capsys.readouterr().out.splitlines() if l.startswith("SENSE_COBRIR\t")]
    assert len(tagged) == 2


def test_no_holes_when_there_is_enough_staff():
    # Al contrari que un comodí, no s'usa mai si algú pot fer l'activitat.
    sched = _solve(["P1", "P2", "P3", "P4"], ["ING", "RM1", "TC1", "URG"])
    assert UNCOVERED_PROFESSIONAL not in set(sched["professional"])
    assert len(sched) == 4


def test_app_calendar_marks_uncovered_in_red():
    rows = [{"professional": UNCOVERED_PROFESSIONAL, "presentiality": "PRESENCIAL",
             "work_mode": "NORMAL"}]
    assert calendar_display_assignment_class(rows, "RM1", set()) == "sense-cobrir"
    assert calendar_display_professional_label(rows[0]) == UNCOVERED_LABEL


def test_pdf_cell_is_red_with_label():
    from src.tools.export_monthly_pdfs import (
        _presence_markup_lines, calendar_assignment_background, calendar_compact_line,
    )
    row = SimpleNamespace(professional=UNCOVERED_PROFESSIONAL, presentiality="PRESENCIAL",
                          work_mode="NORMAL", is_flipped=0, franja="MATI", slot_id="RM1")
    assert calendar_assignment_background([row], "RM1").hexval().upper() == \
        "0X" + UNCOVERED_BG_HEX.lstrip("#").upper()
    # Una paraula per línia perquè no es parteixi a mig mot a les columnes estretes.
    assert any("SENSE<br/>COBRIR" in line for line in _presence_markup_lines([row]))
    assert UNCOVERED_LABEL in calendar_compact_line(row)


def test_excel_cell_is_red_with_label():
    from src.services.excel_export import _cell_text_and_style
    rows = pd.DataFrame([{"professional": UNCOVERED_PROFESSIONAL,
                          "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
                          "is_flipped": 0}])
    text, font, fill = _cell_text_and_style(rows)
    assert text == UNCOVERED_LABEL
    assert font.bold
    assert fill.fgColor.rgb.endswith(UNCOVERED_BG_HEX.lstrip("#"))
