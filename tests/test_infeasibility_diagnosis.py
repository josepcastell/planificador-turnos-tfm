"""Diagnòstic de dies sense prou facultatius: explica per què hi ha
activitats SENSE COBRIR i ha de dir EXACTAMENT quins dies fallen. Abans
comptava cada slot per separat (vinculades i revisions incloses): llistava
dies que quadraven, el límit de 8 línies amagava els reals i culpava H5/H7
encara que no hi tinguessin res a veure. Cas real: una secció amb 4
facultatius, dimecres amb 4 activitats presencials sense vincles i una
absència aquell dia."""

import pandas as pd

from src.solver.core import (
    _availability_deficits,
    _availability_problem_report,
    _infeasibility_message,
)
from src.ui.command_progress import infeasibility_block

PROFS = ["P1", "P2", "P3", "P4", "NONE"]


def _sk(day, franja, slot, pres="PRESENCIAL", pos=1):
    return (day, franja, slot, pres, "NORMAL", pos)


def _absent(*rows):
    return pd.DataFrame(
        [{"professional_id": p, "day": d, "franja": f, "presentiality": "", "reason": ""}
         for p, d, f in rows]
    )


# 2026-12-07 és dilluns i 2026-12-09, dimecres.
MONDAY = "2026-12-07"
WEDNESDAY = "2026-12-09"
LINKS = {
    ("MONDAY", "MATI"): [("TC1", "URG"), ("URG", "ING")],
}


def _monday_keys():
    # Bloc TC1+URG+ING (1 persona) + RM1 + RM2 + revisió → calen 3 persones.
    return [_sk(MONDAY, "MATI", s) for s in ("ING", "RM1", "RM2", "TC1", "URG")] + [
        _sk(MONDAY, "MATI", "REVISIO", pres="NO_PRESENCIAL"),
    ]


def _wednesday_keys():
    # 4 presencials sense vincles + revisió → calen 4 persones.
    return [_sk(WEDNESDAY, "MATI", s) for s in ("ING", "RM1", "TC1", "URG")] + [
        _sk(WEDNESDAY, "MATI", "REVISIO", pres="NO_PRESENCIAL"),
    ]


def _report(keys_by_day, unav, **kwargs):
    kwargs.setdefault("review_slots", {"REVISIO"})
    kwargs.setdefault("links_by_wf", LINKS)
    return _availability_problem_report(keys_by_day, PROFS, unav, **kwargs)


def test_linked_block_and_review_do_not_count_as_extra_people():
    # Dilluns amb 1 absent: queden 3 i en calen 3 → quadra, no s'ha de llistar
    # (l'informe antic hi deia «calen fins a 6»).
    assert _report({MONDAY: _monday_keys()}, _absent(("P1", MONDAY, ""))) == ""


def test_monday_with_two_absent_is_reported():
    report = _report({MONDAY: _monday_keys()},
                     _absent(("P1", MONDAY, ""), ("P2", MONDAY, "")))
    assert (f"{MONDAY} (Dilluns, presencials): calen almenys 3 facultatius "
            "(ING + TC1 + URG, RM1, RM2) i només 2 de disponibles "
            "(no disponibles: P1, P2)") in report


def test_real_day_is_listed_and_false_alarms_are_not():
    # Dimecres amb un facultatiu absent → falla; un altre dimecres complet → quadra.
    other_wed = "2026-12-02"
    keys = {WEDNESDAY: _wednesday_keys(),
            other_wed: [(other_wed,) + sk[1:] for sk in _wednesday_keys()]}
    report = _report(keys, _absent(("P3", WEDNESDAY, "")))
    assert f"{WEDNESDAY} (Dimecres, presencials): calen almenys 4 facultatius" in report
    assert "ING, RM1, TC1, URG" in report
    assert "només 3 de disponibles (no disponibles: P3)" in report
    assert other_wed not in report
    assert "REVISIO" not in report


def test_daily_presential_cap_across_franges():
    # Una presencial al matí i una a la tarda: cap franja sola falla, però
    # ningú pot fer 2 presencials el mateix dia.
    keys = {WEDNESDAY: [_sk(WEDNESDAY, "MATI", "A"), _sk(WEDNESDAY, "TARDA", "B")]}
    unav = _absent(*[(p, WEDNESDAY, "") for p in ("P1", "P2", "P3")])
    report = _report(keys, unav)
    assert "calen almenys 2 facultatius (A, B)" in report
    assert "només 1 de disponibles" in report


def test_every_failing_day_is_shown_up_to_the_limit():
    days = [f"2027-01-{d:02d}" for d in range(4, 30) if pd.Timestamp(f"2027-01-{d:02d}").weekday() < 5]
    keys = {d: [_sk(d, "MATI", s) for s in ("A", "B", "C", "D", "E")] for d in days}
    report = _report(keys, pd.DataFrame())
    assert len(days) == 20
    assert report.count("calen almenys 5") == 12
    assert "… i 8 dies més amb el mateix problema" in report


def test_presential_comodi_absorbs_any_deficit():
    keys = {WEDNESDAY: _wednesday_keys()}
    unav = _absent(("P3", WEDNESDAY, ""))
    assert _report(keys, unav, unlimited_professionals={"TLD"}) == ""


def test_np_only_comodi_does_not_hide_presential_deficit():
    keys = {WEDNESDAY: _wednesday_keys()}
    unav = _absent(("P3", WEDNESDAY, ""))
    report = _report(keys, unav, unlimited_professionals={"TLD"},
                     presence_mode_by_prof={"TLD": "NO_PRESENCIAL"})
    assert "calen almenys 4 facultatius" in report
    assert "TLD" not in report


class _SolverStub:
    def SufficientAssumptionsForInfeasibility(self):
        return [0, 1]


def test_deficits_give_the_reason_per_day():
    # És el motiu que acompanya cada activitat SENSE COBRIR a l'avís.
    deficits = _availability_deficits(
        {WEDNESDAY: _wednesday_keys(), MONDAY: _monday_keys()}, PROFS,
        _absent(("P3", WEDNESDAY, "")), review_slots={"REVISIO"}, links_by_wf=LINKS,
    )
    assert list(deficits) == [WEDNESDAY]
    assert deficits[WEDNESDAY].startswith(
        "(Dimecres, presencials): calen almenys 4 facultatius"
    )


def test_infeasible_message_names_only_hard_constraints():
    # La manca de gent ja no fa el model infactible (queda SENSE COBRIR):
    # si ho és, és per una dura fràgil.
    names = {0: "H5 (acoblament de parells vinculats)",
             1: "H7 (continuïtat de revisió en festius)"}
    msg = _infeasibility_message(_SolverStub(), names)
    assert msg.startswith("Model infactible")
    assert "H5" in msg and "H7" in msg


def test_ui_shows_whole_diagnosis_instead_of_traceback_tail():
    out = "\n".join([
        "[Tram 1: presencial]  status=INFEASIBLE  obj=N/A",
        "Model infactible: alguns dies no hi ha prou facultatius per cobrir les activitats.",
        "PROBLEMA LOCALITZAT — ...",
        *[f"  · dia {i}" for i in range(15)],
        "Solucions, per a cada dia: ...",
        "",
    ])
    block = infeasibility_block(out)
    assert block.startswith("Model infactible")
    assert "dia 0" in block and "dia 14" in block and block.endswith("...")
    assert infeasibility_block("Traceback (most recent call last):\nKeyError: 'x'") == ""
