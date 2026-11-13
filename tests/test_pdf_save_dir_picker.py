"""Carpeta on guardar PDF/Excel: es tria amb la finestra de Windows en
lloc d'escriure la ruta. Si la finestra no es pot obrir, el camp passa a
ser editable."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

import src.services.folder_picker as folder_picker


def _script(default: str) -> None:
    from pathlib import Path as _P
    import streamlit as st
    from src.ui.planning_calendar_tabs import _render_pdf_save_dir
    st.session_state["chosen_dir"] = str(_render_pdf_save_dir(_P(default)))


def _app(tmp_path):
    return AppTest.from_function(_script, args=(str(tmp_path / "PDFs"),), default_timeout=30)


def test_the_field_is_read_only_and_the_button_opens_the_window(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asked = {}

    def fake_pick(initial, title):
        asked["initial"] = initial
        return str(tmp_path / "Triada")

    monkeypatch.setattr(folder_picker, "pick_folder", fake_pick)
    at = _app(tmp_path).run()
    assert at.text_input[0].disabled
    at.button(key="pdf_save_dir_pick").click().run()
    assert asked["initial"] == str(tmp_path / "PDFs")  # obre on ja era
    assert at.session_state["chosen_dir"] == str(tmp_path / "Triada")
    # Es recorda per a la pròxima vegada.
    saved = (tmp_path / "data" / "pdf_save_dir.txt").read_text(encoding="utf-8")
    assert Path(saved) == tmp_path / "Triada"


def test_cancel_keeps_the_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(folder_picker, "pick_folder", lambda initial, title: None)
    at = _app(tmp_path).run()
    at.button(key="pdf_save_dir_pick").click().run()
    assert at.session_state["chosen_dir"] == str(tmp_path / "PDFs")


def test_without_the_window_the_path_can_be_typed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def broken(initial, title):
        raise folder_picker.FolderPickerUnavailable("no")

    monkeypatch.setattr(folder_picker, "pick_folder", broken)
    at = _app(tmp_path).run()
    at.button(key="pdf_save_dir_pick").click().run()
    assert not at.text_input[0].disabled
    at.text_input[0].set_value(str(tmp_path / "AMa")).run()
    assert at.session_state["chosen_dir"] == str(tmp_path / "AMa")
