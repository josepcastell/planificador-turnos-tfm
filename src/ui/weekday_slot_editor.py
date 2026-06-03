import calendar
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import (
    CATALAN_MONTHS,
    WEEKDAY_LABELS,
    WEEKDAY_TEMPLATE_COLUMNS,
)
from src.services.calendar_settings import default_required_staff
from src.services.input_tables import save_weekly_slot_templates
from src.services.slot_templates import (
    add_template_override,
    add_work_slot_template,
    load_template_overrides,
    remove_work_slot_template,
    save_template_overrides,
    slots_for_day_with_overrides,
    work_slots_for_weekday_and_franja,
)
from src.ui.calendar_html import non_working_days_for_calendar


FRANJA_LABELS = {"MATI": "Matí", "TARDA": "Tarda", "NIT": "Nit"}
PRESENTIALITY_OPTIONS = ["PRESENCIAL", "NO_PRESENCIAL"]
FRANJA_OPTIONS = list(FRANJA_LABELS)
# MODEL DE PEONADES: l'usuari ja no marca slots com a peonada al
# template. El solver decideix automàticament fins a 3 (o N proporcional
# a la jornada) NO_PRES per facultatiu i mes com a peonades (cap HARD)
# — vegeu `_add_peonada_monthly_cap` al solver. Per això tots els slots
# generats des d'aquest editor són sempre NORMAL.
_DEFAULT_WORK_MODE = "NORMAL"


def _edit_suffix(values: dict[str, object], parts: list[str]) -> str:
    return "_".join(str(values.get(part, "")).replace(" ", "_").replace("-", "_") for part in parts)


def _render_franja_badge(franja: str) -> None:
    st.caption(FRANJA_LABELS[franja])


def render_weekday_work_slot_editor(
    year: int,
    display_month: int,
    base_calendar_path: Path,
    public_holidays_path: Path,
    templates_df: pd.DataFrame,
    existing_slots: list[str],
    weekly_templates_path: Path,
    template_overrides_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    """Editor de les franges fixes setmanals (estructura). Els canvis
    puntuals del mes (overrides per dia concret) viuen ara a la pestanya
    de Mètriques › Altres restriccions com a expander a part: vegeu
    `render_weekday_punctual_overrides_editor`."""
    default_required = default_required_staff()

    st.subheader("Franges fixes setmanals")
    st.caption(
        "Patró setmanal de slots. Clica una franja per editar-la o «+» per "
        "afegir-ne una de nova. **🔁** = doblada · **🔗** = vinculada amb "
        "una altra màquina · **🔁🔗** = doblada *i* vinculada."
    )
    _render_selected_fixed_slot_editor(
        templates_df,
        existing_slots,
        weekly_templates_path,
        invalidate_after_work_slot_change,
    )
    _render_selected_fixed_cell_editor(
        templates_df,
        existing_slots,
        weekly_templates_path,
        invalidate_after_work_slot_change,
    )
    _render_fixed_weekly_calendar(templates_df, default_required)


def render_weekday_punctual_overrides_editor(
    year: int,
    display_month: int,
    base_calendar_path: Path,
    public_holidays_path: Path,
    templates_df: pd.DataFrame,
    existing_slots: list[str],
    template_overrides_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    """Canvis puntuals del mes (overrides per dia concret) — extret de
    `render_weekday_work_slot_editor` perquè ara viu a Mètriques › Altres
    restriccions, no a l'editor de franges (les franges es configuren
    abans de generar; els canvis puntuals s'apliquen després)."""
    overrides_df = load_template_overrides(template_overrides_path)
    default_required = default_required_staff()
    _render_selected_punctual_slot_editor(
        overrides_df,
        existing_slots,
        template_overrides_path,
        year,
        invalidate_after_work_slot_change,
    )
    _render_selected_punctual_cell_editor(
        overrides_df,
        existing_slots,
        template_overrides_path,
        invalidate_after_work_slot_change,
    )
    _render_punctual_month_calendar(
        year,
        display_month,
        base_calendar_path,
        public_holidays_path,
        templates_df,
        overrides_df,
        default_required,
    )


def _render_franja_slot_pres_selectors(
    col_franja, col_slot, col_pres, selected, edit_suffix, existing_slots, key_prefix,
):
    """Els 3 selectors COMUNS als editors de franja fixa i puntual: Franja,
    Màquina/slot i Presencialitat (lògica idèntica; només canvien el prefix
    de clau i el dict `selected`). Retorna (franja, slot, presentiality).
    La resta de cada editor (dia/data, vinculació, doblatge, persistència)
    difereix prou per mantenir-los com a funcions separades."""
    with col_franja:
        franja = st.selectbox(
            "Franja",
            FRANJA_OPTIONS,
            index=(
                FRANJA_OPTIONS.index(selected["franja"])
                if selected["franja"] in FRANJA_OPTIONS
                else 0
            ),
            key=f"{key_prefix}_franja_{edit_suffix}",
            format_func=lambda value: FRANJA_LABELS[value],
        )
    with col_slot:
        current_slot = str(selected["slot_id"]).strip().upper()
        slot_options = list(existing_slots)
        if current_slot and current_slot not in slot_options:
            slot_options = [current_slot, *slot_options]
        slot = st.selectbox(
            "Màquina/slot",
            options=slot_options,
            index=slot_options.index(current_slot) if current_slot in slot_options else 0,
            key=f"{key_prefix}_slot_{edit_suffix}",
            help="Tria un slot del catàleg (Calendari base → Slots disponibles).",
        ).strip().upper()
    with col_pres:
        presentiality = st.selectbox(
            "Presencialitat",
            PRESENTIALITY_OPTIONS,
            index=0 if selected["presentiality"] == "PRESENCIAL" else 1,
            key=f"{key_prefix}_presentiality_{edit_suffix}",
            format_func=lambda value: value.replace("_", " ").title(),
        )
    return franja, slot, presentiality


def _render_selected_fixed_slot_editor(
    templates_df: pd.DataFrame,
    existing_slots: list[str],
    weekly_templates_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    selected_fixed_edit = st.session_state.get("selected_fixed_work_slot_edit")
    if not selected_fixed_edit:
        return

    edit_suffix = _edit_suffix(
        selected_fixed_edit,
        ["weekday_name", "franja", "slot_id", "presentiality", "work_mode"],
    )
    st.markdown(
        f"**Editar franja fixa:** {selected_fixed_edit['weekday_label']} · "
        f"{selected_fixed_edit['franja'].lower()}"
    )
    edit_col1, edit_col2, edit_col3, edit_col4, edit_col5, edit_col6 = st.columns(
        [1, 0.9, 1.4, 1, 1.2, 0.7]
    )
    with edit_col1:
        edited_fixed_weekday = st.selectbox(
            "Dia",
            WEEKDAY_TEMPLATE_COLUMNS,
            index=(
                WEEKDAY_TEMPLATE_COLUMNS.index(selected_fixed_edit["weekday_name"])
                if selected_fixed_edit["weekday_name"] in WEEKDAY_TEMPLATE_COLUMNS
                else 0
            ),
            key=f"fixed_edit_weekday_{edit_suffix}",
            format_func=lambda value: WEEKDAY_LABELS[WEEKDAY_TEMPLATE_COLUMNS.index(value)],
        )
    (edited_fixed_franja, edited_fixed_slot,
     edited_fixed_presentiality) = _render_franja_slot_pres_selectors(
        edit_col2, edit_col3, edit_col4, selected_fixed_edit, edit_suffix,
        existing_slots, "fixed_edit",
    )
    with edit_col5:
        # Màquina secundària: dropdown amb la resta de màquines. Si es
        # tria, queda lligada a aquesta com a NO_PRESENCIAL (LOCAL a
        # (dia, franja) — no afecta altres franges).
        _edit_link_current = _link_partner_for_template_cell(
            templates_df,
            selected_fixed_edit["weekday_name"],
            selected_fixed_edit["franja"],
            edited_fixed_slot,
        )
        _edit_link_opts = [""] + [
            s for s in existing_slots
            if str(s).strip().upper() != edited_fixed_slot
        ]
        _edit_link_idx = (
            _edit_link_opts.index(_edit_link_current)
            if _edit_link_current and _edit_link_current in _edit_link_opts
            else 0
        )
        edited_link_choice = st.selectbox(
            "Màquina secundària (NP, vinculada)",
            options=_edit_link_opts,
            index=_edit_link_idx,
            key=f"fixed_edit_link_{edit_suffix}",
            help=(
                "Slot secundari que queda vinculat a aquest (mateix "
                "facultatiu cobreix les dues a la mateixa franja). "
                "Buit = sense vinculació."
            ),
        )
    with edit_col6:
        # Doblar: detecta si l'slot està actualment doblat (té PRES + NP
        # al mateix (dia, franja, slot_id)).
        _orig_wd = selected_fixed_edit["weekday_name"]
        _orig_fr = selected_fixed_edit["franja"]
        _orig_sid = selected_fixed_edit["slot_id"]
        _siblings = templates_df[
            (templates_df["weekday_name"].astype(str) == str(_orig_wd))
            & (templates_df["franja"].astype(str) == str(_orig_fr))
            & (templates_df["slot_id"].astype(str).str.strip().str.upper()
               == str(_orig_sid).strip().upper())
        ]
        _sibling_pres = set(
            _siblings["presentiality"].astype(str).str.upper().tolist()
        )
        _is_currently_doubled = (
            {"PRESENCIAL", "NO_PRESENCIAL"}.issubset(_sibling_pres)
        )
        edited_doubled_choice = st.checkbox(
            "Doblar",
            value=_is_currently_doubled,
            key=f"fixed_edit_doubled_{edit_suffix}",
            help=(
                "Si està marcat: el slot té 2 files (PRESENCIAL + "
                "NO_PRESENCIAL) per al mateix (dia, franja). Si la "
                "desmarques, eliminem la fila de la presencialitat "
                "OPOSADA a la que estàs editant; només queda la triada."
            ),
        )
    # NOU MODEL DE PEONADES: el work_mode ja no s'edita aquí.
    edited_fixed_work_mode = _DEFAULT_WORK_MODE
    edited_fixed_required_staff = 1

    edit_actions = st.columns(3)
    with edit_actions[0]:
        if st.button(
            "Guardar canvi",
            disabled=not edited_fixed_slot,
            width="stretch",
            key=f"save_fixed_edit_{edit_suffix}",
        ):
            templates_df = remove_work_slot_template(
                templates_df,
                selected_fixed_edit["weekday_name"],
                selected_fixed_edit["franja"],
                selected_fixed_edit["slot_id"],
                selected_fixed_edit["presentiality"],
                selected_fixed_edit["work_mode"],
            )
            templates_df = add_work_slot_template(
                templates_df,
                edited_fixed_weekday,
                edited_fixed_franja,
                edited_fixed_slot,
                edited_fixed_presentiality,
                edited_fixed_work_mode,
                int(edited_fixed_required_staff),
                doubled=0,
            )
            # Gestió del checkbox Doblar:
            #  - Si marcat → garantim que existeix també la sibling de
            #    la presencialitat OPOSADA per al mateix (dia, franja, slot).
            #  - Si desmarcat → eliminem la sibling oposada (si hi era).
            _opposite_pres = (
                "NO_PRESENCIAL" if edited_fixed_presentiality == "PRESENCIAL"
                else "PRESENCIAL"
            )
            if bool(edited_doubled_choice):
                templates_df = add_work_slot_template(
                    templates_df,
                    edited_fixed_weekday,
                    edited_fixed_franja,
                    edited_fixed_slot,
                    _opposite_pres,
                    edited_fixed_work_mode,
                    int(edited_fixed_required_staff),
                    doubled=0,
                )
            else:
                templates_df = remove_work_slot_template(
                    templates_df,
                    edited_fixed_weekday,
                    edited_fixed_franja,
                    edited_fixed_slot,
                    _opposite_pres,
                    edited_fixed_work_mode,
                )
            # Persisteix la vinculació al template (per (dia, franja))
            # si l'usuari l'ha modificada.
            _new_edit_link = str(edited_link_choice or "").strip().upper()
            if _new_edit_link != _edit_link_current:
                templates_df = _save_linked_to_in_template(
                    templates_df,
                    edited_fixed_weekday,
                    edited_fixed_franja,
                    edited_fixed_slot,
                    _new_edit_link,
                    weekly_templates_path,
                )
            save_weekly_slot_templates(templates_df, weekly_templates_path)
            invalidate_after_work_slot_change()
            st.session_state.pop("selected_fixed_work_slot_edit", None)
            st.rerun()
    with edit_actions[1]:
        if st.button("Eliminar franja", width="stretch", key=f"delete_fixed_edit_{edit_suffix}"):
            templates_df = remove_work_slot_template(
                templates_df,
                selected_fixed_edit["weekday_name"],
                selected_fixed_edit["franja"],
                selected_fixed_edit["slot_id"],
                selected_fixed_edit["presentiality"],
                selected_fixed_edit["work_mode"],
            )
            save_weekly_slot_templates(templates_df, weekly_templates_path)
            invalidate_after_work_slot_change()
            st.session_state.pop("selected_fixed_work_slot_edit", None)
            st.rerun()
    with edit_actions[2]:
        if st.button("Cancel·lar", width="stretch", key=f"cancel_fixed_edit_{edit_suffix}"):
            st.session_state.pop("selected_fixed_work_slot_edit", None)
            st.rerun()


def _secondary_slots() -> set[str]:
    """Set d'slot_ids marcats com a "màquina secundària" al catàleg
    (apareixen al camp `linked_to` d'alguna altra fila). Els slots
    secundaris s'autodefaulteja a NO_PRESENCIAL al template."""
    try:
        cat = pd.read_csv(Path("data/slot_catalog.csv"))
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return set()
    if "linked_to" not in cat.columns:
        return set()
    return {
        s.strip().upper()
        for s in cat["linked_to"].fillna("").astype(str)
        if s.strip()
    }


def _render_selected_fixed_cell_editor(
    templates_df: pd.DataFrame,
    existing_slots: list[str],
    weekly_templates_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    selected_fixed_cell = st.session_state.get("selected_fixed_work_slot_cell")
    if not selected_fixed_cell:
        return

    st.markdown(
        f"**Afegir franja fixa:** {selected_fixed_cell['weekday_label']} · "
        f"{selected_fixed_cell['franja'].lower()}"
    )
    st.caption(
        "Jerarquia: **Màquina principal** sempre PRESENCIAL. Si tries "
        "**Màquina secundària**, s'afegeix automàticament com a "
        "NO_PRESENCIAL i queda **vinculada** a la principal (el mateix "
        "facultatiu cobreix les dues). Si tries **Doblar**, el slot "
        "principal apareix dues vegades (PRES + NP, dos facultatius)."
    )
    add_col1, add_col2, add_col3, add_col4 = st.columns([1.4, 1.4, 0.7, 0.8])
    with add_col1:
        slot_choice = st.selectbox(
            "Màquina principal (PRES)",
            [""] + existing_slots,
            key="fixed_calendar_slot_choice",
            help="Slot primari (PRESENCIAL). El facultatiu hi és presencial.",
        )
    with add_col2:
        slot_to_add_now = str(slot_choice).strip().upper()
        _sec_options = [""] + [
            s for s in existing_slots
            if str(s).strip().upper() != slot_to_add_now
        ]
        link_choice = st.selectbox(
            "Màquina secundària (NP, vinculada)",
            options=_sec_options,
            index=0,
            key=f"fixed_calendar_link_{slot_choice}",
            help=(
                "Opcional. Si tries un slot aquí, s'afegirà com a "
                "NO_PRESENCIAL i quedarà vinculat a la principal "
                "(el mateix facultatiu cobreix les dues màquines a "
                "aquesta franja). Només per aquesta (dia, franja)."
            ),
        )
    with add_col3:
        doubled_choice = st.checkbox(
            "Doblar",
            value=False,
            key="fixed_calendar_doubled",
            help="Si marcat: la principal apareix 2 vegades (PRES + NP, "
                 "2 facultatius diferents). Mutuament exclusiu amb "
                 "Màquina secundària.",
        )
    with add_col4:
        st.write("")
        st.write("")
        slot_to_add = str(slot_choice).strip().upper()
        if st.button(
            "Afegir",
            disabled=not slot_to_add,
            width="stretch",
            key="fixed_calendar_add_slot",
        ):
            _new_link = str(link_choice or "").strip().upper()
            # Validació: doblar + secundària = error.
            if bool(doubled_choice) and _new_link:
                st.error(
                    "No pots marcar **Doblar** i triar una **Màquina "
                    "secundària** alhora. Tria només una de les dues opcions."
                )
                st.stop()
            # Principal sempre PRESENCIAL.
            templates_df = add_work_slot_template(
                templates_df,
                selected_fixed_cell["weekday_name"],
                selected_fixed_cell["franja"],
                slot_to_add,
                "PRESENCIAL",
                _DEFAULT_WORK_MODE,
                doubled=0,
            )
            if bool(doubled_choice):
                # DOBLAR: afegim també la NP del mateix slot.
                templates_df = add_work_slot_template(
                    templates_df,
                    selected_fixed_cell["weekday_name"],
                    selected_fixed_cell["franja"],
                    slot_to_add,
                    "NO_PRESENCIAL",
                    _DEFAULT_WORK_MODE,
                    doubled=0,
                )
            if _new_link:
                # VINCULAR amb secundària: afegim el secundari com a NP
                # i posem linked_to=secundari a la principal (template).
                templates_df = add_work_slot_template(
                    templates_df,
                    selected_fixed_cell["weekday_name"],
                    selected_fixed_cell["franja"],
                    _new_link,
                    "NO_PRESENCIAL",
                    _DEFAULT_WORK_MODE,
                    doubled=0,
                )
                templates_df = _save_linked_to_in_template(
                    templates_df,
                    selected_fixed_cell["weekday_name"],
                    selected_fixed_cell["franja"],
                    slot_to_add,
                    _new_link,
                    weekly_templates_path,
                )
            save_weekly_slot_templates(templates_df, weekly_templates_path)
            invalidate_after_work_slot_change()
            st.session_state.pop("selected_fixed_work_slot_cell", None)
            st.rerun()


def _link_partner_map_from_templates(
    templates_df: pd.DataFrame,
) -> dict[tuple[str, str, str], str]:
    """Mapatge bidireccional (weekday_name, franja, slot_id) → partner
    derivat dels templates setmanals (camp `linked_to`). Cada vinculació
    es registra en ambdues direccions A↔B per a aquella (weekday, franja).
    Si el template no té cap linking, retorna {}."""
    out: dict[tuple[str, str, str], str] = {}
    if (
        templates_df is None or templates_df.empty
        or "linked_to" not in templates_df.columns
    ):
        return out
    _EMPTY = {"", "NAN", "NONE"}
    for row in templates_df.itertuples(index=False):
        wd = str(getattr(row, "weekday_name", "") or "").strip().upper()
        fr = str(getattr(row, "franja", "") or "").strip().upper()
        a_raw = getattr(row, "slot_id", "")
        b_raw = getattr(row, "linked_to", "")
        a = "" if pd.isna(a_raw) else str(a_raw).strip().upper()
        b = "" if pd.isna(b_raw) else str(b_raw).strip().upper()
        if not wd or not fr or a in _EMPTY or b in _EMPTY:
            continue
        out[(wd, fr, a)] = b
        out[(wd, fr, b)] = a
    return out


def _save_linked_to_in_template(
    templates_df: pd.DataFrame,
    weekday_name: str,
    franja: str,
    slot_id: str,
    partner: str,
    weekly_templates_path: Path,
) -> pd.DataFrame:
    """Actualitza el camp `linked_to` de la fila concreta del template
    (per (weekday_name, franja, slot_id)). La vinculació passa a ser
    LOCAL a la franja, no global al catàleg."""
    df = templates_df.copy()
    if "linked_to" not in df.columns:
        df["linked_to"] = ""
    df["linked_to"] = df["linked_to"].astype(object).fillna("")
    sid = str(slot_id).strip().upper()
    new_val = str(partner or "").strip().upper()
    mask = (
        (df["weekday_name"].astype(str) == str(weekday_name))
        & (df["franja"].astype(str) == str(franja))
        & (df["slot_id"].astype(str).str.strip().str.upper() == sid)
    )
    if not mask.any():
        return df
    df.loc[mask, "linked_to"] = new_val
    save_weekly_slot_templates(df, weekly_templates_path)
    return df


def _link_partner_for_template_cell(
    templates_df: pd.DataFrame,
    weekday_name: str,
    franja: str,
    slot_id: str,
) -> str:
    """Retorna el partner (linked_to) per a una cel·la concreta del
    template. Si no hi ha vinculació, retorna ''."""
    if templates_df.empty or "linked_to" not in templates_df.columns:
        return ""
    sid = str(slot_id).strip().upper()
    mask = (
        (templates_df["weekday_name"].astype(str) == str(weekday_name))
        & (templates_df["franja"].astype(str) == str(franja))
        & (templates_df["slot_id"].astype(str).str.strip().str.upper() == sid)
    )
    if not mask.any():
        return ""
    vals = templates_df.loc[mask, "linked_to"].fillna("").astype(str).str.strip().str.upper()
    for v in vals:
        if v and v not in {"NAN", "NONE"}:
            return v
    return ""


def _render_franja_button(
    weekday_name: str,
    weekday_idx: int,
    franja: str,
    slot_row,
    pres_abbr: str,
    is_doubled: bool,
    is_linked: bool = False,
    link_partner: str | None = None,
) -> None:
    """Renderitza el botó d'edició d'una franja fixa amb marcadors
    visuals al label per a slots doblats (🔁) i/o vinculats (🔗).
    La llegenda dels símbols s'explica fora de les franges (vegeu
    `render_weekday_work_slot_editor`)."""
    prefix = ""
    if is_doubled and is_linked:
        prefix = "🔁🔗 "
    elif is_doubled:
        prefix = "🔁 "
    elif is_linked:
        prefix = "🔗 "
    slot_label = f"{prefix}{slot_row.slot_id} · {pres_abbr}"
    extra = []
    if is_doubled:
        extra.append("doblada")
    if is_linked:
        extra.append(f"vinculada amb {link_partner}")
    extra_text = f" ({', '.join(extra)})" if extra else ""
    slot_help = (
        f"{slot_row.slot_id} · "
        f"{slot_row.presentiality.replace('_', ' ').title()}"
        f"{extra_text} — clica per editar"
    )
    if st.button(
        slot_label,
        key=(
            f"edit_fixed_{weekday_name}_{franja}_{slot_row.slot_id}_"
            f"{slot_row.presentiality}_{slot_row.work_mode}"
        ),
        width="stretch",
        help=slot_help,
    ):
        st.session_state["selected_fixed_work_slot_edit"] = {
            "weekday_name": weekday_name,
            "weekday_label": WEEKDAY_LABELS[weekday_idx],
            "franja": franja,
            "slot_id": str(slot_row.slot_id),
            "presentiality": str(slot_row.presentiality),
            "work_mode": str(slot_row.work_mode),
            "required_staff": int(getattr(slot_row, "required_staff", 1)),
            "doubled": 0,
        }
        st.session_state.pop("selected_fixed_work_slot_cell", None)
        st.rerun()


def _render_fixed_weekly_calendar(
    templates_df: pd.DataFrame,
    default_required: int = 1,
) -> None:
    fixed_cols = st.columns(5, gap="small")
    # Mapatge de vincles per (weekday_name, franja, slot_id) → partner,
    # derivat dels templates (NO del catàleg). Bidireccional.
    partner_map = _link_partner_map_from_templates(templates_df)
    for weekday_idx, weekday_name in enumerate(WEEKDAY_TEMPLATE_COLUMNS):
        with fixed_cols[weekday_idx]:
            with st.container(border=True):
                st.markdown(f"**{WEEKDAY_LABELS[weekday_idx]}**")
                for franja in FRANJA_OPTIONS:
                    with st.container(key=f"franjabox_{franja}_{weekday_name}"):
                        _render_franja_badge(franja)
                        day_slots = work_slots_for_weekday_and_franja(
                            templates_df, weekday_name, franja,
                        )
                        # Comptem instàncies per slot_id per detectar doblades.
                        slot_counts: dict[str, int] = {}
                        slot_ids_present: set[str] = set()
                        for r in day_slots.itertuples(index=False):
                            sid = str(r.slot_id).upper()
                            slot_counts[sid] = slot_counts.get(sid, 0) + 1
                            slot_ids_present.add(sid)
                        # Pre-calcula l'ÍNDEX del representatiu de cada
                        # slot_id: la primera fila amb presentiality=
                        # PRESENCIAL (o la primera de qualsevol
                        # presentiality si no n'hi ha cap de PRES).
                        # Només l'instància representativa està REALMENT
                        # vinculada — la doblada NP és independent.
                        #
                        # IMPORTANT: comparem per índex, no per identitat
                        # d'objecte. `itertuples()` retorna namedtuples
                        # NOUS a cada iteració, així `is` mai no funciona.
                        rep_idx_by_sid: dict[str, int] = {}
                        key_by_idx: dict[int, tuple] = {}
                        for idx, r in enumerate(day_slots.itertuples(index=False)):
                            sid = str(r.slot_id).upper()
                            key = (
                                0 if str(r.presentiality).upper() == "PRESENCIAL"
                                else 1,
                                idx,
                            )
                            key_by_idx[idx] = key
                            cur = rep_idx_by_sid.get(sid)
                            if cur is None or key < key_by_idx[cur]:
                                rep_idx_by_sid[sid] = idx
                        for idx, slot_row in enumerate(
                            day_slots.itertuples(index=False)
                        ):
                            sid = str(slot_row.slot_id).upper()
                            is_doubled = slot_counts.get(sid, 1) >= 2
                            partner = partner_map.get((weekday_name, franja, sid))
                            is_rep = rep_idx_by_sid.get(sid) == idx
                            is_linked = (
                                partner is not None
                                and partner in slot_ids_present
                                and is_rep
                            )
                            pres_abbr = (
                                "P" if str(slot_row.presentiality) == "PRESENCIAL"
                                else "NP"
                            )
                            _render_franja_button(
                                weekday_name, weekday_idx, franja, slot_row,
                                pres_abbr, is_doubled,
                                is_linked=is_linked,
                                link_partner=partner if is_linked else None,
                            )
                        if st.button(
                            "+",
                            key=f"select_fixed_cell_{weekday_name}_{franja}",
                            width="stretch",
                            help=f"Afegir franja fixa a {WEEKDAY_LABELS[weekday_idx]} {franja.lower()}",
                        ):
                            st.session_state.pop("selected_fixed_work_slot_edit", None)
                            st.session_state["selected_fixed_work_slot_cell"] = {
                                "weekday_name": weekday_name,
                                "weekday_label": WEEKDAY_LABELS[weekday_idx],
                                "franja": franja,
                            }
                            st.rerun()


def _render_selected_punctual_slot_editor(
    overrides_df: pd.DataFrame,
    existing_slots: list[str],
    template_overrides_path: Path,
    year: int,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    selected_punctual_edit = st.session_state.get("selected_punctual_work_slot_edit")
    if not selected_punctual_edit:
        return

    selected_day = date.fromisoformat(selected_punctual_edit["day"])
    edit_suffix = _edit_suffix(
        selected_punctual_edit,
        ["day", "franja", "slot_id", "presentiality", "work_mode"],
    )
    st.markdown(
        f"**Editar canvi puntual:** {selected_day.strftime('%Y-%m-%d')} · "
        f"{selected_punctual_edit['franja'].lower()}"
    )
    p_edit_col1, p_edit_col2, p_edit_col3, p_edit_col4 = st.columns(
        [1, 0.9, 1.4, 1]
    )
    with p_edit_col1:
        edited_punctual_day = st.date_input(
            "Dia",
            value=selected_day,
            min_value=date(year, 1, 1),
            max_value=date(year, 12, 31),
            format="DD/MM/YYYY",
            key=f"punctual_edit_day_{edit_suffix}",
        )
    (edited_punctual_franja, edited_punctual_slot,
     edited_punctual_presentiality) = _render_franja_slot_pres_selectors(
        p_edit_col2, p_edit_col3, p_edit_col4, selected_punctual_edit, edit_suffix,
        existing_slots, "punctual_edit",
    )
    # NOU MODEL: el work_mode no és editable; el solver el decideix.
    edited_punctual_work_mode = _DEFAULT_WORK_MODE
    edited_punctual_required_staff = 1

    p_edit_actions = st.columns(3)
    with p_edit_actions[0]:
        if st.button(
            "Guardar canvi",
            disabled=not edited_punctual_slot,
            width="stretch",
            key=f"save_punctual_edit_{edit_suffix}",
        ):
            old_values = (
                selected_punctual_edit["day"],
                selected_punctual_edit["franja"],
                selected_punctual_edit["slot_id"],
                selected_punctual_edit["presentiality"],
                selected_punctual_edit["work_mode"],
                int(selected_punctual_edit.get("required_staff", 1)),
            )
            edited_punctual_day_key = pd.Timestamp(edited_punctual_day).strftime("%Y-%m-%d")
            new_values = (
                edited_punctual_day_key,
                edited_punctual_franja,
                edited_punctual_slot,
                edited_punctual_presentiality,
                edited_punctual_work_mode,
                int(edited_punctual_required_staff),
            )
            if new_values != old_values:
                overrides_df = add_template_override(
                    overrides_df,
                    selected_punctual_edit["day"],
                    selected_punctual_edit["franja"],
                    selected_punctual_edit["slot_id"],
                    selected_punctual_edit["presentiality"],
                    selected_punctual_edit["work_mode"],
                    "remove",
                )
                overrides_df = add_template_override(
                    overrides_df,
                    edited_punctual_day_key,
                    edited_punctual_franja,
                    edited_punctual_slot,
                    edited_punctual_presentiality,
                    edited_punctual_work_mode,
                    "add",
                    required_staff=int(edited_punctual_required_staff),
                )
                save_template_overrides(template_overrides_path, overrides_df)
                invalidate_after_work_slot_change()
            st.session_state.pop("selected_punctual_work_slot_edit", None)
            st.rerun()
    with p_edit_actions[1]:
        if st.button(
            "Eliminar franja d'aquest dia",
            width="stretch",
            key=f"delete_punctual_edit_{edit_suffix}",
        ):
            overrides_df = add_template_override(
                overrides_df,
                selected_punctual_edit["day"],
                selected_punctual_edit["franja"],
                selected_punctual_edit["slot_id"],
                selected_punctual_edit["presentiality"],
                selected_punctual_edit["work_mode"],
                "remove",
            )
            save_template_overrides(template_overrides_path, overrides_df)
            invalidate_after_work_slot_change()
            st.session_state.pop("selected_punctual_work_slot_edit", None)
            st.rerun()
    with p_edit_actions[2]:
        if st.button("Cancel·lar", width="stretch", key=f"cancel_punctual_edit_{edit_suffix}"):
            st.session_state.pop("selected_punctual_work_slot_edit", None)
            st.rerun()


def _render_selected_punctual_cell_editor(
    overrides_df: pd.DataFrame,
    existing_slots: list[str],
    template_overrides_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    selected_punctual_cell = st.session_state.get("selected_punctual_work_slot_cell")
    if not selected_punctual_cell:
        return

    selected_day = date.fromisoformat(selected_punctual_cell["day"])
    st.markdown(
        f"**Afegir canvi puntual:** {selected_day.strftime('%Y-%m-%d')} · "
        f"{selected_punctual_cell['franja'].lower()}"
    )
    p_col1, p_col2, p_col3 = st.columns([1.5, 1, 0.7])
    with p_col1:
        slot_choice = st.selectbox(
            "Màquina/slot",
            [""] + existing_slots,
            key="punctual_slot_choice",
            help="Tria un slot del catàleg (definits a Calendari base → Slots disponibles).",
        )
    # Default NO_PRESENCIAL si l'slot és secundari (linked_to d'algú).
    _secondary = _secondary_slots()
    _is_secondary = str(slot_choice).strip().upper() in _secondary
    _default_pres_idx = 1 if _is_secondary else 0
    with p_col2:
        presentiality_label = st.selectbox(
            "Presencialitat",
            ["Presencial", "No presencial"],
            index=_default_pres_idx,
            key=f"punctual_presentiality_{slot_choice}",
            help=(
                "Per defecte **No presencial** (màquina secundària)."
            ) if _is_secondary else None,
        )
    with p_col3:
        st.write("")
        st.write("")
        slot_to_add = str(slot_choice).strip().upper()
        if st.button("Afegir", disabled=not slot_to_add, width="stretch", key="punctual_add_slot"):
            overrides_df = add_template_override(
                overrides_df,
                selected_punctual_cell["day"],
                selected_punctual_cell["franja"],
                slot_to_add,
                "PRESENCIAL" if presentiality_label == "Presencial" else "NO_PRESENCIAL",
                _DEFAULT_WORK_MODE,
                "add",
                required_staff=1,
            )
            save_template_overrides(template_overrides_path, overrides_df)
            invalidate_after_work_slot_change()
            st.session_state.pop("selected_punctual_work_slot_cell", None)
            st.rerun()


def _render_punctual_month_calendar(
    year: int,
    calendar_month: int,
    base_calendar_path: Path,
    public_holidays_path: Path,
    templates_df: pd.DataFrame,
    overrides_df: pd.DataFrame,
    default_required: int = 1,
) -> None:
    non_working_days = non_working_days_for_calendar(int(year), base_calendar_path, public_holidays_path)
    cal = calendar.Calendar(firstweekday=0)
    st.markdown(f"**{CATALAN_MONTHS.get(int(calendar_month), calendar_month)} {year}**")
    header_cols = st.columns(7)
    for idx, label in enumerate(WEEKDAY_LABELS):
        header_cols[idx].markdown(f"**{label}**")

    if not overrides_df.empty:
        override_days = set(
            pd.to_datetime(overrides_df["day"], errors="coerce")
            .dt.strftime("%Y-%m-%d")
            .dropna()
        )
    else:
        override_days = set()

    for week in cal.monthdatescalendar(int(year), int(calendar_month)):
        week_cols = st.columns(7)
        for col_idx, current in enumerate(week):
            with week_cols[col_idx]:
                if current.month != int(calendar_month):
                    st.caption(" ")
                    continue
                day_key = current.strftime("%Y-%m-%d")
                is_non_working = day_key in non_working_days or current.weekday() >= 5
                has_overrides = day_key in override_days
                st.markdown(f"**{current.day}**" + (" ⚙" if has_overrides else ""))
                if is_non_working:
                    st.caption("No laborable")
                    continue
                for franja in FRANJA_OPTIONS:
                    with st.container(key=f"franjabox_{franja}_{day_key}"):
                        _render_franja_badge(franja)
                        day_slots = slots_for_day_with_overrides(templates_df, overrides_df, current)
                        day_slots = day_slots[day_slots["franja"].astype(str).str.upper() == franja].copy()
                        for slot_row in day_slots.itertuples(index=False):
                            row_doubled = int(getattr(slot_row, "doubled", 0) or 0)
                            n = default_required + (1 if row_doubled else 0)
                            slot_label = (
                                f"{slot_row.slot_id} · "
                                f"{slot_row.presentiality.replace('_', ' ').title()} · "
                                f"{'Peonada' if slot_row.work_mode == 'PEONADA' else 'Ordinària'}"
                                + (f" · {n} fac." if n > 1 else "")
                            )
                            edit_key = (
                                f"edit_punctual_{day_key}_{franja}_{slot_row.slot_id}_"
                                f"{slot_row.presentiality}_{slot_row.work_mode}"
                            )
                            if st.button(
                                slot_label,
                                key=edit_key,
                                width="stretch",
                                help="Clica per editar aquesta franja només d'aquest dia",
                            ):
                                st.session_state["selected_punctual_work_slot_edit"] = {
                                    "day": day_key,
                                    "franja": franja,
                                    "slot_id": str(slot_row.slot_id),
                                    "presentiality": str(slot_row.presentiality),
                                    "work_mode": str(slot_row.work_mode),
                                    "required_staff": n,
                                }
                                st.session_state.pop("selected_punctual_work_slot_cell", None)
                                st.rerun()
                        if st.button(
                            "+",
                            key=f"select_punctual_cell_{day_key}_{franja}",
                            width="stretch",
                            help=f"Afegir canvi puntual a {day_key} {franja.lower()}",
                        ):
                            st.session_state.pop("selected_punctual_work_slot_edit", None)
                            st.session_state["selected_punctual_work_slot_cell"] = {
                                "day": day_key,
                                "franja": franja,
                            }
                            st.rerun()
