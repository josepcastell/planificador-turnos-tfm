"""Editor inline de la tolerància ε de presencials/setmana. Es viu a
Mètriques i canvis finals › Altres restriccions: l'usuari l'ajusta
post-calendari-inicial per relaxar el target si cal."""
from pathlib import Path

import streamlit as st

from src.services.weekly_tolerance import (
    load_presential_tolerance,
    save_presential_tolerance,
)


def render_presential_tolerance_editor(
    path: Path | None = None,
    key_suffix: str = "",
) -> None:
    """Render del number_input + caption amb autosave. La tolerància és
    ESTRUCTURAL: s'aplica tant al calendari inicial com al definitiu
    (es llegeix de disc al moment del solve).

    `key_suffix` permet renderitzar l'editor en múltiples ubicacions
    (Calendari inicial + Restriccions) sense col·lisió de claus
    Streamlit."""
    tol_path = Path(path) if path is not None else Path(
        "data/metrics/presential_tolerance.txt"
    )
    current = load_presential_tolerance(tol_path)
    col1, col2 = st.columns([1, 5])
    with col1:
        new_value = st.number_input(
            "Tolerància ε (presencials i no-presencials/setm.)",
            min_value=0, max_value=10, value=int(current), step=1,
            key=f"presential_tolerance_input{key_suffix}",
        )
    with col2:
        st.caption(
            "Marge ± per a **presencials i no-presencials/setmana** respecte "
            "al target (si la diferència és ≤ ε no es penalitza). ε=0 força "
            "el target exacte. S'aplica al solver tant al calendari inicial "
            "com al definitiu."
        )
    if int(new_value) != int(current):
        save_presential_tolerance(tol_path, new_value)
        st.toast(f"Tolerància desada: ε={int(new_value)}", icon="✅")
