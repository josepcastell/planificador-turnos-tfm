"""Quadre de mètriques clau: compta com el solver (un bloc vinculat aquell
dia i franja és una sola feina), separa revisions i peonades, i detecta
les dobles feines amb els mateixos límits que el solver."""

import pandas as pd

from src.domain.constants import UNCOVERED_PROFESSIONAL
from src.domain.schedule_format import set_slot_review_overrides
from src.services.key_metrics import key_metrics

MON, WED = "2026-12-07", "2026-12-09"


def _row(day, franja, slot, prof, pres="PRESENCIAL", mode="NORMAL"):
    return {"day": day, "franja": franja, "slot_id": slot, "professional": prof,
            "presentiality": pres, "work_mode": mode}


def _templates():
    # Dilluns al matí, ING + TC1 + URG són un sol bloc; el dimecres no.
    return pd.DataFrame([
        {"weekday_name": "MONDAY", "franja": "MATI", "slot_id": s, "linked_to": link}
        for s, link in (("ING", ""), ("TC1", "ING"), ("URG", "ING"))
    ] + [
        {"weekday_name": "WEDNESDAY", "franja": "MATI", "slot_id": s, "linked_to": ""}
        for s in ("ING", "TC1", "URG")
    ])


def _metrics(rows, **kw):
    set_slot_review_overrides({"REV"})
    try:
        table, uncovered = key_metrics(pd.DataFrame(rows), _templates(), **kw)
    finally:
        set_slot_review_overrides(set())
    return table.set_index("professional").to_dict("index"), uncovered


def test_linked_block_is_one_job_and_not_a_double():
    got, _ = _metrics([_row(MON, "MATI", s, "AA") for s in ("ING", "TC1", "URG")])
    assert got["AA"]["presencials"] == 1
    assert got["AA"]["dobles_feines"] == 0


def test_same_activities_unlinked_day_are_a_double():
    got, _ = _metrics([_row(WED, "MATI", s, "AA") for s in ("ING", "TC1", "URG")])
    assert got["AA"]["presencials"] == 3
    assert got["AA"]["dobles_feines"] == 1  # un dia


def test_reviews_peonades_and_night_are_counted_apart():
    got, uncovered = _metrics([
        _row(WED, "MATI", "ING", "AA"),
        _row(WED, "MATI", "REV", "AA", pres="NO_PRESENCIAL"),  # revisió: no és doble
        _row(WED, "NIT", "TC1", "AA"),  # nit presencial: no compta pel dia
        _row(MON, "TARDA", "URG", "AA", pres="NO_PRESENCIAL", mode="PEONADA"),
        _row(MON, "MATI", "ING", UNCOVERED_PROFESSIONAL),
    ])
    assert got["AA"] == {
        "presencials": 2, "no_presencials": 0, "peonades": 1,
        "revisions": 1, "dobles_feines": 0,
    }
    assert uncovered == 1


def test_two_presentials_morning_and_afternoon_is_a_double():
    got, _ = _metrics([_row(WED, "MATI", "ING", "AA"), _row(WED, "TARDA", "TC1", "AA")])
    assert got["AA"]["dobles_feines"] == 1


def test_comodi_is_left_out():
    got, _ = _metrics([_row(WED, "MATI", "ING", "TLD")], exclude={"TLD"})
    assert "TLD" not in got
