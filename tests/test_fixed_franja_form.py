"""Franges fixes: afegir i editar fan servir els MATEIXOS camps i les
mateixes regles (`apply_fixed_franja`). Abans, afegir només deixava triar
una màquina presencial (+ secundària / doblar) i editar en mostrava uns
altres (dia, franja, presencialitat…)."""

import pandas as pd

from src.services.slot_templates import apply_fixed_franja

COLS = ["weekday_name", "franja", "slot_id", "presentiality", "work_mode",
        "required_staff", "is_active", "doubled", "linked_to",
        "week_interval", "week_offset"]


def _tpl(rows=()):
    return pd.DataFrame(
        [{"weekday_name": w, "franja": f, "slot_id": s, "presentiality": p,
          "work_mode": "NORMAL", "required_staff": 1, "is_active": 1,
          "doubled": 0, "linked_to": link, "week_interval": 1, "week_offset": 0}
         for w, f, s, p, link in rows],
        columns=COLS,
    )


def _cells(df):
    return sorted(
        (r.weekday_name, r.franja, r.slot_id, r.presentiality, str(r.linked_to or ""),
         int(r.required_staff))
        for r in df.itertuples(index=False)
    )


def test_add_a_non_presential_slot_directly():
    df = apply_fixed_franja(
        _tpl(), weekday_name="TUESDAY", franja="NIT", slot_id="RM1",
        presentiality="NO_PRESENCIAL",
    )
    assert _cells(df) == [("TUESDAY", "NIT", "RM1", "NO_PRESENCIAL", "", 1)]


def test_add_with_secondary_adds_it_and_links():
    df = apply_fixed_franja(
        _tpl(), weekday_name="MONDAY", franja="MATI", slot_id="TC1",
        presentiality="PRESENCIAL", linked_to="ING",
    )
    assert _cells(df) == [
        ("MONDAY", "MATI", "ING", "NO_PRESENCIAL", "", 1),
        ("MONDAY", "MATI", "TC1", "PRESENCIAL", "ING", 1),
    ]


def test_secondary_already_there_is_not_added_twice():
    df = apply_fixed_franja(
        _tpl([("MONDAY", "MATI", "ING", "PRESENCIAL", "")]),
        weekday_name="MONDAY", franja="MATI", slot_id="TC1",
        presentiality="PRESENCIAL", linked_to="ING",
    )
    assert ("MONDAY", "MATI", "ING", "PRESENCIAL", "", 1) in _cells(df)
    assert len(df) == 2


def test_add_doubled_makes_the_pair():
    df = apply_fixed_franja(
        _tpl(), weekday_name="MONDAY", franja="MATI", slot_id="RM1",
        presentiality="PRESENCIAL", doubled=True,
    )
    assert _cells(df) == [
        ("MONDAY", "MATI", "RM1", "NO_PRESENCIAL", "", 1),
        ("MONDAY", "MATI", "RM1", "PRESENCIAL", "", 1),
    ]


ORIG = {"weekday_name": "MONDAY", "franja": "MATI", "slot_id": "RM1",
        "presentiality": "PRESENCIAL", "work_mode": "NORMAL"}


def test_edit_moves_a_doubled_pair_together():
    df = _tpl([("MONDAY", "MATI", "RM1", "PRESENCIAL", ""),
               ("MONDAY", "MATI", "RM1", "NO_PRESENCIAL", "")])
    df = apply_fixed_franja(
        df, weekday_name="WEDNESDAY", franja="MATI", slot_id="RM1",
        presentiality="PRESENCIAL", doubled=True, original=ORIG,
    )
    assert _cells(df) == [
        ("WEDNESDAY", "MATI", "RM1", "NO_PRESENCIAL", "", 1),
        ("WEDNESDAY", "MATI", "RM1", "PRESENCIAL", "", 1),
    ]


def test_edit_undouble_removes_the_pair_partner():
    df = _tpl([("MONDAY", "MATI", "RM1", "PRESENCIAL", ""),
               ("MONDAY", "MATI", "RM1", "NO_PRESENCIAL", "")])
    df = apply_fixed_franja(
        df, weekday_name="MONDAY", franja="MATI", slot_id="RM1",
        presentiality="PRESENCIAL", doubled=False, original=ORIG,
    )
    assert _cells(df) == [("MONDAY", "MATI", "RM1", "PRESENCIAL", "", 1)]


def test_edit_keeps_the_link_and_frequency():
    df = _tpl([("MONDAY", "MATI", "TC1", "PRESENCIAL", "ING"),
               ("MONDAY", "MATI", "ING", "NO_PRESENCIAL", "")])
    df = apply_fixed_franja(
        df, weekday_name="MONDAY", franja="MATI", slot_id="TC1",
        presentiality="PRESENCIAL", linked_to="ING", week_interval=2, week_offset=1,
        original={**ORIG, "slot_id": "TC1"},
    )
    row = df[df["slot_id"] == "TC1"].iloc[0]
    assert row["linked_to"] == "ING"
    assert (int(row["week_interval"]), int(row["week_offset"])) == (2, 1)
    assert len(df) == 2


def test_edit_presentiality_of_a_doubled_pair_keeps_one_of_each():
    df = _tpl([("MONDAY", "MATI", "RM1", "PRESENCIAL", ""),
               ("MONDAY", "MATI", "RM1", "NO_PRESENCIAL", "")])
    df = apply_fixed_franja(
        df, weekday_name="MONDAY", franja="MATI", slot_id="RM1",
        presentiality="NO_PRESENCIAL", doubled=True, original=ORIG,
    )
    assert _cells(df) == [
        ("MONDAY", "MATI", "RM1", "NO_PRESENCIAL", "", 1),
        ("MONDAY", "MATI", "RM1", "PRESENCIAL", "", 1),
    ]
