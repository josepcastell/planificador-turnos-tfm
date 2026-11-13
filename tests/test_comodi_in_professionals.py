"""El comodí (fallback) es marca a la pestanya Facultatius, en afegir o
editar un facultatiu, i surt a la taula (abans era un desplegable a part a
Restriccions)."""

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.services.input_tables import PROFESSIONALS_COLUMNS, save_professional_scope
from src.services.table_io import read_table


def _editor(prof_path: str, elig_path: str) -> None:
    from pathlib import Path

    import pandas as pd

    from src.services.table_io import read_table
    from src.ui.input_editors import render_professionals_editor
    df = read_table(Path(prof_path), [
        "professional_id", "name", "non_working_weekdays", "no_pres_weekdays",
        "pres_weekdays", "fallback", "presence_mode",
    ])
    render_professionals_editor(df, Path(prof_path), Path(elig_path))


def _fallback(path):
    df = read_table(path, PROFESSIONALS_COLUMNS)
    return dict(zip(df["professional_id"], pd.to_numeric(df["fallback"]).astype(int)))


def test_add_a_comodi_and_unmark_it(tmp_path):
    prof, elig = tmp_path / "professionals.csv", tmp_path / "eligibility.csv"
    save_professional_scope(pd.DataFrame([
        {"professional_id": "FA", "name": "A", "fallback": 0, "presence_mode": ""},
    ]), prof, elig)

    at = AppTest.from_function(_editor, args=(str(prof), str(elig)), default_timeout=30).run()
    assert [c.label for c in at.checkbox] == ["Comodí"]
    at.text_input(key="qa_pro_pid_-1").set_value("TLD")
    at.text_input(key="qa_pro_name_-1").set_value("Telediagnòstic")
    at.checkbox(key="qa_pro_fallback_-1").check()
    at.button[0].click().run()
    assert not at.exception
    assert _fallback(prof) == {"FA": 0, "NONE": 0, "TLD": 1}

    # Editar TLD (fila seleccionada a la taula) i treure-li el comodí. El
    # navegador manté la selecció entre clics; AppTest no: es torna a fixar.
    selected = {"selection": {"rows": [1], "columns": []}}
    at.session_state["base_professionals_view"] = selected
    at.run()
    assert at.text_input(key="qa_pro_pid_1").value == "TLD"
    assert at.checkbox(key="qa_pro_fallback_1").value is True
    at.checkbox(key="qa_pro_fallback_1").uncheck()
    at.session_state["base_professionals_view"] = selected
    at.button[0].click().run()
    assert not at.exception
    assert _fallback(prof)["TLD"] == 0
