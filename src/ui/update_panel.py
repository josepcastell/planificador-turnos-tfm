"""Panell d'auto-actualització a la barra lateral.

Mostra la versió actual, un botó per comprovar si n'hi ha una de nova al
GitHub i, si escau, un botó per baixar-la i aplicar-la (només el codi).
"""
import streamlit as st


def render_update_panel(app_root) -> None:
    from src.services import app_update as au

    cur = au.current_version(app_root)
    with st.sidebar.expander(f"🔄 Actualitzacions  ·  v{cur}", expanded=False):
        st.caption(
            "Actualitza el programa amb un clic. No esborra res ni perd les "
            "teves dades."
        )

        if st.button("Comprovar actualitzacions", key="upd_check", width="stretch"):
            for k in ("upd_latest", "upd_error", "upd_done", "upd_apply_error"):
                st.session_state.pop(k, None)
            try:
                st.session_state["upd_latest"] = au.latest_version()
            except Exception as exc:  # sense connexió / sense releases
                st.session_state["upd_error"] = str(exc)

        if st.session_state.get("upd_error"):
            st.warning(
                "No s'ha pogut comprovar (sense connexió o cap versió "
                "publicada encara)."
            )

        latest = st.session_state.get("upd_latest")
        if latest:
            if au.is_newer(latest, cur):
                st.success(f"Versió nova disponible: **{latest}** (tens la {cur}).")
                if st.button(
                    f"Actualitzar a {latest}", key="upd_apply",
                    type="primary", width="stretch",
                ):
                    st.session_state.pop("upd_apply_error", None)
                    try:
                        with st.spinner("Baixant i aplicant l'actualització…"):
                            data = au.download_update()
                            au.apply_update(app_root, data)
                        st.session_state["upd_done"] = latest
                    except Exception as exc:
                        st.session_state["upd_apply_error"] = str(exc)
            else:
                st.info(f"Ja tens l'última versió ({cur}). ✅")

        if st.session_state.get("upd_done"):
            st.success(
                f"✅ Actualitzat a {st.session_state['upd_done']}. "
                "**Tanca i torna a obrir l'app** per aplicar-ho."
            )
        if st.session_state.get("upd_apply_error"):
            st.error(
                "No s'ha pogut aplicar automàticament: "
                + st.session_state["upd_apply_error"]
                + ". Pots fer-ho manualment reemplaçant la carpeta `app`."
            )
