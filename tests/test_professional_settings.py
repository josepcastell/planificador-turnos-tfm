"""El tipus d'activitat de cada facultatiu (totes / només presencial /
només no presencial) es configura a Restriccions, com els dies NP/PRES; el
comodí, a la pestanya Facultatius. Facultatius guarda un esborrany que es
carrega un cop per sessió: en desar-hi un nom, no pot tornar al valor antic
res del que s'ha canviat a Restriccions."""

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.services.input_tables import (
    PROFESSIONALS_COLUMNS,
    save_professional_scope,
    set_presence_mode,
    with_settings_from_disk,
)
from src.services.table_io import read_table


def _base(tmp_path):
    path = tmp_path / "professionals.csv"
    elig = tmp_path / "eligibility.csv"
    save_professional_scope(pd.DataFrame([
        {"professional_id": "FA", "name": "A", "fallback": 0, "presence_mode": ""},
        {"professional_id": "TLD", "name": "T", "fallback": 0, "presence_mode": ""},
    ]), path, elig)
    return path, elig


def _read(path):
    return read_table(path, PROFESSIONALS_COLUMNS).fillna("")


def _row(path, pid):
    return _read(path).set_index("professional_id").loc[pid]


def test_facultatius_save_keeps_what_restriccions_changed(tmp_path):
    path, elig = _base(tmp_path)
    draft = read_table(path, PROFESSIONALS_COLUMNS)  # esborrany carregat a l'inici
    # A Restriccions: TLD passa a només no presencial.
    set_presence_mode(path, "TLD", "NO_PRESENCIAL")
    # A Facultatius: es canvia l'identificador d'FA (i el nom).
    draft.loc[draft["professional_id"] == "FA", ["professional_id", "name"]] = ["FA2", "A2"]
    merged = with_settings_from_disk(draft, path, {"FA": "FA2"})
    save_professional_scope(merged, path, elig)

    assert _row(path, "TLD")["presence_mode"] == "NO_PRESENCIAL"
    assert _row(path, "FA2")["name"] == "A2"


def test_set_presence_mode_only_touches_that_column(tmp_path):
    path, _ = _base(tmp_path)
    before = _read(path)
    set_presence_mode(path, "fa", "PRESENCIAL")
    after = _read(path)
    modes = after.set_index("professional_id")["presence_mode"].to_dict()
    assert {p: modes[p] for p in ("FA", "TLD")} == {"FA": "PRESENCIAL", "TLD": ""}
    cols = [c for c in PROFESSIONALS_COLUMNS if c != "presence_mode"]
    pd.testing.assert_frame_equal(before[cols], after[cols])


def _script(path: str) -> None:
    from pathlib import Path as _Path
    from src.ui.presence_mode_editor import render_presence_mode_editor
    render_presence_mode_editor(_Path(path))


def test_editor_saves_and_follows_the_file(tmp_path):
    path, _ = _base(tmp_path)
    at = AppTest.from_function(_script, args=(str(path),), default_timeout=30).run()
    assert at.selectbox(key="presence_mode_TLD").value == "Totes"
    at.selectbox(key="presence_mode_TLD").set_value("Només no presencial").run()
    assert _row(path, "TLD")["presence_mode"] == "NO_PRESENCIAL"
    # Un canvi fet des d'un altre lloc (p. ex. restaurar una versió) es
    # mostra i no es reescriu amb el valor que tenia el desplegable.
    set_presence_mode(path, "TLD", "")
    at.run()
    assert at.selectbox(key="presence_mode_TLD").value == "Totes"
    assert _row(path, "TLD")["presence_mode"] == ""
