from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import WEEKDAY_CODES
from src.services.comite import COMITE_COLUMNS, load_comite_assignments, save_comite_assignments
from src.services.input_tables import (
    normalize_doubled_machines,
    professional_scope_df,
    save_absences,
    save_guards,
    save_professional_scope,
    save_professionals,
)
from src.services.table_io import read_table
from src.ui.editor_patterns import idx_of, init_sticky_draft, read_table_selection
from src.ui.table_state import (
    autosave_draft_if_changed,
    commit_new_row,
    data_editor_height,
    source_table_signature,
    table_draft,
)


_PRESENCE_LABELS = {
    "": "Totes",
    "PRESENCIAL": "Només presencial",
    "NO_PRESENCIAL": "Només no presencial",
}
_PRESENCE_CODES = {v: k for k, v in _PRESENCE_LABELS.items()}
_PROFESSIONAL_SCOPE_COLS = [
    "professional_id", "name", "dies_laborables",
    "fallback", "presence_mode", "doubled_machines",
    "non_working_weekdays", "no_pres_weekdays", "pres_weekdays",
]


def render_professionals_editor(
    professionals_df: pd.DataFrame,
    professionals_path: Path,
    eligibility_path: Path,
    catalog_weekday_slots: list[str] | None = None,
) -> None:
    scoped_professionals_df = professional_scope_df(professionals_df)

    # Draft persistent: només s'inicialitza des de disc el primer cop o
    # quan canvia el path (canvi de sessió).
    draft = init_sticky_draft(
        "base_professionals_draft",
        scoped_professionals_df,
        _PROFESSIONAL_SCOPE_COLS,
        professionals_path,
    )

    # Vista per la taula: només columnes editables, amb etiquetes humanes.
    # NOTA: la columna "fallback" (comodí) s'edita ara a Restriccions ›
    # Comodí. Aquí només es mostra el llistat base de facultatius.
    _view = draft[["professional_id", "name", "presence_mode"]].copy()
    _view["presence_mode"] = (
        _view["presence_mode"].fillna("").astype(str).str.strip().str.upper()
        .map(lambda v: _PRESENCE_LABELS.get(v, "Totes"))
    )
    _view = _view.reset_index(drop=True)

    # Selecció de la fila per pre-omplir el form.
    _table_key = "base_professionals_view"
    _selected_idx = read_table_selection(_table_key, len(_view))

    _prefill_pid = ""
    _prefill_name = ""
    _prefill_presence = "Totes"
    if _selected_idx is not None:
        _row = _view.iloc[_selected_idx]
        _prefill_pid = str(_row.get("professional_id", "") or "")
        _prefill_name = str(_row.get("name", "") or "")
        _prefill_presence = str(_row.get("presence_mode", "") or "Totes")

    _form_nonce = _selected_idx if _selected_idx is not None else -1
    _presence_options = list(_PRESENCE_LABELS.values())

    st.caption(
        "Afegeix o edita facultatius. Si selecciones una fila a la taula, els "
        "camps s'omplen prèviament amb els seus valors per editar-la. Si l'identificador "
        "(Facultatiu) és nou, s'afegeix una nova entrada."
    )

    with st.form("quick_add_professional", clear_on_submit=False):
        cols_form = st.columns([1.2, 2.5, 1.6, 1.0])
        with cols_form[0]:
            qa_pid = st.text_input(
                "Identificador",
                value=_prefill_pid,
                placeholder="ex. XX",
                key=f"qa_pro_pid_{_form_nonce}",
            )
        with cols_form[1]:
            qa_name = st.text_input(
                "Nom complet",
                value=_prefill_name,
                placeholder="ex. John Doe",
                key=f"qa_pro_name_{_form_nonce}",
            )
        with cols_form[2]:
            qa_presence = st.selectbox(
                "Activitat",
                options=_presence_options,
                index=idx_of(_prefill_presence, _presence_options),
                key=f"qa_pro_presence_{_form_nonce}",
            )
        with cols_form[3]:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            submitted = st.form_submit_button("Aplicar", width="stretch")
        if submitted:
            pid_clean = (qa_pid or "").strip().upper()
            if not pid_clean:
                st.error("El camp Facultatiu no pot estar buit.")
            else:
                existing = st.session_state["base_professionals_draft"].copy()
                pids_upper = (
                    existing["professional_id"].fillna("").astype(str)
                    .str.strip().str.upper()
                )
                presence_code = _PRESENCE_CODES.get(qa_presence, "")
                _selected_pid = None
                if _selected_idx is not None and _selected_idx < len(_view):
                    _selected_pid = str(
                        _view.iloc[_selected_idx]["professional_id"]
                    ).strip().upper()

                if _selected_pid and (pids_upper == _selected_pid).any():
                    # UPDATE de la fila seleccionada.
                    if pid_clean != _selected_pid:
                        _other = set(pids_upper[pids_upper != _selected_pid])
                        if pid_clean in _other:
                            st.error(
                                f"L'identificador «{pid_clean}» ja existeix; "
                                "tria'n un altre."
                            )
                            st.stop()
                    _mask = pids_upper == _selected_pid
                    existing.loc[_mask, "professional_id"] = pid_clean
                    existing.loc[_mask, "name"] = (qa_name or "").strip()
                    # fallback no es toca aquí (s'edita a Restriccions › Comodí).
                    existing.loc[_mask, "presence_mode"] = presence_code
                    existing.loc[_mask, "dies_laborables"] = True
                    st.session_state["base_professionals_draft"] = existing
                    st.session_state.pop(_table_key, None)
                    save_professional_scope(
                        existing, professionals_path, eligibility_path,
                    )
                    if pid_clean != _selected_pid:
                        st.toast(
                            f"«{_selected_pid}» → «{pid_clean}»", icon="✅",
                        )
                    else:
                        st.toast(f"«{pid_clean}» actualitzat", icon="✅")
                    st.rerun()
                else:
                    # ADD nou facultatiu. Si l'identificador ja existeix
                    # (dos facultatius amb les mateixes inicials), generem
                    # un sufix _2, _3, ... per fer l'ID intern únic
                    # (necessari perquè tot el sistema —schedule,
                    # eligibility, absències…— referencia el facultatiu per
                    # ID). El nom visible queda igual.
                    final_pid = pid_clean
                    if pid_clean in set(pids_upper):
                        k = 2
                        while f"{pid_clean}_{k}" in set(pids_upper):
                            k += 1
                        final_pid = f"{pid_clean}_{k}"
                        st.toast(
                            f"«{pid_clean}» ja existia → afegit com «{final_pid}»",
                            icon="ℹ️",
                        )
                    new_row = {
                        "professional_id": final_pid,
                        "name": (qa_name or "").strip(),
                        "dies_laborables": True,
                        # fallback (comodí) per defecte 0; es marca a
                        # Restriccions › Comodí.
                        "fallback": 0,
                        "presence_mode": presence_code,
                        "doubled_machines": "",
                        "non_working_weekdays": "",
                        "no_pres_weekdays": "",
                        "pres_weekdays": "",
                    }
                    combined = pd.concat(
                        [existing, pd.DataFrame([new_row])], ignore_index=True,
                    )[_PROFESSIONAL_SCOPE_COLS].copy()
                    st.session_state["base_professionals_draft"] = combined
                    st.session_state.pop(_table_key, None)
                    save_professional_scope(
                        combined, professionals_path, eligibility_path,
                    )
                    st.toast(f"«{final_pid}» afegit", icon="✅")
                    st.rerun()

    # Taula amb selecció (read-only).
    st.dataframe(
        _view,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        width="stretch",
        height=data_editor_height(len(_view)),
        key=_table_key,
        column_config={
            "professional_id": st.column_config.TextColumn("Facultatiu"),
            "name": st.column_config.TextColumn("Nom"),
            "presence_mode": st.column_config.TextColumn(
                "Activitat",
                help="Restringeix el tipus d'activitat.",
            ),
        },
    )

    # Eliminar fila seleccionada.
    if _selected_idx is not None:
        _pid_to_delete = str(
            _view.iloc[_selected_idx]["professional_id"]
        ).strip().upper()
        if st.button(
            f"🗑️ Eliminar «{_pid_to_delete}»",
            key="delete_selected_professional",
        ):
            kept = draft[
                draft["professional_id"].fillna("").astype(str)
                .str.strip().str.upper() != _pid_to_delete
            ].copy().reset_index(drop=True)
            st.session_state["base_professionals_draft"] = kept
            st.session_state.pop(_table_key, None)
            save_professional_scope(kept, professionals_path, eligibility_path)
            st.toast(f"«{_pid_to_delete}» eliminat", icon="🗑️")
            st.rerun()

    _valid_pids = draft["professional_id"].fillna("").astype(str).str.strip()
    _valid_mask = (_valid_pids != "") & (_valid_pids.str.upper() != "NONE")
    _total = int(_valid_mask.sum())
    st.caption(f"**Total facultatius introduïts: {_total}**")


def render_allowed_areas_editor(
    professionals_path: Path,
    eligibility_path: Path,
) -> None:
    """Editor per facultatiu: llocs (àrees) on pot anar a treballar.
    Si la llista és buida, el facultatiu pot anar a qualsevol lloc.
    Si conté valors (p.ex. ZONA_A;ZONA_B), el solver bloqueja qualsevol
    slot ubicat a una àrea fora d'aquesta llista (via eligibility)."""
    # Llegim totes les columnes per no perdre dades en desar.
    pros_df = read_table(
        professionals_path,
        ["professional_id", "name", "doubled_machines", "non_working_weekdays",
         "no_pres_weekdays", "pres_weekdays", "fallback", "presence_mode",
         "allowed_areas"],
    )
    pros_df["professional_id"] = pros_df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    pros_df["allowed_areas"] = pros_df["allowed_areas"].fillna("").astype(str).str.strip()
    pros_df = pros_df[(pros_df["professional_id"] != "") & (pros_df["professional_id"] != "NONE")].copy()
    if pros_df.empty:
        st.info("Primer introdueix facultatius a la pestanya Facultatius.")
        return

    # Llista d'àrees disponibles: les úniques del catàleg de slots o de
    # data/llocs.csv.
    areas: set[str] = set()
    cat_path = Path("data/slot_catalog.csv")
    if cat_path.exists():
        try:
            cat = pd.read_csv(cat_path)
            if "area" in cat.columns:
                areas.update(
                    cat["area"].fillna("").astype(str).str.strip().str.upper().tolist()
                )
        except Exception:
            pass
    llocs_path = Path("data/llocs.csv")
    if llocs_path.exists():
        try:
            llocs = pd.read_csv(llocs_path)
            if "nom" in llocs.columns:
                areas.update(
                    llocs["nom"].fillna("").astype(str).str.strip().str.upper().tolist()
                )
        except Exception:
            pass
    areas.discard("")
    area_options = sorted(areas)

    st.caption(
        "Llocs on cada facultatiu pot anar a treballar. **Buit = pot anar "
        "a qualsevol lloc.** Si tries algunes àrees, el solver no li "
        "assignarà slots d'altres àrees."
    )
    header_label, header_pick = st.columns([1, 4])
    with header_label:
        st.markdown("**Facultatiu**")
    with header_pick:
        st.markdown("**Llocs permesos**")

    existing = dict(zip(pros_df["professional_id"], pros_df["allowed_areas"]))
    new_values: dict[str, str] = {}
    for _, row in pros_df.iterrows():
        pid = str(row["professional_id"]).strip().upper()
        current = [
            a.strip().upper()
            for a in str(existing.get(pid, "") or "").split(";")
            if a.strip()
        ]
        options = sorted(set(area_options) | set(current))
        valid_default = [a for a in current if a in options]
        col_label, col_pick = st.columns([1, 4])
        with col_label:
            display_name = str(row.get("name", "") or "").strip()
            label = f"**{pid}**" if not display_name else f"**{pid}** · {display_name}"
            st.markdown(label)
        with col_pick:
            selected = st.multiselect(
                "allowed_areas",
                options=options,
                default=valid_default,
                key=f"allowed_areas_picker_{pid}",
                label_visibility="collapsed",
                placeholder="Tots els llocs (cap restricció)",
            )
        new_values[pid] = ";".join(sorted({a.strip().upper() for a in selected if a and a.strip()}))

    if any(new_values.get(pid, "") != existing.get(pid, "") for pid in new_values):
        pros_df["allowed_areas"] = pros_df["professional_id"].map(new_values).fillna(pros_df["allowed_areas"])
        save_professionals(pros_df, professionals_path, eligibility_path)


def render_doubled_machines_section(
    professionals_path: Path,
    eligibility_path: Path,
    catalog_weekday_slots: list[str] | None = None,
) -> None:
    """Per facultatiu d'entre setmana, escull quins slots dobla.
    Llegeix i escriu professionals.csv (només la columna doubled_machines).

    Llegim TOTES les columnes de professionals.csv per evitar perdre
    les que no fa servir l'editor (no_pres_weekdays, pres_weekdays,
    fallback, presence_mode, …) en el moment de desar."""
    pros_df = read_table(
        professionals_path,
        ["professional_id", "name", "doubled_machines", "non_working_weekdays",
         "no_pres_weekdays", "pres_weekdays", "fallback", "presence_mode"],
    )
    pros_df["professional_id"] = pros_df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    pros_df["doubled_machines"] = pros_df["doubled_machines"].fillna("").astype(str).str.strip()
    pros_df = pros_df[(pros_df["professional_id"] != "") & (pros_df["professional_id"] != "NONE")].copy()
    if pros_df.empty:
        return

    catalog_options = sorted(catalog_weekday_slots or [])
    existing_doubled = dict(
        zip(pros_df["professional_id"], pros_df["doubled_machines"])
    )
    new_doubled: dict[str, str] = {}
    for _, row in pros_df.iterrows():
        pid = row["professional_id"]
        normalised = normalize_doubled_machines(existing_doubled[pid])
        current = normalised.split(";") if normalised else []
        options = sorted(set(catalog_options) | set(current))
        valid_default = [m for m in current if m in options]
        col_label, col_picker = st.columns([1, 4])
        with col_label:
            display_name = str(row.get("name", "") or "").strip()
            label = f"**{pid}**" if not display_name else f"**{pid}** · {display_name}"
            st.markdown(label)
        with col_picker:
            selected = st.multiselect(
                "doubled_machines",
                options=options,
                default=valid_default,
                key=f"slot_doubled_picker_{pid}",
                label_visibility="collapsed",
                placeholder="Cap màquina doblada",
            )
        new_doubled[pid] = ";".join(sorted({m.strip().upper() for m in selected if m and m.strip()}))

    if any(new_doubled.get(pid, "") != existing_doubled.get(pid, "") for pid in new_doubled):
        pros_df["doubled_machines"] = pros_df["professional_id"].map(new_doubled).fillna(pros_df["doubled_machines"])
        save_professionals(pros_df, professionals_path, eligibility_path)


def render_comite_editor(
    professional_options: list[str],
    all_professional_options: list[str] | None = None,
    catalog_weekday_slots: list[str] | None = None,
) -> None:
    """Editor de Comitès — taula global a la pestanya pròpia de Calendari base."""
    st.caption("Afegeix els comités.")

    comite_path = Path("data/comite/assignments.csv")
    valid_professionals = set(all_professional_options or professional_options)
    comite_df = load_comite_assignments(comite_path)
    comite_df["specific_day"] = pd.to_datetime(comite_df["specific_day"], errors="coerce")

    draft_df = table_draft(
        "comite_draft",
        comite_df,
        COMITE_COLUMNS,
        source_table_signature(comite_path, comite_df),
    )

    with st.form("quick_add_comite", clear_on_submit=True):
        st.caption("Afegir ràpidament: omple i prem **Enter** per afegir.")
        cols_form = st.columns([2, 3, 1, 2, 2, 1])
        with cols_form[0]:
            qa_pid = st.selectbox(
                "facultatiu", options=professional_options or [""],
                index=0, label_visibility="collapsed",
            )
        with cols_form[1]:
            qa_name = st.text_input("nom comitè", placeholder="ex. CIM",
                                    label_visibility="collapsed")
        with cols_form[2]:
            qa_type = st.text_input(
                "àrea", placeholder="àrea (com al catàleg)",
                label_visibility="collapsed",
            )
        with cols_form[3]:
            qa_specific = st.date_input(
                "dia concret", value=None, format="DD/MM/YYYY",
                label_visibility="collapsed",
            )
        with cols_form[4]:
            qa_weekday = st.selectbox(
                "dia setmana", options=[""] + WEEKDAY_CODES, index=0,
                label_visibility="collapsed",
            )
        with cols_form[5]:
            submitted = st.form_submit_button("Afegir", width="stretch")
        if submitted:
            pid_clean = (qa_pid or "").strip().upper()
            if not pid_clean:
                st.error("Cal un facultatiu.")
            elif not qa_specific and not qa_weekday:
                st.error("Cal un dia concret o un dia de la setmana.")
            else:
                commit_new_row(
                    "comite_draft",
                    {
                        "professional_id": pid_clean,
                        "comite_name": (qa_name or "").strip(),
                        "comite_type": (qa_type or "").strip().upper(),
                        "specific_day": pd.to_datetime(qa_specific) if qa_specific else pd.NaT,
                        "weekday": qa_weekday if not qa_specific else "",
                        "notes": "",
                    },
                    COMITE_COLUMNS,
                    lambda df: save_comite_assignments(comite_path, df, valid_professionals),
                    fallback_df=draft_df,
                )

    editor_nonce = st.session_state.get("comite_editor_nonce", 0)
    _comite_src = st.session_state["comite_draft"].copy()
    _comite_src["_eliminar"] = False
    edited = st.data_editor(
        _comite_src,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=data_editor_height(len(st.session_state["comite_draft"])),
        key=f"comite_editor_{editor_nonce}",
        column_order=[c for c in COMITE_COLUMNS if c != "notes"] + ["_eliminar"],
        column_config={
            "professional_id": st.column_config.SelectboxColumn(
                "Facultatiu", options=professional_options, required=True,
            ),
            "comite_name": st.column_config.TextColumn(
                "Nom del comitè", help="Etiqueta lliure (ex: CIM, Mama). Només informativa.",
            ),
            "comite_type": st.column_config.TextColumn(
                "Àrea", required=True,
                help="Àrea (la que has posat al catàleg) del grup de màquines "
                     "a forçar aquell dia.",
            ),
            "specific_day": st.column_config.DateColumn(
                "Dia concret", format="DD/MM/YYYY",
                help="Dia exacte (puntual). Deixa buit per usar 'dia de la setmana'.",
            ),
            "weekday": st.column_config.SelectboxColumn(
                "Dia de la setmana", options=[""] + WEEKDAY_CODES,
                help="Si està marcat, s'aplica cada setmana en aquest dia. S'ignora si hi ha 'dia concret'.",
            ),
            "_eliminar": st.column_config.CheckboxColumn(
                "Eliminar",
                help="Marca les files que vulguis eliminar i prem el botó de sota.",
            ),
        },
    )

    _mark = (
        edited["_eliminar"].fillna(False).astype(bool)
        if "_eliminar" in edited.columns
        else pd.Series(False, index=edited.index)
    )
    _n_marked = int(_mark.sum())
    if st.button(
        f"🗑️ Eliminar {_n_marked} comitè(s) marcat(s)"
        if _n_marked
        else "🗑️ Eliminar comitè(s) marcats",
        disabled=_n_marked == 0,
        key="comite_delete_marked",
    ):
        kept = edited.loc[~_mark, COMITE_COLUMNS].copy().reset_index(drop=True)
        st.session_state["comite_draft"] = kept
        st.session_state["comite_editor_nonce"] = editor_nonce + 1
        save_comite_assignments(comite_path, kept, valid_professionals)
        st.rerun()

    st.session_state["comite_draft"] = edited[COMITE_COLUMNS].copy()
    autosave_draft_if_changed(
        "comite",
        st.session_state["comite_draft"],
        COMITE_COLUMNS,
        lambda df: save_comite_assignments(comite_path, df, valid_professionals),
    )


def render_absences_editor(
    absences_path: Path,
    all_professional_options: list[str],
    professionals_path: Path | None = None,
    eligibility_path: Path | None = None,
    weekday_unavailability_path: Path | None = None,
) -> None:
    """Indisponibilitats — 3 seccions:
      • Per període (absences amb start_day/end_day i tipus)
      • Per dies de la setmana per facultatiu (non_working_weekdays)
      • Per dies concrets (entrades puntuals a unavailability)
    """
    # ── Secció 1: Per període ─────────────────────────────────────────────────
    with st.expander("Per període", expanded=False):
        # Nota: el camp "Tipus d'absència" (motiu) s'ha tret a petició
        # de l'usuari. Totes les absències des d'aquesta secció es desen
        # amb el tipus per defecte `_DEFAULT_ABSENCE_TYPE` (no influeix
        # al solver: nomes s'usa com a etiqueta downstream).
        _DEFAULT_ABSENCE_TYPE = "altres_absencies"
        absences_df = read_table(absences_path, ["absence_type", "professional_id", "start_day", "end_day", "notes"])
        absences_df["start_day"] = pd.to_datetime(absences_df["start_day"], errors="coerce")
        absences_df["end_day"] = pd.to_datetime(absences_df["end_day"], errors="coerce")
        absences_editor_df = table_draft(
            "absences_draft",
            absences_df,
            ["absence_type", "professional_id", "start_day", "end_day", "notes"],
            source_table_signature(absences_path, absences_df),
        )
        valid_professionals = set(all_professional_options)
        with st.form("quick_add_absence", clear_on_submit=True):
            st.caption("Afegir ràpidament: omple i prem **Enter** per afegir.")
            cols_form = st.columns([2, 2, 2, 1])
            with cols_form[0]:
                qa_pid = st.selectbox("pid", options=all_professional_options or [""],
                                      index=0, label_visibility="collapsed")
            with cols_form[1]:
                qa_start = st.date_input("start", value=None, format="DD/MM/YYYY",
                                         label_visibility="collapsed")
            with cols_form[2]:
                qa_end = st.date_input("end", value=None, format="DD/MM/YYYY",
                                       label_visibility="collapsed")
            with cols_form[3]:
                submitted = st.form_submit_button("Afegir", width="stretch")
            if submitted:
                pid_clean = (qa_pid or "").strip().upper()
                if not pid_clean:
                    st.error("Cal un facultatiu.")
                elif not qa_start or not qa_end:
                    st.error("Cal data inicial i final.")
                elif qa_end < qa_start:
                    st.error("La data final ha de ser igual o posterior a la inicial.")
                else:
                    commit_new_row(
                        "absences_draft",
                        {
                            "absence_type": _DEFAULT_ABSENCE_TYPE,
                            "professional_id": pid_clean,
                            "start_day": pd.to_datetime(qa_start),
                            "end_day": pd.to_datetime(qa_end),
                            "notes": "",
                        },
                        ["absence_type", "professional_id", "start_day", "end_day", "notes"],
                        lambda df: save_absences(df, absences_path, valid_professionals),
                        fallback_df=absences_editor_df,
                    )

        editor_nonce = st.session_state.get("absences_editor_nonce", 0)
        _abs_src = st.session_state["absences_draft"].copy()
        # Si hi ha files legacy amb absence_type buit, posem el default
        # perquè save_absences (que filtra files amb absence_type=="") no
        # les descarti.
        _abs_src["absence_type"] = (
            _abs_src["absence_type"].fillna("").astype(str).str.strip()
            .replace("", _DEFAULT_ABSENCE_TYPE)
        )
        _n_abs_rows = len(_abs_src)
        _abs_src["_eliminar"] = False
        edited_absences = st.data_editor(
            _abs_src,
            num_rows="fixed",
            hide_index=True,
            width="stretch",
            height=data_editor_height(_n_abs_rows),
            key=f"absences_editor_main_{editor_nonce}",
            column_order=["professional_id", "start_day", "end_day", "_eliminar"],
            column_config={
                "professional_id": st.column_config.SelectboxColumn("Facultatiu", options=all_professional_options),
                "start_day": st.column_config.DateColumn("Inici", format="DD/MM/YYYY"),
                "end_day": st.column_config.DateColumn("Fi", format="DD/MM/YYYY"),
                "_eliminar": st.column_config.CheckboxColumn(
                    "Eliminar",
                    help="Marca les files que vulguis eliminar i prem el botó de sota.",
                ),
            },
        )

        _mark = (
            edited_absences["_eliminar"].fillna(False).astype(bool)
            if "_eliminar" in edited_absences.columns
            else pd.Series(False, index=edited_absences.index)
        )
        _n_marked = int(_mark.sum())
        if st.button(
            f"🗑️ Eliminar {_n_marked} absència/permís marcat(s)"
            if _n_marked
            else "🗑️ Eliminar absència/permís marcats",
            disabled=_n_marked == 0,
            key="absences_delete_marked",
        ):
            kept = edited_absences.loc[
                ~_mark,
                ["absence_type", "professional_id", "start_day", "end_day", "notes"],
            ].copy().reset_index(drop=True)
            st.session_state["absences_draft"] = kept
            st.session_state["absences_editor_nonce"] = editor_nonce + 1
            save_absences(kept, absences_path, valid_professionals)
            st.rerun()

        st.session_state["absences_draft"] = edited_absences[
            ["absence_type", "professional_id", "start_day", "end_day", "notes"]
        ].copy()
        autosave_draft_if_changed(
            "absences",
            st.session_state["absences_draft"],
            ["absence_type", "professional_id", "start_day", "end_day", "notes"],
            lambda df: save_absences(df, absences_path, valid_professionals),
        )

    # ── Secció 2: Per dies de la setmana per facultatiu ───────────────────────
    if professionals_path and eligibility_path:
        with st.expander("Per dies de la setmana", expanded=False):
            _render_non_working_weekdays_block(
                professionals_path, eligibility_path,
            )

    # ── Secció 3: Per dies concrets ───────────────────────────────────────────
    if weekday_unavailability_path:
        with st.expander("Per dies concrets", expanded=False):
            _render_specific_days_unavailability_block(
                weekday_unavailability_path, all_professional_options,
            )


def _render_non_working_weekdays_block(
    professionals_path: Path,
    eligibility_path: Path,
) -> None:
    """Multiselect MON..SUN per pro. Edita la columna non_working_weekdays de
    professionals.csv via save_professional_scope."""
    _render_weekday_picker_block(
        professionals_path=professionals_path,
        eligibility_path=eligibility_path,
        column="non_working_weekdays",
        caption=(
            "Selecciona els dies de la setmana en què cada facultatiu mai "
            "està disponible. Aplica a tot el rang del calendari planificat."
        ),
        header="Dies forçats no laborables",
        placeholder="Cap dia no laborable",
        key_prefix="absences_offdays_picker",
        draft_key="non_working_weekdays_picker",
    )


def render_no_pres_weekdays_editor(
    professionals_path: Path,
    eligibility_path: Path,
) -> None:
    """Subpestanya de Restriccions: dies de la setmana en què cada
    facultatiu només pot fer NO_PRESENCIAL. La restricció és TOVA: el
    solver penalitza fort els PRES en aquells dies però pot infringir-ho
    si la cobertura del calendari ho exigeix. Les revisions NO compten
    (no són ni PRES ni NP en aquest sentit; passen sempre)."""
    st.markdown(
        "Per cada facultatiu, marca els dies de la setmana en què "
        "**només** ha de fer activitat **no-presencial**. Restricció "
        "**tova** (pes molt alt): el solver l'evita sempre, però pot "
        "infringir-la si és estrictament necessari per cobrir el "
        "calendari. Les revisions queden fora — sí que es poden fer "
        "aquell dia."
    )
    _render_weekday_picker_block(
        professionals_path=professionals_path,
        eligibility_path=eligibility_path,
        column="no_pres_weekdays",
        caption="",
        header="Dies no-presencials",
        placeholder="Cap dia NP-only",
        key_prefix="no_pres_weekdays_picker",
        draft_key="no_pres_weekdays_picker",
    )


def render_pres_weekdays_editor(
    professionals_path: Path,
    eligibility_path: Path,
) -> None:
    """Subpestanya simètrica: dies en què cada facultatiu només pot
    fer activitat presencial. Restricció TOVA (mateix pes que el cas
    NP-only); revisions excloses."""
    st.markdown(
        "Per cada facultatiu, marca els dies de la setmana en què "
        "**només** ha de fer activitat **presencial**. Restricció "
        "**tova** (pes molt alt): el solver l'evita sempre, però pot "
        "infringir-la si és estrictament necessari per cobrir el "
        "calendari. Les revisions queden fora — sí que es poden fer "
        "aquell dia."
    )
    _render_weekday_picker_block(
        professionals_path=professionals_path,
        eligibility_path=eligibility_path,
        column="pres_weekdays",
        caption="",
        header="Dies presencials",
        placeholder="Cap dia PRES-only",
        key_prefix="pres_weekdays_picker",
        draft_key="pres_weekdays_picker",
    )


def _render_weekday_picker_block(
    *,
    professionals_path: Path,
    eligibility_path: Path,
    column: str,
    caption: str,
    header: str,
    placeholder: str,
    key_prefix: str,
    draft_key: str,
) -> None:
    """Patró comú: multiselect MON..SUN per facultatiu sobre la columna
    `column` de professionals.csv (semicolon-list de codis). Autosave."""
    weekday_df = read_table(
        professionals_path,
        ["professional_id", "name", "doubled_machines",
         "non_working_weekdays", "no_pres_weekdays", "pres_weekdays"],
    )
    scope_df = professional_scope_df(weekday_df)
    if scope_df.empty:
        st.info("Primer introdueix facultatius a la pestanya Facultatius.")
        return

    if caption:
        st.caption(caption)
    header_label, header_pick = st.columns([1, 4])
    with header_label:
        st.markdown("**Facultatiu**")
    with header_pick:
        st.markdown(f"**{header}**")

    new_values: dict[str, str] = {}
    for _, row in scope_df.iterrows():
        pid = str(row["professional_id"]).strip().upper()
        if not pid or pid == "NONE":
            continue
        current = [
            d.strip().upper()
            for d in str(row.get(column, "") or "").split(";")
            if d.strip().upper() in WEEKDAY_CODES
        ]
        col_label, col_pick = st.columns([1, 4])
        with col_label:
            display_name = str(row.get("name", "") or "").strip()
            label = f"**{pid}**" if not display_name else f"**{pid}** · {display_name}"
            st.markdown(label)
        with col_pick:
            selected = st.multiselect(
                column,
                options=WEEKDAY_CODES,
                default=current,
                key=f"{key_prefix}_{pid}",
                label_visibility="collapsed",
                placeholder=placeholder,
            )
        new_values[pid] = ";".join(sorted({d for d in selected if d}))

    # Re-build scope_df amb la nova columna; autosave.
    updated = scope_df.copy()
    updated[column] = updated["professional_id"].apply(
        lambda pid: new_values.get(str(pid).strip().upper(), "")
    )
    scope_cols = [
        "professional_id", "name", "dies_laborables",
        "doubled_machines", "non_working_weekdays", "no_pres_weekdays",
        "pres_weekdays",
    ]
    autosave_draft_if_changed(
        draft_key,
        updated[scope_cols],
        scope_cols,
        lambda df: save_professional_scope(
            df, professionals_path, eligibility_path,
        ),
    )


def _render_specific_days_unavailability_block(
    unavailability_path: Path,
    all_professional_options: list[str],
) -> None:
    """Editor per a entrades puntuals (pid, dia) a l'unavailability manual."""
    df = read_table(unavailability_path, ["professional_id", "day", "reason"])
    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    draft = table_draft(
        "specific_unavailability_draft",
        df,
        ["professional_id", "day", "reason"],
        source_table_signature(unavailability_path, df),
    )

    def _save(df_to_save: pd.DataFrame) -> None:
        out = df_to_save.copy()
        for col in ["professional_id", "day", "reason"]:
            if col not in out.columns:
                out[col] = ""
        out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
        out["day"] = pd.to_datetime(out["day"], errors="coerce")
        out["reason"] = out["reason"].fillna("").astype(str)
        out = out[
            (out["professional_id"] != "")
            & out["professional_id"].isin(set(all_professional_options))
            & out["day"].notna()
        ].copy()
        out["day"] = out["day"].dt.strftime("%Y-%m-%d")
        out = out.drop_duplicates(subset=["professional_id", "day"], keep="last")
        out = out.sort_values(["day", "professional_id"]).reset_index(drop=True)
        from src.services.table_io import save_table as _save_table
        _save_table(unavailability_path, out, ["professional_id", "day", "reason"])

    with st.form("quick_add_specific_unavailability", clear_on_submit=True):
        st.caption("Afegir ràpidament: facultatiu + dia + motiu (opcional), Enter per afegir.")
        cols_form = st.columns([2, 2, 3, 1])
        with cols_form[0]:
            qa_pid = st.selectbox(
                "pid", options=all_professional_options or [""],
                index=0, label_visibility="collapsed",
            )
        with cols_form[1]:
            qa_day = st.date_input("day", value=None, format="DD/MM/YYYY",
                                   label_visibility="collapsed")
        with cols_form[2]:
            qa_reason = st.text_input("motiu", placeholder="motiu (opcional)",
                                      label_visibility="collapsed")
        with cols_form[3]:
            submitted = st.form_submit_button("Afegir", width="stretch")
        if submitted:
            pid_clean = (qa_pid or "").strip().upper()
            if not pid_clean:
                st.error("Cal un facultatiu.")
            elif not qa_day:
                st.error("Cal un dia.")
            else:
                commit_new_row(
                    "specific_unavailability_draft",
                    {
                        "professional_id": pid_clean,
                        "day": pd.to_datetime(qa_day),
                        "reason": (qa_reason or "").strip(),
                    },
                    ["professional_id", "day", "reason"],
                    _save,
                    fallback_df=draft,
                )

    editor_nonce = st.session_state.get("specific_unavailability_editor_nonce", 0)
    _draft_show = st.session_state["specific_unavailability_draft"].copy()
    _draft_show["day"] = pd.to_datetime(_draft_show["day"], errors="coerce")
    _draft_show["professional_id"] = _draft_show["professional_id"].fillna("").astype(str)
    _draft_show["reason"] = _draft_show["reason"].fillna("").astype(str)
    _n_spec_rows = len(_draft_show)
    _draft_show["_eliminar"] = False
    edited = st.data_editor(
        _draft_show,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=data_editor_height(_n_spec_rows),
        key=f"specific_unavailability_editor_{editor_nonce}",
        column_order=["professional_id", "day", "reason", "_eliminar"],
        column_config={
            "professional_id": st.column_config.SelectboxColumn("Facultatiu", options=all_professional_options),
            "day": st.column_config.DateColumn("Dia", format="DD/MM/YYYY"),
            "reason": st.column_config.TextColumn("Motiu"),
            "_eliminar": st.column_config.CheckboxColumn(
                "Eliminar",
                help="Marca les files que vulguis eliminar i prem el botó de sota.",
            ),
        },
    )

    _mark = (
        edited["_eliminar"].fillna(False).astype(bool)
        if "_eliminar" in edited.columns
        else pd.Series(False, index=edited.index)
    )
    _n_marked = int(_mark.sum())
    if st.button(
        f"🗑️ Eliminar {_n_marked} indisponibilitat(s) marcada(es)"
        if _n_marked
        else "🗑️ Eliminar indisponibilitat(s) marcades",
        disabled=_n_marked == 0,
        key="specific_unavail_delete_marked",
    ):
        kept = edited.loc[
            ~_mark, ["professional_id", "day", "reason"]
        ].copy().reset_index(drop=True)
        st.session_state["specific_unavailability_draft"] = kept
        st.session_state["specific_unavailability_editor_nonce"] = editor_nonce + 1
        _save(kept)
        st.rerun()

    st.session_state["specific_unavailability_draft"] = edited[
        ["professional_id", "day", "reason"]
    ].copy()
    autosave_draft_if_changed(
        "specific_unavailability",
        st.session_state["specific_unavailability_draft"],
        ["professional_id", "day", "reason"],
        _save,
    )


def render_guards_editor(guards_path: Path, all_professional_options: list[str]) -> None:
    guards_df = read_table(guards_path, ["day", "professional_id", "guard_kind", "notes"])
    guards_df["day"] = pd.to_datetime(guards_df["day"], errors="coerce")
    guards_editor_df = table_draft(
        "guards_draft",
        guards_df,
        ["day", "professional_id", "guard_kind", "notes"],
        source_table_signature(guards_path, guards_df),
    )
    valid_professionals = set(all_professional_options)
    with st.form("quick_add_guard", clear_on_submit=True):
        st.caption("Afegir ràpidament: omple i prem **Enter** per afegir.")
        cols_form = st.columns([2, 2, 2, 1])
        with cols_form[0]:
            qa_day = st.date_input("day", value=None, format="DD/MM/YYYY",
                                   label_visibility="collapsed")
        with cols_form[1]:
            qa_pid = st.selectbox("pid", options=all_professional_options or [""],
                                  index=0, label_visibility="collapsed")
        with cols_form[2]:
            qa_kind = st.selectbox("kind", options=["guardia", "refuerzo"],
                                   index=0, label_visibility="collapsed")
        with cols_form[3]:
            submitted = st.form_submit_button("Afegir", width="stretch")
        if submitted:
            pid_clean = (qa_pid or "").strip().upper()
            if not qa_day:
                st.error("Cal un dia.")
            elif not pid_clean:
                st.error("Cal un facultatiu.")
            else:
                commit_new_row(
                    "guards_draft",
                    {
                        "day": pd.to_datetime(qa_day),
                        "professional_id": pid_clean,
                        "guard_kind": qa_kind,
                        "notes": "",
                    },
                    ["day", "professional_id", "guard_kind", "notes"],
                    lambda df: save_guards(df, guards_path, valid_professionals),
                    fallback_df=guards_editor_df,
                )

    editor_nonce = st.session_state.get("guards_editor_nonce", 0)
    _n_guards_rows = len(st.session_state["guards_draft"])
    _guards_src = st.session_state["guards_draft"].copy()
    _guards_src["_eliminar"] = False
    edited_guards = st.data_editor(
        _guards_src,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=data_editor_height(_n_guards_rows),
        key=f"guards_editor_main_{editor_nonce}",
        column_order=["day", "professional_id", "guard_kind", "_eliminar"],
        column_config={
            "day": st.column_config.DateColumn("Dia", format="DD/MM/YYYY"),
            "professional_id": st.column_config.SelectboxColumn("Facultatiu", options=all_professional_options),
            "guard_kind": st.column_config.SelectboxColumn("Tipus de guàrdia", options=["guardia", "refuerzo"]),
            "_eliminar": st.column_config.CheckboxColumn(
                "Eliminar",
                help="Marca les files que vulguis eliminar i prem el botó de sota.",
            ),
        },
    )

    _mark = (
        edited_guards["_eliminar"].fillna(False).astype(bool)
        if "_eliminar" in edited_guards.columns
        else pd.Series(False, index=edited_guards.index)
    )
    _n_marked = int(_mark.sum())
    if st.button(
        f"🗑️ Eliminar {_n_marked} guàrdia/reforç marcat(s)"
        if _n_marked
        else "🗑️ Eliminar guàrdia/reforç marcats",
        disabled=_n_marked == 0,
        key="guards_delete_marked",
    ):
        kept = edited_guards.loc[
            ~_mark, ["day", "professional_id", "guard_kind", "notes"]
        ].copy().reset_index(drop=True)
        st.session_state["guards_draft"] = kept
        st.session_state["guards_editor_nonce"] = editor_nonce + 1
        save_guards(kept, guards_path, valid_professionals)
        st.rerun()

    st.session_state["guards_draft"] = edited_guards[["day", "professional_id", "guard_kind", "notes"]].copy()
    autosave_draft_if_changed(
        "guards",
        st.session_state["guards_draft"],
        ["day", "professional_id", "guard_kind", "notes"],
        lambda df: save_guards(df, guards_path, valid_professionals),
    )
