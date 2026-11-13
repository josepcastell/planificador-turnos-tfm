import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import streamlit as st

from src.services.session_store import (
    SessionFileError,
    list_session_snapshots,
    read_session_file_manifest,
    safe_session_name,
)


@dataclass(frozen=True)
class SessionSidebarActions:
    restore_clicked: bool
    selected_snapshot: Path | None
    delete_session_clicked: bool
    save_version_clicked: bool = False
    # «Desar com a fitxer…»: carpeta triada (None = no s'ha pogut obrir la
    # finestra de Windows: es desa a l'Escriptori).
    export_requested: bool = False
    export_dir: str | None = None
    # «Obrir una sessió desada en fitxer»: {"data", "title", "replace"}.
    import_request: dict | None = None


def real_desktop() -> Path:
    """L'Escriptori de l'usuari (no la carpeta de PDF del portable)."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for cand in (home / "Desktop", home / "OneDrive" / "Desktop", home / "Escritorio"):
        if cand.is_dir():
            return cand
    return home


def _choose_export_dir() -> None:
    """Botó «Desar com a fitxer…»: finestra de Windows per triar la carpeta
    (s'executa abans del guió, com la de la carpeta dels PDF)."""
    from src.services.folder_picker import FolderPickerUnavailable, pick_folder
    initial = st.session_state.get("session_export_last_dir") or str(real_desktop())
    try:
        chosen = pick_folder(initial, "Tria on desar el fitxer de la sessió")
    except FolderPickerUnavailable:
        st.session_state["session_export_request"] = {"dir": None}
        return
    if chosen:
        st.session_state["session_export_last_dir"] = chosen
        st.session_state["session_export_request"] = {"dir": chosen}


def _render_open_session_file(sessions_root: Path) -> dict | None:
    """Obrir en aquest ordinador una sessió desada amb «Desar com a
    fitxer…» en un altre (p. ex. de la feina a casa)."""
    with st.sidebar.expander("📂 Obrir una sessió desada en fitxer", expanded=False):
        st.caption(
            "Per continuar aquí una sessió desada en un altre ordinador amb "
            "«💾 Desar com a fitxer…»."
        )
        nonce = st.session_state.get("session_import_nonce", 0)
        uploaded = st.file_uploader(
            "Fitxer de la sessió (.zip)", type=["zip"],
            key=f"session_import_{nonce}", label_visibility="collapsed",
        )
        if uploaded is None:
            return None
        data = uploaded.getvalue()
        try:
            meta = read_session_file_manifest(data)
        except SessionFileError as exc:
            st.error(str(exc))
            return None
        title = meta.get("section") or Path(uploaded.name).stem
        saved = meta.get("saved_at", "")[:16].replace("T", " ")
        st.markdown(f"Sessió **{title}**" + (f", desada el {saved}" if saved else ""))
        if not (sessions_root / safe_session_name(title)).exists():
            if st.button("Obrir", type="primary", width="stretch", key="session_import_open"):
                return {"data": data, "title": title, "replace": False}
            return None
        st.warning(
            f"En aquest ordinador ja tens la sessió «{title}». Si la "
            "substitueixes, abans se'n desa una versió (la pots recuperar a "
            "Versions de la sessió)."
        )
        c_rep, c_copy = st.columns(2)
        if c_rep.button("Substituir-la", type="primary", width="stretch", key="session_import_replace"):
            return {"data": data, "title": title, "replace": True}
        if c_copy.button("Obrir com a còpia", width="stretch", key="session_import_copy"):
            k = 2
            while (sessions_root / safe_session_name(f"{title} {k}")).exists():
                k += 1
            return {"data": data, "title": f"{title} {k}", "replace": False}
    return None


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


def render_session_sidebar_actions(
    session_dir: Path, sessions_root: Path | None = None,
) -> SessionSidebarActions:
    st.sidebar.caption(f"Activa: {session_dir.name}")
    export_request = st.session_state.pop("session_export_request", None)

    snapshots = list_session_snapshots(session_dir)
    selected_snapshot: Path | None = None
    restore_clicked = False
    save_version_clicked = False
    with st.sidebar.container(border=True):
        st.markdown("**🕘 Versions de la sessió**")
        save_version_clicked = st.button(
            "Desar versió ara",
            width="stretch",
            key="sidebar_save_version",
            help="Crea una còpia datada de l'estat actual, restaurable "
                 "des d'aquí mateix.",
        )
        st.button(
            "💾 Desar com a fitxer…",
            width="stretch",
            key="sidebar_export_session",
            on_click=_choose_export_dir,
            help="Desa tota la sessió en un sol fitxer per obrir-la en un "
                 "altre ordinador (p. ex. de la feina a casa) amb «📂 Obrir "
                 "una sessió desada en fitxer».",
        )
        if snapshots:
            snapshot_names = [p.name for p in snapshots]
            selection = st.selectbox(
                "Versions desades",
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

    import_request = _render_open_session_file(sessions_root or session_dir.parent)

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
        export_requested=export_request is not None,
        export_dir=(export_request or {}).get("dir"),
        import_request=import_request,
    )
