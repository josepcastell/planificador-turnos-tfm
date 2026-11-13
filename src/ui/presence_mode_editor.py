"""Editor del TIPUS D'ACTIVITAT de cada facultatiu: totes, només presencial
o només no presencial (columna `presence_mode` de data/professionals.csv).
Viu a Restriccions › Altres restriccions; abans era la columna «Activitat»
de la pestanya Facultatius. Al solver és DUR
(`_add_presence_mode_constraints`) i les revisions hi queden fora."""
from pathlib import Path

import streamlit as st

from src.services.input_tables import PROFESSIONALS_COLUMNS, set_presence_mode
from src.services.table_io import read_table

PRESENCE_LABELS = {
    "": "Totes",
    "PRESENCIAL": "Només presencial",
    "NO_PRESENCIAL": "Només no presencial",
}
_PRESENCE_CODES = {v: k for k, v in PRESENCE_LABELS.items()}


def _save(professionals_path: Path, pid: str, key: str) -> None:
    label = st.session_state.get(key, "Totes")
    set_presence_mode(professionals_path, pid, _PRESENCE_CODES.get(label, ""))
    st.toast(f"{pid}: {label.lower()}", icon="✅")


def render_presence_mode_editor(professionals_path: Path) -> None:
    df = read_table(Path(professionals_path), PROFESSIONALS_COLUMNS)
    df["professional_id"] = df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    df = df[(df["professional_id"] != "") & (df["professional_id"] != "NONE")]
    if df.empty:
        st.info("Primer introdueix facultatius a la pestanya Facultatius.")
        return
    st.caption(
        "Per defecte cada facultatiu pot fer activitats presencials i no "
        "presencials. Aquí pots limitar algú a un sol tipus (p. ex. qui "
        "només fa telediagnòstic: **només no presencial**). És estricte; "
        "les revisions hi queden fora."
    )
    for row in df.sort_values("professional_id").itertuples(index=False):
        pid = row.professional_id
        mode = str(row.presence_mode or "").strip().upper()
        key = f"presence_mode_{pid}"
        # El valor sempre surt del disc; el canvi es desa al moment
        # (on_change), així mai no es reescriu amb un valor antic.
        st.session_state[key] = PRESENCE_LABELS.get(mode, "Totes")
        c_pid, c_mode = st.columns([1, 3], vertical_alignment="center")
        c_pid.markdown(f"**{pid}**")
        c_mode.selectbox(
            pid, list(PRESENCE_LABELS.values()), key=key,
            on_change=_save, args=(professionals_path, pid, key),
            label_visibility="collapsed",
        )
