"""Màquines DOBLADES (la mateixa màquina, presencial + no presencial: dues
persones) i vinculacions: ja no es fan al formulari de cada màquina sinó
als desplegables de sota del calendari de franges, i les doblades es
marquen amb 👥 a la graella."""

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.services.slot_templates import (
    apply_fixed_franja,
    doubled_slots_in_template,
    set_doubled_in_template,
)


def _tpl(rows):
    return pd.DataFrame([
        {"weekday_name": wd, "franja": fr, "slot_id": s, "presentiality": p,
         "work_mode": "NORMAL", "required_staff": 1, "is_active": 1, "doubled": 0,
         "linked_to": link, "week_interval": wi, "week_offset": wo}
        for wd, fr, s, p, link, wi, wo in rows
    ])


def test_double_and_undouble_a_machine():
    tpl = _tpl([
        ("TUESDAY", "MATI", "RM1", "PRESENCIAL", "", 2, 1),
        ("TUESDAY", "MATI", "TC1", "PRESENCIAL", "RM1", 1, 0),
        ("WEDNESDAY", "MATI", "RM1", "PRESENCIAL", "", 1, 0),
    ])
    out = set_doubled_in_template(tpl, "TUESDAY", "MATI", "RM1", True)
    assert doubled_slots_in_template(out, "TUESDAY", "MATI") == ["RM1"]
    assert doubled_slots_in_template(out, "WEDNESDAY", "MATI") == []   # per dia
    new = out[(out.slot_id == "RM1") & (out.presentiality == "NO_PRESENCIAL")].iloc[0]
    assert (new.weekday_name, new.week_interval, new.week_offset) == ("TUESDAY", 2, 1)

    back = set_doubled_in_template(out, "TUESDAY", "MATI", "RM1", False)
    assert doubled_slots_in_template(back, "TUESDAY", "MATI") == []
    # Es queda la presencial.
    rm1 = back[(back.weekday_name == "TUESDAY") & (back.slot_id == "RM1")]
    assert rm1.presentiality.tolist() == ["PRESENCIAL"]


def test_editing_keeps_link_and_doubling():
    tpl = _tpl([
        ("TUESDAY", "MATI", "RM1", "PRESENCIAL", "", 1, 0),
        ("TUESDAY", "MATI", "RM1", "NO_PRESENCIAL", "", 1, 0),
        ("TUESDAY", "MATI", "TC1", "PRESENCIAL", "RM1", 1, 0),
    ])
    # Editar TC1 (canviar-ne la freqüència) amb els valors que dona el
    # formulari: el vincle i la doblada es conserven.
    out = apply_fixed_franja(
        tpl, weekday_name="TUESDAY", franja="MATI", slot_id="TC1",
        presentiality="PRESENCIAL", linked_to="RM1", doubled=False,
        week_interval=2, week_offset=0,
        original={"weekday_name": "TUESDAY", "franja": "MATI", "slot_id": "TC1",
                  "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
    )
    assert out[out.slot_id == "TC1"].linked_to.tolist() == ["RM1"]
    assert doubled_slots_in_template(out, "TUESDAY", "MATI") == ["RM1"]


def _form(mode: str):
    import pandas as pd
    import streamlit as st

    from src.ui import weekday_slot_editor as w
    tpl = pd.DataFrame([
        {"weekday_name": "TUESDAY", "franja": "MATI", "slot_id": "RM1",
         "presentiality": "PRESENCIAL", "work_mode": "NORMAL", "required_staff": 1,
         "is_active": 1, "doubled": 0, "linked_to": "", "week_interval": 1, "week_offset": 0},
        {"weekday_name": "TUESDAY", "franja": "MATI", "slot_id": "RM1",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL", "required_staff": 1,
         "is_active": 1, "doubled": 0, "linked_to": "", "week_interval": 1, "week_offset": 0},
        {"weekday_name": "TUESDAY", "franja": "MATI", "slot_id": "TC1",
         "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL", "required_staff": 1,
         "is_active": 1, "doubled": 0, "linked_to": "", "week_interval": 1, "week_offset": 0},
    ])
    st.session_state["selected_fixed_work_slot_edit"] = {
        "weekday_name": "TUESDAY", "weekday_label": "Dimarts", "franja": "MATI",
        "slot_id": "RM1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
        "required_staff": 1, "doubled": 0,
    }
    w._render_selected_fixed_slot_editor(tpl, ["RM1", "TC1"], None, lambda: None, 2026)
    if mode == "grid":
        w._render_fixed_weekly_calendar(tpl)
    else:
        w._render_doubled_editor(tpl, None, lambda: None)
        w._render_linked_groups_editor(tpl, None, lambda: None)


def test_grid_marks_doubled_machines():
    at = AppTest.from_function(_form, args=("grid",), default_timeout=30).run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert labels.count("👥 RM1 · P") == 1 and labels.count("👥 RM1 · NP") == 1
    assert "TC1 · NP" in labels


def test_bottom_expanders_list_doubled_and_offer_np_machines_to_link():
    at = AppTest.from_function(_form, args=("panels",), default_timeout=30)
    at.session_state["dblgrp_wd"] = "TUESDAY"
    at.session_state["dblgrp_fr"] = "MATI"
    at.session_state["linkgrp_wd"] = "TUESDAY"
    at.session_state["linkgrp_fr"] = "MATI"
    at.run()
    assert not at.exception
    assert any("👥 RM1" in m.value for m in at.markdown)
    assert [b.label for b in at.button if b.label == "Desdoblar"] == ["Desdoblar"]
    # Doblar: només les que encara no ho són.
    assert at.multiselect(key="dblgrp_sel_TUESDAY_MATI").options == ["TC1"]
    # Vincular: també les no presencials (abans només presencials).
    assert at.multiselect(key="linkgrp_sel_TUESDAY_MATI").options == ["RM1", "TC1"]
