"""UI editor del catàleg de slots disponibles."""

from pathlib import Path

import pandas as pd
import streamlit as st

from src.services.slot_catalog import (
    SLOT_CATALOG_COLUMNS,
    persist_slot_catalog_with_templates,
    seed_slot_catalog_if_missing,
)
from src.ui.editor_patterns import idx_of, init_sticky_draft, read_table_selection
from src.ui.table_state import (
    commit_new_row,
    data_editor_height,
)


_FAMILY_TOKENS = {"TC", "RM"}


def _infer_area_family(slot_id: str) -> tuple[str, str]:
    """Detecta la família (TC/RM) a partir del nom de l'slot. L'ÀREA NO
    s'infereix mai del nom: la defineix l'usuari al camp Àrea (lliure)."""
    family = ""
    for token in str(slot_id).strip().upper().split("_"):
        root = token.rstrip("0123456789")
        if not family and root in _FAMILY_TOKENS:
            family = root
    return "", family


def render_slot_catalog_editor(
    catalog_path: Path,
    weekday_templates_path: Path | None = None,
    weekend_templates_path: Path | None = None,
    professional_options: list[str] | None = None,
    machines: list[str] | None = None,
    locations: list[str] | None = None,
    year: int | None = None,
) -> None:
    catalog_df = seed_slot_catalog_if_missing(
        catalog_path,
        weekday_templates_path=weekday_templates_path,
        weekend_templates_path=weekend_templates_path,
    )

    st.caption(
        "Catàleg complet d'activitats. Afegeix-les amb el formulari de sota "
        "triant **Màquina + Lloc** dels desplegables (s'omplen amb les llistes "
        "de dalt), o escriu directament un nom personalitzat per a casos "
        "especials (revisions, etc.)."
    )

    # Draft persistent: només s'inicialitza des de disc el primer cop o
    # quan canvia el path (canvi de sessió).
    editor_df = init_sticky_draft(
        "slot_catalog_draft", catalog_df, SLOT_CATALOG_COLUMNS, catalog_path,
    )

    # Opcions per als desplegables.
    _machines = [str(m).strip().upper() for m in (machines or []) if str(m).strip()]
    _locations = [str(p).strip().upper() for p in (locations or []) if str(p).strip()]

    # Preprocessing del catàleg per al display.
    _cat_src = editor_df.copy()
    _cat_src["review"] = pd.to_numeric(
        _cat_src.get("review", 0), errors="coerce"
    ).fillna(0).astype(bool)
    _cat_src["area"] = (
        _cat_src.get("area", "").fillna("").astype(str).str.strip().str.upper()
    )
    _cat_src["metric_family"] = (
        _cat_src.get("metric_family", "").fillna("").astype(str).str.strip().str.upper()
    )
    _cat_src["linked_to"] = (
        _cat_src.get("linked_to", "").fillna("").astype(str).str.strip().str.upper()
    )
    _view_cols = ["slot_id", "metric_family", "area", "review"]
    _view_df = _cat_src[_view_cols].copy().reset_index(drop=True)

    # Selecció de la fila per pre-omplir el formulari.
    _table_key = "slot_catalog_view"
    _selected_idx = read_table_selection(_table_key, len(_view_df))

    _prefill_name = ""
    _prefill_family = ""
    _prefill_area = ""
    _prefill_review = False
    if _selected_idx is not None:
        _row = _view_df.iloc[_selected_idx]
        _prefill_name = str(_row.get("slot_id", "") or "")
        _prefill_family = str(_row.get("metric_family", "") or "").upper()
        _prefill_area = str(_row.get("area", "") or "").upper()
        _prefill_review = bool(_row.get("review", False))

    _family_options = [""] + _machines
    _area_options = [""] + _locations
    # Canviem el "nonce" del formulari quan canvia la selecció: així els
    # widgets es reinicialitzen amb els nous valors per defecte (prefill).
    _form_nonce = _selected_idx if _selected_idx is not None else -1

    with st.form("quick_add_slot", clear_on_submit=False):
        st.caption(
            "**Afegir o editar activitat**: omple les opcions i prem "
            "**Aplicar**. Si seleccionés una fila a la taula de sota, els camps "
            "s'omplen prèviament amb els seus valors per editar-la. Si escrius un nom "
            "nou s'afegeix una activitat nova. La vinculació entre màquines "
            "es configura a Estructura › Franges (per dia i franja)."
        )
        cols_form = st.columns([1.8, 1.0, 1.0, 1.2, 0.9])
        with cols_form[0]:
            qa_slot = st.text_input(
                "Nom",
                value=_prefill_name,
                placeholder="ex. REV_TC (opcional)",
                key=f"qa_slot_{_form_nonce}",
            )
        with cols_form[1]:
            qa_family = st.selectbox(
                "Màquina",
                options=_family_options,
                index=idx_of(_prefill_family, _family_options),
                format_func=lambda v: v or "—",
                key=f"qa_family_{_form_nonce}",
            )
        with cols_form[2]:
            qa_area = st.selectbox(
                "Lloc",
                options=_area_options,
                index=idx_of(_prefill_area, _area_options),
                format_func=lambda v: v or "—",
                key=f"qa_area_{_form_nonce}",
            )
        with cols_form[3]:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            qa_review = st.checkbox(
                "Revisió",
                value=_prefill_review,
                help="Slot de revisió: dia sencer, no compta a la quota "
                     "setmanal. El solver els reparteix equitativament entre "
                     "els facultatius elegibles cada mes (la 'roda').",
                key=f"qa_review_{_form_nonce}",
            )
        with cols_form[4]:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            submitted = st.form_submit_button("Aplicar", width="stretch")
        if submitted:
            _qa_family_clean = (qa_family or "").strip().upper()
            _qa_area_clean = (qa_area or "").strip().upper()
            _qa_name_clean = (qa_slot or "").strip().upper()
            # Si no hi ha nom manual, es genera des de Màquina + Lloc.
            if not _qa_name_clean and _qa_family_clean and _qa_area_clean:
                new_name = f"{_qa_family_clean}_{_qa_area_clean}"
            else:
                new_name = _qa_name_clean
            if not new_name:
                st.error(
                    "Cal indicar un nom o triar Màquina + Lloc per generar-lo."
                )
            else:
                # Sincronitzem el draft amb l'estat actual abans d'aplicar.
                _current = st.session_state.get("slot_catalog_current")
                if isinstance(_current, pd.DataFrame) and not _current.empty:
                    st.session_state["slot_catalog_draft"] = _current[SLOT_CATALOG_COLUMNS].copy()
                existing = st.session_state.get("slot_catalog_draft", editor_df).copy()
                existing_slots_upper = (
                    existing["slot_id"].fillna("").astype(str).str.strip().str.upper()
                )
                _area_guess, _family_guess = _infer_area_family(new_name)
                _area_final = _qa_area_clean or _area_guess
                _family_final = _qa_family_clean or _family_guess
                # `linked_to` ja no s'edita des d'aquí: la vinculació
                # s'introdueix per (dia, franja) a Estructura › Franges.
                # Per a UPDATE preservarem el valor existent (a sota).
                _linked_final = ""

                # Determinar mode: si hi ha fila seleccionada → UPDATE; sino → ADD.
                _selected_slot = None
                if _selected_idx is not None and _selected_idx < len(_view_df):
                    _selected_slot = str(
                        _view_df.iloc[_selected_idx]["slot_id"]
                    ).strip().upper()

                if _selected_slot and (existing_slots_upper == _selected_slot).any():
                    # UPDATE de la fila seleccionada. Si el nom canvia i xoca
                    # amb un altre slot existent, autosufixar.
                    if new_name != _selected_slot:
                        _other_slots = set(
                            existing_slots_upper[
                                existing_slots_upper != _selected_slot
                            ]
                        )
                        if new_name in _other_slots:
                            _n = 2
                            while (
                                f"{new_name}_{_n}" in _other_slots
                                or f"{new_name}_{_n}" == _selected_slot
                            ):
                                _n += 1
                            new_name = f"{new_name}_{_n}"
                    _mask = existing_slots_upper == _selected_slot
                    existing.loc[_mask, "slot_id"] = new_name
                    existing.loc[_mask, "area"] = _area_final
                    existing.loc[_mask, "metric_family"] = _family_final
                    # NO toquem linked_to: ara és per (dia, franja) als
                    # templates. El valor existent al catàleg queda
                    # com a legacy (no s'usa pel solver nou).
                    existing.loc[_mask, "review"] = int(bool(qa_review))
                    # CASCADE RENAME: si l'slot canvia de nom, propaguem
                    # la nova etiqueta a tots els llocs que el referencien
                    # perque la resta de caracteristiques (vinculacions,
                    # elegibilitats, targets, preassignacions, franges)
                    # es mantinguin sense reconfigurar.
                    if new_name != _selected_slot:
                        from src.services.slot_rename import (
                            cascade_rename_linked_to,
                            cascade_rename_slot_id,
                            cascade_rename_slot_id_in_file,
                        )
                        # 1) linked_to en altres files del cataleg (memoria).
                        existing = cascade_rename_linked_to(
                            existing, _selected_slot, new_name,
                        )
                        # 2) templates setmanals (a disc).
                        if (
                            weekday_templates_path is not None
                            and weekday_templates_path.exists()
                        ):
                            cascade_rename_slot_id_in_file(
                                weekday_templates_path,
                                _selected_slot, new_name,
                            )
                        # 3) eligibility, preassignments,
                        #    template_overrides (any del scope).
                        if year is not None:
                            cascade_rename_slot_id(
                                _selected_slot, new_name, year,
                            )
                    st.session_state["slot_catalog_draft"] = existing
                    st.session_state.pop("slot_catalog_current", None)
                    st.session_state.pop(_table_key, None)
                    persist_slot_catalog_with_templates(
                        existing, catalog_path,
                        weekday_templates_path, weekend_templates_path,
                    )
                    if new_name != _selected_slot:
                        st.toast(
                            f"«{_selected_slot}» → «{new_name}»", icon="✅",
                        )
                    else:
                        st.toast(f"«{new_name}» actualitzada", icon="✅")
                    st.rerun()
                else:
                    # ADD: si col·lisiona el nom, autosufixar.
                    existing_set = set(existing_slots_upper)
                    if new_name in existing_set:
                        _n = 2
                        while f"{new_name}_{_n}" in existing_set:
                            _n += 1
                        new_name = f"{new_name}_{_n}"

                    def _save_catalog_and_seed_template(df):
                        # Només persisteix el catàleg; NO sembra files de
                        # franges automàticament — l'usuari les afegirà
                        # explícitament des de Restriccions › Franges de treball.
                        persist_slot_catalog_with_templates(
                            df, catalog_path,
                            weekday_templates_path, weekend_templates_path,
                        )

                    st.session_state.pop(_table_key, None)
                    commit_new_row(
                        "slot_catalog_draft",
                        {
                            "slot_id": new_name,
                            "weekday": True,
                            "weekend": False,
                            "linked_to": _linked_final,
                            "doubled": 0,
                            "review": int(bool(qa_review)),
                            "area": _area_final,
                            "metric_family": _family_final,
                            "notes": "",
                        },
                        SLOT_CATALOG_COLUMNS,
                        _save_catalog_and_seed_template,
                        fallback_df=editor_df,
                    )

    # Taula amb selecció: clica una fila per editar-la al formulari de sobre.
    st.dataframe(
        _view_df,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        height=data_editor_height(len(_view_df)),
        key=_table_key,
        column_config={
            "slot_id": st.column_config.TextColumn(
                "Activitat",
                help="Identificador en majúscules (ex. `RM_1`).",
            ),
            "metric_family": st.column_config.TextColumn(
                "Màquina",
                help="Família (TC/RM o lliure). El solver usa TC/RM per a "
                "l'equilibri; altres etiquetes són només descriptives.",
            ),
            "area": st.column_config.TextColumn(
                "Lloc",
                help="Localització (etiqueta lliure, ex. ZONA_A). S'usa per "
                "agrupar i acolorir el calendari, els PDF i els comitès.",
            ),
            "review": st.column_config.CheckboxColumn(
                "Revisió",
                help="Slot de revisió: dia sencer, no compta per a la quota "
                "setmanal i màx. 1 per facultatiu i dia.",
            ),
        },
    )

    # Botó d'eliminar la fila seleccionada (si hi ha selecció).
    if _selected_idx is not None:
        _slot_to_delete = str(_view_df.iloc[_selected_idx]["slot_id"]).strip().upper()
        if st.button(
            f"🗑️ Eliminar «{_slot_to_delete}»",
            key="delete_selected_slot",
        ):
            existing = st.session_state["slot_catalog_draft"].copy()
            kept = existing[
                existing["slot_id"].fillna("").astype(str).str.strip().str.upper()
                != _slot_to_delete
            ].copy().reset_index(drop=True)
            st.session_state["slot_catalog_draft"] = kept
            st.session_state.pop("slot_catalog_current", None)
            st.session_state.pop(_table_key, None)
            persist_slot_catalog_with_templates(
                kept, catalog_path,
                weekday_templates_path, weekend_templates_path,
            )
            st.toast(f"«{_slot_to_delete}» eliminada", icon="🗑️")
            st.rerun()

    # Slot_catalog_current = draft (no s'edita via taula → són iguals).
    st.session_state["slot_catalog_current"] = (
        st.session_state["slot_catalog_draft"][SLOT_CATALOG_COLUMNS].copy()
    )

