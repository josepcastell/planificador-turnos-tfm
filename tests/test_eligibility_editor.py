"""Elegibilitat per facultatiu (Restriccions): en tornar a un facultatiu,
l'editor ha de mostrar el que hi ha desat al fitxer. Abans reutilitzava la
taula de la primera visita: una casella desmarcada (i desada) tornava a
sortir marcada, i el següent autodesat la reescrivia al fitxer — «es
tornen a marcar soles». Passava igual amb el TLD, que és un facultatiu
més d'aquest editor."""

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


def _script(path: str) -> None:
    from pathlib import Path as _Path
    from src.ui.eligibility_editor import render_eligibility_editor
    render_eligibility_editor(_Path(path), ["FA", "TLD"], ["RM1", "RM2"], "weekday")


def _write(path: Path, as_rm1: int) -> None:
    pd.DataFrame({
        "professional_id": ["FA", "FA", "TLD", "TLD"],
        "slot_id": ["RM1", "RM2", "RM1", "RM2"],
        "allowed": [as_rm1, 1, 1, 1],
    }).to_csv(path, index=False)


def test_returning_to_a_professional_shows_what_is_saved(tmp_path):
    path = tmp_path / "eligibility.csv"
    _write(path, as_rm1=1)
    at = AppTest.from_function(_script, args=(str(path),), default_timeout=30).run()
    assert at.selectbox[0].value == "FA"

    # La casella RM1 d'FA s'ha desmarcat i desat (l'autodesat escriu al moment).
    _write(path, as_rm1=0)
    at.selectbox[0].set_value("TLD").run()
    at.selectbox[0].set_value("FA").run()

    shown = at.dataframe[0].value
    assert shown.set_index("slot_id")["allowed"].astype(int).to_dict() == {"RM1": 0, "RM2": 1}
    saved = pd.read_csv(path).query("professional_id == 'FA'")
    assert saved.set_index("slot_id")["allowed"].to_dict() == {"RM1": 0, "RM2": 1}


def test_change_made_elsewhere_shows_up_without_switching(tmp_path):
    # Si el fitxer canvia des d'un altre lloc (p. ex. en restaurar una
    # versió de la sessió), l'editor (amb el mateix facultatiu triat) ho
    # ha de mostrar i no reescriure la versió vella.
    path = tmp_path / "eligibility.csv"
    _write(path, as_rm1=1)
    at = AppTest.from_function(_script, args=(str(path),), default_timeout=30).run()
    _write(path, as_rm1=0)
    at.run()
    shown = at.dataframe[0].value
    assert shown.set_index("slot_id")["allowed"].astype(int).to_dict() == {"RM1": 0, "RM2": 1}
    saved = pd.read_csv(path).query("professional_id == 'FA'")
    assert saved.set_index("slot_id")["allowed"].to_dict() == {"RM1": 0, "RM2": 1}
