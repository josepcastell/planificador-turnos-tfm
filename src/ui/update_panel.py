"""Botó d'auto-actualització a la barra lateral.

Un sol clic ho fa tot: comprova si hi ha versió nova al GitHub i, si n'hi
ha, la baixa i l'aplica (només el codi — mai les dades). Sense desplegable.
"""
import streamlit as st


def render_update_panel(app_root) -> None:
    from src.services import app_update as au

    cur = au.current_version(app_root)
    if st.sidebar.button(
        f"🔄 Actualitzar (v{cur})",
        key="upd_go",
        width="stretch",
        help="Comprova si hi ha una versió nova i l'aplica amb un clic. "
             "No esborra res ni perd les teves dades.",
    ):
        for k in ("upd_error", "upd_done", "upd_uptodate"):
            st.session_state.pop(k, None)
        try:
            latest = au.latest_version()
            if au.is_newer(latest, cur):
                with st.spinner("Baixant i aplicant l'actualització…"):
                    data = au.download_update()
                    au.apply_update(app_root, data)
                st.session_state["upd_done"] = latest
            else:
                st.session_state["upd_uptodate"] = cur
        except Exception as exc:  # sense connexió / sense releases
            st.session_state["upd_error"] = str(exc)

    if st.session_state.get("upd_done"):
        st.sidebar.success(
            f"✅ Actualitzat a {st.session_state['upd_done']}. "
            "**Tanca i torna a obrir** el programa per aplicar-ho."
        )
    elif st.session_state.get("upd_uptodate"):
        st.sidebar.caption(f"Ja tens l'última versió ({st.session_state['upd_uptodate']}). ✅")
    elif st.session_state.get("upd_error"):
        st.sidebar.warning(
            "No s'ha pogut actualitzar (sense connexió o cap versió "
            "publicada). Torna-ho a provar més tard."
        )
