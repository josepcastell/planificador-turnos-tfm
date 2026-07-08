"""Editor de canvis manuals al calendari ja generat (anteriorment dins
de l'expander «Afegir guàrdia, permís o canvi d'activitat» de la
pestanya Generar i revisar).

Ara viu a Mètriques i canvis finals › Altres restriccions com a
expander «Canvi d'activitat»: l'usuari edita una assignació concreta
de l'schedule actual i la guarda com a preassignació, així el solver
la respecta a la pròxima generació/reajust."""
from pathlib import Path

import streamlit as st


def render_schedule_changes_editor(
    year: int,
    month: int,
    selected_months: list[int],
    professional_options: list[str],
    all_professional_options: list[str] | None = None,
) -> None:
    """Edita el calendari ja generat i desa els canvis com a
    preassignacions. La propera Generació/Reajust els respectarà."""
    from src.services.metrics_summary import load_schedule_for_display
    from src.services.schedule_editing import (
        save_planning_editor_changes,
        write_edited_schedule,
    )
    from src.services.table_io import dataframe_changed
    from src.ui.schedule_views import calendar_schedule_editor

    sched = load_schedule_for_display("outputs/schedule_weekday.csv")
    if sched is None or sched.empty:
        st.info("Genera primer el calendari per canviar assignacions.")
        return

    editor_cols = [
        c for c in
        ["day", "franja", "slot_id", "professional", "presentiality", "work_mode"]
        if c in sched.columns
    ]
    editable = sched[editor_cols].copy()
    profs = sorted(
        p for p in (all_professional_options or professional_options or [])
        if str(p).strip().upper() != "NONE"
    )
    edited, emonth = calendar_schedule_editor(
        editable, editable.columns.tolist(), profs, year, selected_months,
        "metrics_schedule_editor", "Canvia assignacions",
        visible_weekdays=[0, 1, 2, 3, 4], fixed_month=month,
    )
    if st.button(
        "Afegir canvi d'activitat",
        key="metrics_apply_changes", width="stretch",
    ):
        if dataframe_changed(editable, edited, editable.columns.tolist()):
            save_planning_editor_changes(
                editable, edited, Path("data/weekday/preassignments.csv"),
                year, emonth, months=selected_months,
            )
            write_edited_schedule(
                edited, Path("outputs/schedule_weekday.csv"),
                editable.columns.tolist(),
            )
            st.toast(
                "Canvi d'activitat afegit. Prem **Generar** o **Reajustar** "
                "perquè el planning incorpori els canvis.",
                icon="✅",
            )
        st.rerun()
    st.caption(
        "Quan acabis d'editar, prem **Generar** a la pestanya Generar i "
        "revisar (o **Reajustar** dins Mètriques) perquè el planning "
        "incorpori els canvis."
    )
