"""Un canvi a mà al calendari (ajustos ràpids de Calendari o «Canvi
d'activitat») ha de tornar a fer el PDF dels mesos tocats, no només dels de
l'àmbit: si no, el PDF d'aquell mes quedava desfasat respecte del calendari
desat i de l'Excel."""

import pandas as pd

from src.services.schedule_editing import changed_months

COLS = ["day", "franja", "slot_id", "professional", "presentiality", "work_mode", "is_flipped"]


def _sched(rows):
    return pd.DataFrame(rows, columns=COLS).astype(str)


BASE = [
    ("2026-11-30", "MATI", "RM1", "FA", "PRESENCIAL", "NORMAL", "0"),
    ("2026-12-09", "MATI", "ING", "SENSE_COBRIR", "PRESENCIAL", "NORMAL", "0"),
    ("2026-12-10", "MATI", "URG", "FD", "PRESENCIAL", "NORMAL", "0"),
]


def test_assigning_an_uncovered_cell_touches_its_month_only():
    after = list(BASE)
    after[1] = ("2026-12-09", "MATI", "ING", "FC", "PRESENCIAL", "NORMAL", "0")
    assert changed_months(_sched(BASE), _sched(after), 2026) == {12}


def test_change_outside_the_scope_month_is_detected():
    after = list(BASE)
    after[0] = ("2026-11-30", "MATI", "RM1", "FD", "PRESENCIAL", "NORMAL", "0")
    assert changed_months(_sched(BASE), _sched(after), 2026) == {11}


def test_no_change_no_months_and_other_years_ignored():
    assert changed_months(_sched(BASE), _sched(BASE), 2026) == set()
    after = BASE + [("2027-01-04", "MATI", "RM1", "FA", "PRESENCIAL", "NORMAL", "0")]
    assert changed_months(_sched(BASE), _sched(after), 2026) == set()
