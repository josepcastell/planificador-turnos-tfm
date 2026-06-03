from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import streamlit as st

from src.services.session_store import list_session_snapshots


@dataclass(frozen=True)
class SessionSidebarActions:
    cleanup_clicked: bool
    restore_clicked: bool
    selected_snapshot: Path | None
    delete_session_clicked: bool


def _format_snapshot_name(name: str) -> str:
    try:
        ts = datetime.strptime(name[:15], "%Y%m%d_%H%M%S")
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return name


def render_session_sidebar_actions(session_dir: Path) -> SessionSidebarActions:
    st.sidebar.caption(f"Activa: {session_dir.name}")

    snapshots = list_session_snapshots(session_dir)
    selected_snapshot: Path | None = None
    restore_clicked = False
    if snapshots:
        snapshot_names = [p.name for p in snapshots]
        selection = st.sidebar.selectbox(
            "Versions guardades",
            snapshot_names,
            format_func=_format_snapshot_name,
            key=f"snapshot_selector_{session_dir.name}",
        )
        selected_snapshot = session_dir / "_snapshots" / selection
        restore_clicked = st.sidebar.button(
            "Restaurar versió",
            width="stretch",
            key=f"restore_snapshot_button_{session_dir.name}",
            help="Sobreescriu els fitxers de treball amb el contingut de la "
                 "versió seleccionada.",
        )

    cleanup_clicked = False
    delete_session_clicked = False
    if session_dir.exists():
        cleanup_clicked = st.sidebar.button(
            "Netejar sessió",
            width="stretch",
            key="cleanup_session_button",
            help="Esborra totes les entrades de la sessió actual i deixa el "
                 "workspace en estat inicial (fitxers buits amb les capçaleres).",
        )
        delete_session_clicked = st.sidebar.button(
            "🗑️ Eliminar sessió",
            width="stretch",
            key="delete_session_button",
            help="Elimina permanentment aquesta sessió guardada (carpeta + "
                 "totes les seves versions). Acció no reversible.",
        )

    return SessionSidebarActions(
        cleanup_clicked=cleanup_clicked,
        restore_clicked=restore_clicked,
        selected_snapshot=selected_snapshot,
        delete_session_clicked=delete_session_clicked,
    )
