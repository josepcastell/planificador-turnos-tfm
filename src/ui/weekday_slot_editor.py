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
    apply_fixed_franja,
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


_FREQ_LABELS = {
    1: "Cada setmana",
    2: "1 de cada 2 setmanes",
    3: "1 de cada 3 setmanes",
    4: "1 de cada 4 setmanes",
}


def _freq_offset_labels(interval: int, year: int, weekday_name: str) -> dict[int, str]:
    """Per a «1 de cada N»: etiqueta cada opció del cicle amb dates
    d'exemple reals de l'any, perquè l'usuari triï QUINES setmanes."""
    import datetime as _dt
    if interval <= 1:
        return {0: ""}
    wd_idx = (
        WEEKDAY_TEMPLATE_COLUMNS.index(weekday_name)
        if weekday_name in WEEKDAY_TEMPLATE_COLUMNS else 0
    )
    out: dict[int, str] = {}
    for off in range(interval):
        examples = []
        d = _dt.date(year, 1, 1)
        while d.weekday() != wd_idx:
            d += _dt.timedelta(days=1)
        while len(examples) < 3 and d.year == year:
            if d.isocalendar()[1] % interval == off:
                examples.append(d.strftime("%d/%m"))
            d += _dt.timedelta(days=7)
        out[off] = "setmanes del " + ", ".join(examples) + "…"
    return out


def _render_freq_selectors(year: int, weekday_name: str, key_prefix: str,
                           current_interval: int = 1, current_offset: int = 0):
    """Selectors «Freqüència» + «Quines setmanes». Retorna (interval, offset)."""
    col_freq, col_off = st.columns(2)
    with col_freq:
        interval = st.selectbox(
            "Freqüència",
            options=list(_FREQ_LABELS),
            index=list(_FREQ_LABELS).index(
                current_interval if current_interval in _FREQ_LABELS else 1
            ),
            format_func=lambda v: _FREQ_LABELS[v],
            key=f"{key_prefix}_freq",
            help="«1 de cada N»: la franja només existeix les setmanes "
                 "triades del cicle (setmana ISO). Cada setmana = sempre.",
        )
    offset = 0
    if interval > 1:
        labels = _freq_offset_labels(interval, year, weekday_name)
        with col_off:
            offset = st.selectbox(
                "Quines setmanes",
                options=list(labels),
                index=min(current_offset, interval - 1),
                format_func=lambda v: labels[v],
                key=f"{key_prefix}_freqoff",
            )
    return int(interval), int(offset)


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
        "Patró setmanal d'activitats. Clica una activitat per editar-la o «+» per "
        "afegir-ne una de nova. **👥** = doblada (la fan dues persones) · "
        "**punt de color** (🔴🟠🟡🟢🔵…) = vinculada: cada **bloc** de "
        "activitats vinculades té el seu propi color, igual a tots els dies on "
        "apareix el bloc (fins a 16 marques: cercles i després quadrats; amb "
        "més blocs es repeteixen). Per **vincular** o **doblar** activitats, "
        "fes servir els desplegables de sota del calendari."
    )
    _render_selected_fixed_slot_editor(
        templates_df,
        existing_slots,
        weekly_templates_path,
        invalidate_after_work_slot_change,
        year,
    )
    _render_selected_fixed_cell_editor(
        templates_df,
        existing_slots,
        weekly_templates_path,
        invalidate_after_work_slot_change,
        year,
    )
    _render_fixed_weekly_calendar(templates_df, default_required)
    st.divider()
    _render_linked_groups_editor(
        templates_df,
        weekly_templates_path,
        invalidate_after_work_slot_change,
    )
    _render_doubled_editor(
        templates_df,
        weekly_templates_path,
        invalidate_after_work_slot_change,
    )


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
    adding: bool = False,
):
    """Selectors COMUNS (Franja, Màquina, Presencialitat) dels formularis
    d'AFEGIR i d'EDITAR, tant de franges fixes com de canvis puntuals: els
    mateixos camps amb les mateixes etiquetes. En afegir, la màquina comença
    buida i la presencialitat per defecte és no presencial si la màquina és
    secundària d'alguna altra. Retorna (franja, slot, presentiality)."""
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
        current_slot = str(selected.get("slot_id", "") or "").strip().upper()
        slot_options = ([""] if adding else []) + list(existing_slots)
        if current_slot and current_slot not in slot_options:
            slot_options = [current_slot, *slot_options]
        slot = st.selectbox(
            "Activitat",
            options=slot_options,
            index=slot_options.index(current_slot) if current_slot in slot_options else 0,
            key=f"{key_prefix}_slot_{edit_suffix}",
            help="Una activitat del catàleg (pestanya Activitat).",
        ).strip().upper()
    with col_pres:
        if adding:
            default = "NO_PRESENCIAL" if slot in _secondary_slots() else "PRESENCIAL"
            pres_key = f"{key_prefix}_presentiality_{edit_suffix}_{slot}"
        else:
            default = selected["presentiality"]
            pres_key = f"{key_prefix}_presentiality_{edit_suffix}"
        presentiality = st.selectbox(
            "Presencialitat",
            PRESENTIALITY_OPTIONS,
            index=0 if default == "PRESENCIAL" else 1,
            key=pres_key,
            format_func=lambda value: value.replace("_", " ").title(),
        )
    return franja, slot, presentiality


_FIXED_FORM_HELP = (
    "Les **vinculacions** i les màquines **doblades** es fan des dels "
    "desplegables de sota del calendari. En editar una activitat, es "
    "conserven."
)


def _render_fixed_franja_form(
    existing_slots: list[str], year: int, prefill: dict, suffix: str, adding: bool,
) -> dict:
    """Camps COMUNS dels formularis d'afegir i d'editar una franja fixa
    (abans cada un en mostrava uns altres). Retorna els valors amb els noms
    que espera `apply_fixed_franja`."""
    st.caption(_FIXED_FORM_HELP)
    c_day, c_fr, c_slot, c_pres = st.columns([1, 0.9, 1.4, 1])
    with c_day:
        weekday = st.selectbox(
            "Dia",
            WEEKDAY_TEMPLATE_COLUMNS,
            index=(
                WEEKDAY_TEMPLATE_COLUMNS.index(prefill["weekday_name"])
                if prefill["weekday_name"] in WEEKDAY_TEMPLATE_COLUMNS
                else 0
            ),
            key=f"fixed_form_weekday_{suffix}",
            format_func=lambda value: WEEKDAY_LABELS[WEEKDAY_TEMPLATE_COLUMNS.index(value)],
        )
    franja, slot, presentiality = _render_franja_slot_pres_selectors(
        c_fr, c_slot, c_pres, prefill, suffix, existing_slots, "fixed_form",
        adding=adding,
    )
    interval, offset = _render_freq_selectors(
        year, weekday, f"fixed_form_freq_{suffix}",
        current_interval=int(prefill.get("week_interval", 1)),
        current_offset=int(prefill.get("week_offset", 0)),
    )
    # Vinculació i doblada no són del formulari (desplegables de sota):
    # en editar es conserven si la màquina es queda al mateix dia i franja.
    same_cell = (weekday, franja, slot) == (
        prefill["weekday_name"], prefill["franja"],
        str(prefill.get("slot_id", "") or "").strip().upper(),
    )
    return {
        "weekday_name": weekday, "franja": franja, "slot_id": slot,
        "presentiality": presentiality,
        "linked_to": str(prefill.get("linked_to", "") or "") if same_cell else "",
        "doubled": bool(prefill.get("doubled", False)),
        "week_interval": interval, "week_offset": offset,
    }


def _fixed_form_error(values: dict) -> str | None:
    if not values["slot_id"]:
        return "Tria l'activitat."
    return None


def _render_selected_fixed_slot_editor(
    templates_df: pd.DataFrame,
    existing_slots: list[str],
    weekly_templates_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
    year: int = 2026,
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
    # Valors actuals de la franja (mateixos camps que el formulari d'afegir).
    _wd = selected_fixed_edit["weekday_name"]
    _fr = selected_fixed_edit["franja"]
    _sid = selected_fixed_edit["slot_id"]
    _cell = templates_df[
        (templates_df["weekday_name"].astype(str) == str(_wd))
        & (templates_df["franja"].astype(str) == str(_fr))
        & (templates_df["slot_id"].astype(str).str.strip().str.upper()
           == str(_sid).strip().upper())
    ]
    _cur_int, _cur_off = 1, 0
    if not _cell.empty:
        if "week_interval" in _cell.columns:
            _cur_int = int(pd.to_numeric(_cell["week_interval"], errors="coerce").fillna(1).iloc[0])
        if "week_offset" in _cell.columns:
            _cur_off = int(pd.to_numeric(_cell["week_offset"], errors="coerce").fillna(0).iloc[0])
    _link = _link_partner_for_template_cell(templates_df, _wd, _fr, _sid)
    if _link and _link not in work_slots_for_weekday_and_franja(
        templates_df, _wd, _fr,
    )["slot_id"].astype(str).str.strip().str.upper().tolist():
        _link = ""  # apuntava a una màquina que ja no hi és: no la recreem
    prefill = {
        **selected_fixed_edit,
        "linked_to": _link,
        "doubled": {"PRESENCIAL", "NO_PRESENCIAL"}.issubset(
            set(_cell["presentiality"].astype(str).str.upper())
        ),
        "week_interval": _cur_int,
        "week_offset": _cur_off,
    }
    values = _render_fixed_franja_form(
        existing_slots, year, prefill, f"edit_{edit_suffix}", adding=False,
    )

    edit_actions = st.columns(3)
    with edit_actions[0]:
        if st.button(
            "Desar canvi",
            disabled=not values["slot_id"],
            width="stretch",
            key=f"save_fixed_edit_{edit_suffix}",
        ):
            error = _fixed_form_error(values)
            if error:
                st.error(error)
            else:
                templates_df = apply_fixed_franja(
                    templates_df, **values, work_mode=_DEFAULT_WORK_MODE,
                    original={
                        k: selected_fixed_edit[k]
                        for k in ("weekday_name", "franja", "slot_id",
                                  "presentiality", "work_mode")
                    },
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
    """Slot_ids "màquina secundària" (font única:
    slot_catalog.secondary_slot_ids_effective — templates primer, catàleg
    com a fallback). S'autodefaulteja a NO_PRESENCIAL al template."""
    from src.services.slot_catalog import secondary_slot_ids_effective
    return secondary_slot_ids_effective()


def _slots_for(
    templates_df: pd.DataFrame, weekday_name: str, franja: str,
    presential_only: bool = False,
) -> list[str]:
    """Màquines presents en un (dia-setmana, franja) concret del template
    (només les presencials si `presential_only`)."""
    if templates_df is None or templates_df.empty:
        return []
    wd = str(weekday_name).strip().upper()
    fr = str(franja).strip().upper()
    df = templates_df
    mask = (
        (df["weekday_name"].fillna("").astype(str).str.strip().str.upper() == wd)
        & (df["franja"].fillna("").astype(str).str.strip().str.upper() == fr)
    )
    if presential_only:
        mask &= (
            df["presentiality"].fillna("").astype(str).str.strip().str.upper()
            == "PRESENCIAL"
        )
    return sorted(
        {
            str(s).strip().upper()
            for s in df.loc[mask, "slot_id"].fillna("")
            if str(s).strip()
        }
    )


def _render_linked_groups_editor(
    templates_df: pd.DataFrame,
    weekly_templates_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    """Vinculador de BLOCS de màquines per (dia-setmana, franja): permet
    definir-ne **més d'un** i és local a cada dia/franja (un dia poden estar
    vinculades i un altre no). Cada bloc = una sola persona cobreix totes les
    màquines del bloc i **compten com 1**. Diferent de doblar (1 màquina, 2
    persones)."""
    from src.services.slot_catalog import (
        clear_linked_group_in_template,
        linked_groups_in_template,
        set_linked_group_in_template,
    )

    with st.expander(
        "🔗 Vincular activitats en blocs",
        expanded=False,
    ):
        st.caption(
            "Vincula diverses activitats que fa la **mateixa persona** en "
            "aquest dia i franja: el solver hi posa el mateix facultatiu i "
            "**compten com 1** activitat (presencial si alguna ho és). Pots "
            "definir **tants blocs com vulguis**, cada un amb **tantes "
            "activitats com calgui**, presencials o no, i és **per (dia, "
            "franja)** — un dia poden estar vinculades i un altre no. Cada "
            "bloc es marca amb un **punt de color** al calendari. És diferent "
            "de **doblar** (doblar = 1 activitat, 2 persones)."
        )
        c_day, c_fr = st.columns(2)
        with c_day:
            wd = st.selectbox(
                "Dia",
                WEEKDAY_TEMPLATE_COLUMNS,
                key="linkgrp_wd",
                format_func=lambda v: WEEKDAY_LABELS[
                    WEEKDAY_TEMPLATE_COLUMNS.index(v)
                ],
            )
        with c_fr:
            fr = st.selectbox(
                "Franja",
                FRANJA_OPTIONS,
                key="linkgrp_fr",
                format_func=lambda v: FRANJA_LABELS[v],
            )

        groups = linked_groups_in_template(templates_df, wd, fr)
        if groups:
            dot_by_group, _ = _link_dot_maps(templates_df)
            for gi, g in enumerate(groups):
                col1, col2 = st.columns([5, 1])
                _dot = dot_by_group.get(tuple(sorted(g)), "🔗")
                col1.markdown(f"{_dot} " + "  +  ".join(g))
                if col2.button(
                    "Desvincular",
                    key=f"linkgrp_rm_{wd}_{fr}_{gi}",
                    width="stretch",
                ):
                    new_df = clear_linked_group_in_template(
                        templates_df, wd, fr, g[0]
                    )
                    save_weekly_slot_templates(new_df, weekly_templates_path)
                    invalidate_after_work_slot_change()
                    st.toast("Bloc desvinculat", icon="🔓")
                    st.rerun()
        else:
            st.caption("Cap bloc en aquest dia i franja.")

        present = _slots_for(templates_df, wd, fr)
        if len(present) < 2:
            st.info(
                "Calen com a mínim 2 activitats en aquest dia i franja per "
                "poder vincular-les."
            )
            return
        sel = st.multiselect(
            "Activitats del bloc",
            options=present,
            key=f"linkgrp_sel_{wd}_{fr}",
            help="Tria 2 o més activitats (presencials o no presencials).",
            placeholder="Tria 2 o més activitats",
        )
        # Representant del bloc: una presencial, si n'hi ha.
        presential = set(_slots_for(templates_df, wd, fr, presential_only=True))
        sel = sorted(sel, key=lambda s: (s not in presential, present.index(s)))
        if st.button(
            "Vincular com a bloc",
            type="primary",
            disabled=len(sel) < 2,
            key=f"linkgrp_add_{wd}_{fr}",
        ):
            new_df = set_linked_group_in_template(templates_df, wd, fr, sel)
            save_weekly_slot_templates(new_df, weekly_templates_path)
            invalidate_after_work_slot_change()
            st.toast("Bloc vinculat", icon="🔗")
            st.rerun()


def _render_doubled_editor(
    templates_df: pd.DataFrame,
    weekly_templates_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
) -> None:
    """Màquines DOBLADES per (dia-setmana, franja): la mateixa màquina la
    fan dues persones, una presencial i una no presencial. Abans es marcava
    al formulari de cada màquina; ara, com les vinculacions, aquí sota."""
    from src.services.slot_templates import (
        doubled_slots_in_template,
        set_doubled_in_template,
    )

    with st.expander("👥 Doblar activitats", expanded=False):
        st.caption(
            "Una activitat **doblada** la fan **dues persones** el mateix dia i "
            "franja: una **presencial** i una **no presencial**. És **per "
            "(dia, franja)** i es marca amb **👥** al calendari. És diferent "
            "de **vincular** (vincular = diverses activitats, 1 persona)."
        )
        c_day, c_fr = st.columns(2)
        with c_day:
            wd = st.selectbox(
                "Dia",
                WEEKDAY_TEMPLATE_COLUMNS,
                key="dblgrp_wd",
                format_func=lambda v: WEEKDAY_LABELS[
                    WEEKDAY_TEMPLATE_COLUMNS.index(v)
                ],
            )
        with c_fr:
            fr = st.selectbox(
                "Franja",
                FRANJA_OPTIONS,
                key="dblgrp_fr",
                format_func=lambda v: FRANJA_LABELS[v],
            )

        def _save(new_df: pd.DataFrame, msg: str, icon: str) -> None:
            save_weekly_slot_templates(new_df, weekly_templates_path)
            invalidate_after_work_slot_change()
            st.toast(msg, icon=icon)
            st.rerun()

        doubled = doubled_slots_in_template(templates_df, wd, fr)
        if doubled:
            for sid in doubled:
                col1, col2 = st.columns([5, 1])
                col1.markdown(f"👥 {sid}  (presencial + no presencial)")
                if col2.button(
                    "Desdoblar", key=f"dblgrp_rm_{wd}_{fr}_{sid}", width="stretch",
                    help="Treu la instància no presencial; es queda la presencial.",
                ):
                    _save(
                        set_doubled_in_template(templates_df, wd, fr, sid, False),
                        f"{sid} desdoblada", "➖",
                    )
        else:
            st.caption("Cap activitat doblada en aquest dia i franja.")

        options = [s for s in _slots_for(templates_df, wd, fr) if s not in doubled]
        if not options:
            st.info("No hi ha cap altra activitat en aquest dia i franja per doblar.")
            return
        sel = st.multiselect(
            "Activitats a doblar",
            options=options,
            key=f"dblgrp_sel_{wd}_{fr}",
            placeholder="Tria una o més activitats",
        )
        if st.button(
            "Doblar", type="primary", disabled=not sel, key=f"dblgrp_add_{wd}_{fr}",
        ):
            new_df = templates_df
            for sid in sel:
                new_df = set_doubled_in_template(new_df, wd, fr, sid, True)
            _save(new_df, f"Doblada: {', '.join(sel)}", "👥")


def _render_selected_fixed_cell_editor(
    templates_df: pd.DataFrame,
    existing_slots: list[str],
    weekly_templates_path: Path,
    invalidate_after_work_slot_change: Callable[[], None],
    year: int = 2026,
) -> None:
    selected_fixed_cell = st.session_state.get("selected_fixed_work_slot_cell")
    if not selected_fixed_cell:
        return

    st.markdown(
        f"**Afegir franja fixa:** {selected_fixed_cell['weekday_label']} · "
        f"{selected_fixed_cell['franja'].lower()}"
    )
    prefill = {
        "weekday_name": selected_fixed_cell["weekday_name"],
        "franja": selected_fixed_cell["franja"],
        "slot_id": "", "presentiality": "PRESENCIAL", "linked_to": "",
        "doubled": False, "week_interval": 1, "week_offset": 0,
    }
    suffix = f"add_{selected_fixed_cell['weekday_name']}_{selected_fixed_cell['franja']}"
    values = _render_fixed_franja_form(existing_slots, year, prefill, suffix, adding=True)

    add_actions = st.columns(3)
    with add_actions[0]:
        if st.button(
            "Afegir",
            disabled=not values["slot_id"],
            width="stretch",
            key="fixed_calendar_add_slot",
        ):
            error = _fixed_form_error(values)
            if error:
                st.error(error)
            else:
                templates_df = apply_fixed_franja(
                    templates_df, **values, work_mode=_DEFAULT_WORK_MODE,
                )
                save_weekly_slot_templates(templates_df, weekly_templates_path)
                invalidate_after_work_slot_change()
                st.session_state.pop("selected_fixed_work_slot_cell", None)
                st.rerun()
    with add_actions[2]:
        if st.button("Cancel·lar", width="stretch", key="cancel_fixed_add"):
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


# 16 marques: primer cercles i després quadrats dels mateixos colors.
_LINK_DOTS = (
    "🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤", "⚫",
    "🟥", "🟧", "🟨", "🟩", "🟦", "🟪", "🟫", "⬛",
)


def _link_dot_maps(
    templates_df: pd.DataFrame,
) -> tuple[dict[tuple, str], dict[tuple[str, str, str], str]]:
    """Assigna un PUNT DE COLOR propi a cada bloc de màquines vinculades:
    mateixos membres = mateix color a tots els dies; blocs diferents =
    colors diferents (fins a 16, després es reciclen). Retorna:
      · dot_by_group: {tuple(membres ordenats) → punt}
      · dot_by_slot: {(weekday_name, franja, slot_id) → punt}"""
    from src.services.slot_catalog import linked_groups_in_template
    groups_by_wf: dict[tuple[str, str], list[list[str]]] = {}
    all_groups: set[tuple] = set()
    for wd in WEEKDAY_TEMPLATE_COLUMNS:
        for fr in FRANJA_OPTIONS:
            gs = linked_groups_in_template(templates_df, wd, fr)
            groups_by_wf[(wd, fr)] = gs
            for g in gs:
                all_groups.add(tuple(sorted(g)))
    dot_by_group = {
        g: _LINK_DOTS[i % len(_LINK_DOTS)]
        for i, g in enumerate(sorted(all_groups))
    }
    dot_by_slot: dict[tuple[str, str, str], str] = {}
    for (wd, fr), gs in groups_by_wf.items():
        for g in gs:
            dot = dot_by_group[tuple(sorted(g))]
            for m in g:
                dot_by_slot[(wd, fr, str(m).strip().upper())] = dot
    return dot_by_group, dot_by_slot


def _render_franja_button(
    weekday_name: str,
    weekday_idx: int,
    franja: str,
    slot_row,
    pres_abbr: str,
    is_doubled: bool,
    is_linked: bool = False,
    link_partner: str | None = None,
    link_dot: str = "🔗",
) -> None:
    """Renderitza el botó d'edició d'una franja fixa amb marcadors
    visuals al label per a slots doblats (👥) i/o vinculats (punt de
    color PROPI de cada bloc). La llegenda s'explica fora de les franges
    (vegeu `render_weekday_work_slot_editor`)."""
    prefix = ""
    if is_doubled and is_linked:
        prefix = f"👥{link_dot} "
    elif is_doubled:
        prefix = "👥 "
    elif is_linked:
        prefix = f"{link_dot} "
    slot_label = f"{prefix}{slot_row.slot_id} · {pres_abbr}"
    extra = []
    if is_doubled:
        extra.append("doblada: dues persones")
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
    # Punt de color propi per a cada bloc vinculat (mateix bloc = mateix
    # color a tots els dies).
    _, dot_by_slot = _link_dot_maps(templates_df)
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
                                link_dot=dot_by_slot.get(
                                    (weekday_name, franja, sid), "🔗",
                                ),
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
            "Desar canvi",
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
    # Mateixos camps que el formulari d'editar un canvi puntual.
    suffix = f"add_{selected_punctual_cell['day']}_{selected_punctual_cell['franja']}"
    p_col1, p_col2, p_col3, p_col4 = st.columns([1, 0.9, 1.4, 1])
    with p_col1:
        add_day = st.date_input(
            "Dia",
            value=selected_day,
            min_value=date(selected_day.year, 1, 1),
            max_value=date(selected_day.year, 12, 31),
            format="DD/MM/YYYY",
            key=f"punctual_form_day_{suffix}",
        )
    add_franja, slot_to_add, add_presentiality = _render_franja_slot_pres_selectors(
        p_col2, p_col3, p_col4,
        {"franja": selected_punctual_cell["franja"], "slot_id": ""},
        suffix, existing_slots, "punctual_form", adding=True,
    )
    p_actions = st.columns(3)
    with p_actions[0]:
        if st.button("Afegir", disabled=not slot_to_add, width="stretch", key="punctual_add_slot"):
            overrides_df = add_template_override(
                overrides_df,
                pd.Timestamp(add_day).strftime("%Y-%m-%d"),
                add_franja,
                slot_to_add,
                add_presentiality,
                _DEFAULT_WORK_MODE,
                "add",
                required_staff=1,
            )
            save_template_overrides(template_overrides_path, overrides_df)
            invalidate_after_work_slot_change()
            st.session_state.pop("selected_punctual_work_slot_cell", None)
            st.rerun()
    with p_actions[2]:
        if st.button("Cancel·lar", width="stretch", key="cancel_punctual_add"):
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
