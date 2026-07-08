"""Editor inline del sostre màxim mensual de peonades (jornada
completa). Es viu a Mètriques i canvis finals › Altres restriccions:
és un sostre ajustable post-calendari-inicial."""
from pathlib import Path

import streamlit as st

from src.services.extraordinary_activity import (
    load_extraordinary_cap,
    save_extraordinary_cap,
)


def render_peonada_cap_editor(
    path: Path | None = None,
) -> None:
    """Render del number_input + caption amb autosave. El cap s'aplica
    tant al Generar com al Reajustar (es llegeix de disc al moment del
    solve)."""
    cap_path = Path(path) if path is not None else Path(
        "data/metrics/extraordinary_activity_cap.txt"
    )
    current = load_extraordinary_cap(cap_path)
    col1, col2 = st.columns([1, 5])
    with col1:
        new_value = st.number_input(
            "Peonades/mes (jornada completa)",
            min_value=0, max_value=31, value=int(current), step=1,
            key="extraordinary_cap_input",
        )
    with col2:
        st.caption(
            "Nombre de **peonades per facultatiu i mes** que el solver ha "
            "d'afegir (sobre slots no-presencials no-revisió). El valor "
            "és alhora target i sostre, proporcional a la jornada "
            "(arrodonit): jornada al 70% → round(N · 0,7). El comodí "
            "n'està exempt. Cal prémer **Regenerar afegint peonades** "
            "perquè s'apliqui."
        )
    if int(new_value) != int(current):
        save_extraordinary_cap(cap_path, new_value)
        st.toast(
            f"Peonades màx./mes (full-time): {int(new_value)}", icon="✅"
        )
