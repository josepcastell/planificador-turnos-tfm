"""Editors de dades mestres relacionats amb el catàleg d'activitats,
extrets d'app.py per no barrejar lògica de negoci a l'entry point:

  · render_machines_locations_editor — llistes base de Màquines i Llocs
    (pestanya Activitat), fonts dels desplegables del quick-add.
  · render_fixed_machines_editor — fixa un facultatiu a una activitat,
    opcionalment per dia de la setmana + franja (taula fixed_machines), a
    Restriccions › Altres restriccions.
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
        "crear cada activitat (p. ex. `RM` + `1` → `RM_1`)."
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


# Etiquetes en català per a la UI (les dades es guarden en codi anglès).
_WD_CAT = {
    "MONDAY": "Dilluns", "TUESDAY": "Dimarts", "WEDNESDAY": "Dimecres",
    "THURSDAY": "Dijous", "FRIDAY": "Divendres",
    "SATURDAY": "Dissabte", "SUNDAY": "Diumenge",
}
_FR_CAT = {"MATI": "Matí", "TARDA": "Tarda"}


def _wlbl(w) -> str:
    w = str(w or "").strip().upper()
    return _WD_CAT.get(w, w.title()) if w else ""


def _flbl(f) -> str:
    f = str(f or "").strip().upper()
    return _FR_CAT.get(f, f.title()) if f else ""


def _when_lbl(wd, fr) -> str:
    wd = str(wd or "").strip().upper()
    fr = str(fr or "").strip().upper()
    if wd in ("", "*") and fr in ("", "*"):
        return "Sempre (tots els dies)"
    return f"{_wlbl(wd) or 'Tots els dies'} · {_flbl(fr) or 'Totes les franges'}"


def render_fixed_machines_editor(slot_catalog_path: Path, all_professional_options) -> None:
    """Fixa un facultatiu a una activitat, opcionalment per a un dia de la
    setmana i franja concrets (taula `fixed_machines.csv`): el solver no
    l'haurà de decidir. Conserva també les fixacions globals antigues del
    catàleg (columna `assignee`). Inclou l'expander."""
    from src.services.slot_catalog import (
        load_slot_catalog as _load_cat_fm,
        save_slot_catalog as _save_cat_fm,
    )
    from src.services.fixed_machines import (
        load_fixed_machines,
        save_fixed_machines,
        slot_schedule_options,
    )
    from src.ui.restriction_warnings import warn_fixed_machines_vs_initial

    _base = Path(slot_catalog_path).parent
    _fm_path = _base / "weekday" / "fixed_machines.csv"
    _tpl_path = _base / "weekday" / "weekly_slot_templates.csv"

    with st.expander("Màquines fixes per facultatiu", expanded=False):
        st.caption(
            "Fixa una activitat a un facultatiu perquè el solver no l'hagi de "
            "decidir. Pots fixar-la **sempre** o només un **dia de la setmana i "
            "franja** concrets. Pots afegir-ne diverses per facultatiu."
        )

        # Plantilles → on (dia · franja) està programada cada activitat.
        try:
            _tpl = (
                pd.read_csv(_tpl_path)
                if _tpl_path.exists() and _tpl_path.stat().st_size > 0
                else pd.DataFrame()
            )
        except Exception:
            _tpl = pd.DataFrame()
        _sched = slot_schedule_options(_tpl)  # {slot_id: [(weekday_name, franja), ...]}

        # Taula granular + catàleg (per a les fixacions globals antigues).
        _fm = load_fixed_machines(_fm_path)
        _cat = (
            st.session_state.get("slot_catalog_current")
            if isinstance(st.session_state.get("slot_catalog_current"), pd.DataFrame)
            else st.session_state.get("slot_catalog_draft")
        )
        if not isinstance(_cat, pd.DataFrame) or _cat.empty:
            _cat = _load_cat_fm(slot_catalog_path)
        _cat = _cat.copy()
        if "assignee" not in _cat.columns:
            _cat["assignee"] = ""
        _cat["assignee"] = _cat["assignee"].fillna("").astype(str).str.strip().str.upper()

        # ── Llista unificada (granular + catàleg) ──
        _list_rows = []
        for r in _fm.itertuples(index=False):
            prof = str(getattr(r, "professional_id", "") or "").strip().upper()
            slot = str(getattr(r, "slot_id", "") or "").strip().upper()
            wd = str(getattr(r, "weekday_name", "") or "").strip().upper()
            fr = str(getattr(r, "franja", "") or "").strip().upper()
            if prof and slot:
                _list_rows.append({
                    "Facultatiu": prof, "Activitat": slot,
                    "Quan": _when_lbl(wd, fr),
                    "_src": "granular", "_wd": wd, "_fr": fr,
                })
        for _, cr in _cat.loc[_cat["assignee"] != "", ["assignee", "slot_id"]].iterrows():
            _list_rows.append({
                "Facultatiu": str(cr["assignee"]).strip().upper(),
                "Activitat": str(cr["slot_id"]).strip().upper(),
                "Quan": "Sempre (catàleg)", "_src": "catalog", "_wd": "", "_fr": "",
            })

        if not _list_rows:
            st.caption("_Cap màquina fixa assignada de moment._")
        else:
            _disp = (
                pd.DataFrame(_list_rows)[["Facultatiu", "Activitat", "Quan"]]
                .sort_values(["Facultatiu", "Activitat", "Quan"])
                .reset_index(drop=True)
            )
            st.dataframe(_disp, hide_index=True, width="stretch")

        # ── Afegir (reactiu: el desplegable dia·franja depèn de l'activitat) ──
        _profs = sorted(set(all_professional_options or []))
        _slots = sorted(_sched.keys())
        _c1, _c2, _c3, _c4 = st.columns([2, 2, 2, 1])
        with _c1:
            _fm_prof = st.selectbox(
                "Facultatiu", options=[""] + _profs, index=0,
                format_func=lambda v: v or "Facultatiu…", key="fm_add_prof",
            )
        with _c2:
            _fm_slot = st.selectbox(
                "Activitat", options=[""] + _slots, index=0,
                format_func=lambda v: v or "Activitat…", key="fm_add_slot",
            )
        _when_opts = _sched.get(_fm_slot, []) if _fm_slot else []
        _when_vals = ["__ALL__"] + [f"{wd}|{fr}" for (wd, fr) in _when_opts]

        def _when_fmt(v):
            if v == "__ALL__":
                return "Tots els dies / Totes les franges"
            _wd, _fr = v.split("|", 1)
            return f"{_wlbl(_wd)} · {_flbl(_fr)}"

        with _c3:
            _fm_when = st.selectbox(
                "Dia · Franja", options=_when_vals, index=0,
                format_func=_when_fmt,
                key=f"fm_add_when_{_fm_slot or 'none'}",
                disabled=not _fm_slot,
            )
        with _c4:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            _do_add = st.button("Fixar", width="stretch", key="fm_add_btn")

        if _do_add:
            if not _fm_prof or not _fm_slot:
                st.error("Cal triar facultatiu i activitat.")
            else:
                if _fm_when == "__ALL__":
                    _wd, _fr = "", ""
                else:
                    _wd, _fr = _fm_when.split("|", 1)
                _exists = bool((
                    (_fm["professional_id"].astype(str).str.strip().str.upper() == _fm_prof)
                    & (_fm["slot_id"].astype(str).str.strip().str.upper() == _fm_slot)
                    & (_fm["weekday_name"].astype(str).str.strip().str.upper() == _wd)
                    & (_fm["franja"].astype(str).str.strip().str.upper() == _fr)
                ).any()) if not _fm.empty else False
                if _exists:
                    st.warning("Aquesta fixació ja existeix.")
                else:
                    _new = pd.DataFrame([{
                        "professional_id": _fm_prof, "slot_id": _fm_slot,
                        "weekday_name": _wd, "franja": _fr,
                    }])
                    _fm = pd.concat([_fm, _new], ignore_index=True)
                    save_fixed_machines(_fm_path, _fm)
                    st.toast(
                        f"Fixat: {_fm_prof} → {_fm_slot} ({_when_lbl(_wd, _fr)})",
                        icon="✅",
                    )
                    st.rerun()

        # ── Treure ──
        if _list_rows:
            _rm_opts = [
                f"{r['Facultatiu']} → {r['Activitat']} · {r['Quan']}"
                for r in _list_rows
            ]
            _r1, _r2 = st.columns([3, 1])
            with _r1:
                _rm_choice = st.selectbox(
                    "Treure assignació", options=[""] + _rm_opts, index=0,
                    key="fm_remove_choice",
                    format_func=lambda v: v or "Treure assignació…",
                    label_visibility="collapsed",
                )
            with _r2:
                if st.button(
                    "Treure", width="stretch", key="fm_remove_btn",
                    disabled=not _rm_choice,
                ):
                    _row = _list_rows[_rm_opts.index(_rm_choice)]
                    if _row["_src"] == "granular":
                        _keep = ~(
                            (_fm["professional_id"].astype(str).str.strip().str.upper() == _row["Facultatiu"])
                            & (_fm["slot_id"].astype(str).str.strip().str.upper() == _row["Activitat"])
                            & (_fm["weekday_name"].astype(str).str.strip().str.upper() == _row["_wd"])
                            & (_fm["franja"].astype(str).str.strip().str.upper() == _row["_fr"])
                        )
                        save_fixed_machines(_fm_path, _fm[_keep])
                    else:  # catàleg (global antic)
                        _mask = (
                            _cat["slot_id"].fillna("").astype(str).str.strip().str.upper()
                            == _row["Activitat"]
                        )
                        _cat.loc[_mask, "assignee"] = ""
                        _save_cat_fm(slot_catalog_path, _cat)
                        st.session_state["slot_catalog_draft"] = _cat
                        st.session_state.pop("slot_catalog_current", None)
                        st.session_state["slot_catalog_editor_nonce"] = (
                            st.session_state.get("slot_catalog_editor_nonce", 0) + 1
                        )
                    st.toast("Tret.", icon="✅")
                    st.rerun()

        warn_fixed_machines_vs_initial(slot_catalog_path)
