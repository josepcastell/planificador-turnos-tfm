"""Els formularis d'AFEGIR i d'EDITAR una franja mostren els mateixos camps
(abans eren diferents i resultava contraintuïtiu): franges fixes i canvis
puntuals del mes."""

from streamlit.testing.v1 import AppTest


def _fixed(mode: str) -> None:
    import pandas as pd
    import streamlit as st
    from src.ui import weekday_slot_editor as w
    tpl = pd.DataFrame([{
        "weekday_name": "TUESDAY", "franja": "TARDA", "slot_id": "RM1",
        "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL", "required_staff": 1,
        "is_active": 1, "doubled": 0, "linked_to": "", "week_interval": 1, "week_offset": 0,
    }])
    if mode == "add":
        st.session_state["selected_fixed_work_slot_cell"] = {
            "weekday_name": "TUESDAY", "weekday_label": "Dimarts", "franja": "TARDA",
        }
        w._render_selected_fixed_cell_editor(tpl, ["RM1", "TC1"], None, lambda: None, 2026)
    else:
        st.session_state["selected_fixed_work_slot_edit"] = {
            "weekday_name": "TUESDAY", "weekday_label": "Dimarts", "franja": "TARDA",
            "slot_id": "RM1", "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL",
            "required_staff": 1, "doubled": 0,
        }
        w._render_selected_fixed_slot_editor(tpl, ["RM1", "TC1"], None, lambda: None, 2026)


def _punctual(mode: str) -> None:
    import pandas as pd
    import streamlit as st
    from src.ui import weekday_slot_editor as w
    if mode == "add":
        st.session_state["selected_punctual_work_slot_cell"] = {
            "day": "2026-12-09", "franja": "MATI",
        }
        w._render_selected_punctual_cell_editor(pd.DataFrame(), ["RM1", "TC1"], None, lambda: None)
    else:
        st.session_state["selected_punctual_work_slot_edit"] = {
            "day": "2026-12-09", "franja": "MATI", "slot_id": "RM1",
            "presentiality": "PRESENCIAL", "work_mode": "NORMAL", "required_staff": 1,
        }
        w._render_selected_punctual_slot_editor(pd.DataFrame(), ["RM1", "TC1"], None, 2026, lambda: None)


def _fields(script, mode):
    at = AppTest.from_function(script, args=(mode,), default_timeout=30).run()
    assert not at.exception
    return (
        [s.label for s in at.selectbox] + [d.label for d in at.date_input]
        + [c.label for c in at.checkbox]
    ), at


def test_fixed_add_and_edit_show_the_same_fields():
    add, at_add = _fields(_fixed, "add")
    edit, at_edit = _fields(_fixed, "edit")
    # Vincular i doblar ja no són al formulari (desplegables de sota).
    assert add == edit == [
        "Dia", "Franja", "Activitat", "Presencialitat", "Freqüència",
    ]
    # En editar, els camps surten amb els valors de la franja.
    assert [s.value for s in at_edit.selectbox][:4] == ["TUESDAY", "TARDA", "RM1", "NO_PRESENCIAL"]
    # En afegir, el dia i la franja són els de la casella clicada.
    assert [s.value for s in at_add.selectbox][:2] == ["TUESDAY", "TARDA"]


def test_punctual_add_and_edit_show_the_same_fields():
    add, _ = _fields(_punctual, "add")
    edit, _ = _fields(_punctual, "edit")
    assert add == edit == ["Franja", "Activitat", "Presencialitat", "Dia"]
