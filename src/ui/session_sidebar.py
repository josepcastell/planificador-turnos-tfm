from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import streamlit as st

from src.services.session_store import list_session_snapshots


@dataclass(frozen=True)
class SessionSidebarActions:
    restore_clicked: bool
    selected_snapshot: Path | None
    delete_session_clicked: bool
    save_version_clicked: bool = False


def _format_snapshot_name(name: str) -> str:
    try:
        ts = datetime.strptime(name[:15], "%Y%m%d_%H%M%S")
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return name


def _confirmed_button(label: str, key: str, help_text: str, warn_text: str) -> bool:
    """Botó destructiu amb confirmació de dos passos: el primer clic arma
    la confirmació (avís + Sí/Cancel·lar); només el segon clic executa."""
    armed_key = f"{key}_armed"
    if not st.session_state.get(armed_key):
        if st.sidebar.button(label, width="stretch", key=key, help=help_text):
            st.session_state[armed_key] = True
            st.rerun()
        return False
    st.sidebar.warning(warn_text)
    col_yes, col_no = st.sidebar.columns(2)
    confirmed = col_yes.button(
        "Sí, endavant", type="primary", width="stretch", key=f"{key}_yes",
    )
    if col_no.button("Cancel·lar", width="stretch", key=f"{key}_no"):
        st.session_state.pop(armed_key, None)
        st.rerun()
    if confirmed:
        st.session_state.pop(armed_key, None)
    return confirmed


def render_session_sidebar_actions(session_dir: Path) -> SessionSidebarActions:
    st.sidebar.caption(f"Activa: {session_dir.name}")

    snapshots = list_session_snapshots(session_dir)
    selected_snapshot: Path | None = None
    restore_clicked = False
    save_version_clicked = False
    with st.sidebar.expander("🕘 Versions de la sessió", expanded=False):
        save_version_clicked = st.button(
            "Desar versió ara",
            width="stretch",
            key="sidebar_save_version",
            help="Crea una còpia datada de l'estat actual, restaurable "
                 "des d'aquí mateix.",
        )
        if snapshots:
            snapshot_names = [p.name for p in snapshots]
            selection = st.selectbox(
                "Versions guardades",
                snapshot_names,
                format_func=_format_snapshot_name,
                key=f"snapshot_selector_{session_dir.name}",
            )
            selected_snapshot = session_dir / "_snapshots" / selection
            restore_clicked = st.button(
                "Restaurar versió",
                width="stretch",
                key=f"restore_snapshot_button_{session_dir.name}",
                help="Sobreescriu els fitxers de treball amb el contingut de "
                     "la versió seleccionada (abans es desa una còpia "
                     "automàtica de l'estat actual).",
            )
        else:
            st.caption("Cap versió guardada encara.")

    delete_session_clicked = False
    if session_dir.exists():
        delete_session_clicked = _confirmed_button(
            "🗑️ Eliminar sessió",
            key="delete_session_button",
            help_text="Elimina permanentment aquesta sessió guardada (carpeta + "
                      "totes les seves versions). Acció no reversible.",
            warn_text=f"S'eliminarà **{session_dir.name}** amb totes les seves "
                      "versions guardades. Aquesta acció no es pot desfer.",
        )

    return SessionSidebarActions(
        restore_clicked=restore_clicked,
        selected_snapshot=selected_snapshot,
        delete_session_clicked=delete_session_clicked,
        save_version_clicked=save_version_clicked,
    )
