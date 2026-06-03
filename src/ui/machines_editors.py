"""Editors de dades mestres relacionats amb el catàleg d'activitats,
extrets d'app.py per no barrejar lògica de negoci a l'entry point:

  · render_machines_locations_editor — llistes base de Màquines i Llocs
    (pestanya Activitat), fonts dels desplegables del quick-add.
  · render_fixed_machines_editor — assigna un facultatiu fix a una
    activitat (assignee del catàleg), a Restriccions › Altres restriccions.
"""
from pathlib import Path

import pandas as pd
import streamlit as st


def render_machines_locations_editor() -> tuple[list[str], list[str]]:
    """Llistes base de Màquines i Llocs: s'usen com a desplegables al
    quick-add del catàleg. Autodesat en canviar (persisteix entre sessions).
    Retorna (machines_list, locations_list) per al quick-add del catàleg."""
    from src.services.machines_locations import (
        load_locations,
        load_machines,
        save_locations,
        save_machines,
    )
    st.subheader("Màquines i Llocs")
    st.caption(
        "Llistes base d'opcions disponibles. S'usen com a desplegables al "
        "**quick-add** del catàleg de sota, per combinar màquina i lloc i "
        "crear cada activitat (p. ex. `TC` + `DIR` → `TC_DIR`)."
    )
    if "machines_list_input" not in st.session_state:
        st.session_state["machines_list_input"] = "\n".join(load_machines())
    if "locations_list_input" not in st.session_state:
        st.session_state["locations_list_input"] = "\n".join(load_locations())
    _ml_col_m, _ml_col_l = st.columns(2)
    with _ml_col_m:
        st.text_area("Màquines (una per línia)", height=140, key="machines_list_input")
    with _ml_col_l:
        st.text_area("Llocs (una per línia)", height=140, key="locations_list_input")
    _machines_list = [
        line.strip().upper()
        for line in st.session_state["machines_list_input"].splitlines()
        if line.strip()
    ]
    _locations_list = [
        line.strip().upper()
        for line in st.session_state["locations_list_input"].splitlines()
        if line.strip()
    ]
    # Auto-desat de les llistes en canviar (per persistir entre sessions).
    if _machines_list != load_machines():
        save_machines(_machines_list)
    if _locations_list != load_locations():
        save_locations(_locations_list)
    st.divider()
    return _machines_list, _locations_list


def render_fixed_machines_editor(slot_catalog_path: Path, all_professional_options) -> None:
    """Assigna un facultatiu fix a una activitat (columna `assignee` del
    catàleg): el solver no l'haurà de decidir. Inclou l'expander."""
    from src.services.slot_catalog import (
        load_slot_catalog as _load_cat_fm,
        save_slot_catalog as _save_cat_fm,
    )
    from src.ui.restriction_warnings import warn_fixed_machines_vs_initial

    with st.expander("Màquines fixes per facultatiu", expanded=False):
        st.caption(
            "Assigna un facultatiu a una activitat per fixar-la sempre: "
            "el solver no l'haurà de decidir."
        )
        _fm_cat = (
            st.session_state.get("slot_catalog_current")
            if isinstance(st.session_state.get("slot_catalog_current"), pd.DataFrame)
            else st.session_state.get("slot_catalog_draft")
        )
        if not isinstance(_fm_cat, pd.DataFrame) or _fm_cat.empty:
            _fm_cat = _load_cat_fm(slot_catalog_path)
        _fm_cat = _fm_cat.copy()
        if "assignee" not in _fm_cat.columns:
            _fm_cat["assignee"] = ""
        _fm_cat["assignee"] = (
            _fm_cat["assignee"].fillna("").astype(str).str.strip().str.upper()
        )
        _fm_assigned_mask = _fm_cat["assignee"] != ""
        _fm_rows = _fm_cat.loc[_fm_assigned_mask, ["assignee", "slot_id"]].copy()
        _fm_rows.columns = ["Facultatiu", "Activitat"]
        _fm_rows = (
            _fm_rows.sort_values(["Facultatiu", "Activitat"]).reset_index(drop=True)
        )

        if _fm_rows.empty:
            st.caption("_Cap màquina fixa assignada de moment._")
        else:
            st.dataframe(_fm_rows, hide_index=True, width="stretch")

        _fm_avail_slots = sorted(
            s for s in _fm_cat.loc[~_fm_assigned_mask, "slot_id"]
            .fillna("").astype(str).str.strip().str.upper().tolist()
            if s
        )
        _fm_profs = sorted(set(all_professional_options or []))

        with st.form("add_fixed_machine", clear_on_submit=True):
            _fm_cols = st.columns([2, 2, 1])
            with _fm_cols[0]:
                _fm_prof = st.selectbox(
                    "Facultatiu",
                    options=[""] + _fm_profs,
                    index=0,
                    format_func=lambda v: v or "Facultatiu…",
                )
            with _fm_cols[1]:
                _fm_slot = st.selectbox(
                    "Activitat",
                    options=[""] + _fm_avail_slots,
                    index=0,
                    format_func=lambda v: v or "Activitat…",
                )
            with _fm_cols[2]:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                _fm_submit = st.form_submit_button("Fixar", width="stretch")
            if _fm_submit:
                if not _fm_prof or not _fm_slot:
                    st.error("Cal triar facultatiu i activitat.")
                else:
                    _mask = (
                        _fm_cat["slot_id"].fillna("").astype(str)
                        .str.strip().str.upper() == _fm_slot
                    )
                    if _mask.any():
                        _fm_cat.loc[_mask, "assignee"] = _fm_prof
                        _save_cat_fm(slot_catalog_path, _fm_cat)
                        st.session_state["slot_catalog_draft"] = _fm_cat
                        st.session_state.pop("slot_catalog_current", None)
                        st.session_state["slot_catalog_editor_nonce"] = (
                            st.session_state.get("slot_catalog_editor_nonce", 0) + 1
                        )
                        st.toast(f"Fixat: {_fm_prof} → {_fm_slot}", icon="✅")
                        st.rerun()
                    else:
                        st.error(
                            f"L'activitat «{_fm_slot}» no existeix al catàleg."
                        )

        if not _fm_rows.empty:
            _rm_cols = st.columns([3, 1])
            with _rm_cols[0]:
                _rm_options = [
                    f"{r['Facultatiu']} → {r['Activitat']}"
                    for _, r in _fm_rows.iterrows()
                ]
                _rm_choice = st.selectbox(
                    "Treure assignació",
                    options=[""] + _rm_options,
                    index=0,
                    key="remove_fixed_machine_choice",
                    format_func=lambda v: v or "Treure assignació…",
                    label_visibility="collapsed",
                )
            with _rm_cols[1]:
                if st.button(
                    "Treure",
                    width="stretch",
                    key="remove_fixed_machine_btn",
                    disabled=not _rm_choice,
                ):
                    _slot_to_unfix = (
                        _rm_choice.split(" → ", 1)[1].strip().upper()
                    )
                    _mask = (
                        _fm_cat["slot_id"].fillna("").astype(str)
                        .str.strip().str.upper() == _slot_to_unfix
                    )
                    if _mask.any():
                        _fm_cat.loc[_mask, "assignee"] = ""
                        _save_cat_fm(slot_catalog_path, _fm_cat)
                        st.session_state["slot_catalog_draft"] = _fm_cat
                        st.session_state.pop("slot_catalog_current", None)
                        st.session_state["slot_catalog_editor_nonce"] = (
                            st.session_state.get("slot_catalog_editor_nonce", 0) + 1
                        )
                        st.toast(f"Tret: {_slot_to_unfix}", icon="✅")
                        st.rerun()
        warn_fixed_machines_vs_initial(slot_catalog_path)
