"""Desplegables ràpids sota el render del calendari (pestanya Calendari).

Dos models, segons l'acció:

  • Afegir absència / Afegir guàrdia  → ESCRIUEN a les dades
    (data/absences, data/guards). Creen un FORAT de cobertura que ha de
    resoldre el SOLVER: en clicar «Generar», el solver hi posa un altre
    facultatiu intentant mantenir el calendari equilibrat.

  • Canvi puntual / Ordinària↔peonada / Canvi de presencialitat →
    EDICIÓ DIRECTA del calendari generat (`outputs/schedule_weekday.csv`)
    + re-render a l'instant, sense passar pel solver. Són decisions
    manuals deliberades que no creen forats (tries el facultatiu /
    marques un extra / gires PRES↔NP). NO sobreviuen a una nova «Generació».
"""
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import ABSENCE_TYPES
from src.domain.schedule_format import is_review_slot

_SCHEDULE_PATH = Path("outputs/schedule_weekday.csv")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _profs(all_professional_options) -> list[str]:
    return sorted(
        p for p in (all_professional_options or [])
        if str(p).strip().upper() not in ("", "NONE", "NAN")
    )


def _default_day(year: int, month: int) -> date:
    try:
        return date(year, month, 1)
    except ValueError:
        return date.today()


def _append_row(path: Path, header_cols: list[str], row: dict) -> None:
    """Afegeix una fila a un CSV de dades, creant-lo amb capçalera si cal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path)
    else:
        df = pd.DataFrame(columns=header_cols)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    for c in header_cols:
        if c not in df.columns:
            df[c] = ""
    df = df[header_cols + [c for c in df.columns if c not in header_cols]]
    df.to_csv(path, index=False)


def _load_schedule() -> pd.DataFrame | None:
    if not _SCHEDULE_PATH.exists() or _SCHEDULE_PATH.stat().st_size == 0:
        return None
    try:
        return pd.read_csv(_SCHEDULE_PATH, dtype=str).fillna("")
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return None


def _save_and_rerender(
    df: pd.DataFrame, professionals_path: Path, pdf_output_dir: Path,
    year: int, selected_months: list[int], toast_msg: str,
) -> None:
    """Desa el calendari editat DIRECTAMENT, re-renderitza el PDF i refresca."""
    df.to_csv(_SCHEDULE_PATH, index=False)
    from src.ui.planning_calendar_tabs import export_general_weekday_pdf
    export_general_weekday_pdf(
        _SCHEDULE_PATH, professionals_path, pdf_output_dir, year, selected_months,
    )
    st.session_state.pop("weekday_live_schedule", None)
    st.toast(toast_msg, icon="✅")
    st.rerun()


def _row_label(row) -> str:
    return f"{row['day']} · {row['franja']} · {row['slot_id']}  ({row.get('professional', '')})"


def _reajust_button(
    reajustar: Callable[[str], None] | None, key: str, what: str,
) -> None:
    """Botó de reajust amb MÍNIMS CANVIS dins el desplegable d'absència/
    guàrdia. Reresol el calendari conservant al màxim les assignacions
    actuals (estabilitat soft): només mou el necessari per cobrir el forat
    que acabes de crear, sense regenerar-ho tot des de zero.

    `reajustar(label)` l'injecta `app.py` (crida `run_weekday_regenerate`
    amb el calendari actual com a punt de partida i fa `st.rerun()`)."""
    if reajustar is None:
        return
    exists = _SCHEDULE_PATH.exists() and _SCHEDULE_PATH.stat().st_size > 0
    if st.button(
        "🔧 Reajustar (mínims canvis)",
        key=key,
        width="stretch",
        type="primary",
        disabled=not exists,
        help=(
            "Reresol conservant al màxim el calendari actual: només mou el "
            "necessari per cobrir el forat. Més ràpid i estable que «Generar» "
            "(que recomença de zero)."
        ) if exists else "Genera primer el calendari per poder reajustar.",
    ):
        reajustar(f"Reajustar ({what})")


# ─────────────────────────────────────────────────────────────────────────────
# 1) Afegir absència  → escriu a dades; el solver omple el forat en Generar
# ─────────────────────────────────────────────────────────────────────────────
def _quick_add_absence(absences_path: Path, profs, year, month, reajustar=None) -> None:
    with st.expander("➕ Afegir absència", expanded=False):
        st.caption(
            "Registra una absència i prem **Reajustar (mínims canvis)** aquí "
            "sota: el solver cobrirà el forat amb un altre facultatiu movent "
            "el mínim possible (no cal «Generar» de nou)."
        )
        with st.form("qa_absence_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            prof = c1.selectbox("Facultatiu", profs, key="qa_abs_prof")
            atype = c2.selectbox("Tipus", ABSENCE_TYPES, key="qa_abs_type")
            c3, c4 = st.columns(2)
            d_ini = c3.date_input("Data inici", value=_default_day(year, month), key="qa_abs_ini")
            d_fi = c4.date_input("Data fi", value=_default_day(year, month), key="qa_abs_fi")
            notes = st.text_input("Notes (opcional)", key="qa_abs_notes")
            submitted = st.form_submit_button("Afegir absència", width="stretch")
        if submitted:
            if d_fi < d_ini:
                st.error("La data fi no pot ser anterior a la d'inici.")
                return
            _append_row(
                absences_path,
                ["absence_type", "professional_id", "start_day", "end_day", "notes"],
                {
                    "absence_type": atype, "professional_id": prof,
                    "start_day": d_ini.isoformat(), "end_day": d_fi.isoformat(),
                    "notes": notes,
                },
            )
            st.toast(
                f"Absència afegida: {prof} ({atype}) {d_ini}→{d_fi}. "
                "Prem **Reajustar (mínims canvis)** perquè el solver ompli "
                "el forat.",
                icon="✅",
            )
            st.rerun()
        _reajust_button(reajustar, "qa_abs_reajust", "absència")


# ─────────────────────────────────────────────────────────────────────────────
# 2) Afegir guàrdia  → escriu a dades; el solver reassigna en Generar
# ─────────────────────────────────────────────────────────────────────────────
def _quick_add_guard(guards_path: Path, profs, year, month, reajustar=None) -> None:
    with st.expander("➕ Afegir guàrdia", expanded=False):
        st.caption(
            "Registra una guàrdia (genera postguàrdia l'endemà) i prem "
            "**Reajustar (mínims canvis)** aquí sota: el solver reassignarà "
            "les màquines alliberades movent el mínim possible."
        )
        with st.form("qa_guard_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            g_day = c1.date_input("Dia de la guàrdia", value=_default_day(year, month), key="qa_guard_day")
            prof = c2.selectbox("Facultatiu", profs, key="qa_guard_prof")
            notes = st.text_input("Notes (opcional)", key="qa_guard_notes")
            submitted = st.form_submit_button("Afegir guàrdia", width="stretch")
        if submitted:
            _append_row(
                guards_path,
                ["day", "professional_id", "guard_kind", "notes"],
                {
                    "day": g_day.isoformat(), "professional_id": prof,
                    "guard_kind": "guardia", "notes": notes,
                },
            )
            st.toast(
                f"Guàrdia afegida: {prof} el {g_day}. Prem **Reajustar "
                "(mínims canvis)** perquè el solver reassigni.",
                icon="✅",
            )
            st.rerun()
        _reajust_button(reajustar, "qa_guard_reajust", "guàrdia")


# ─────────────────────────────────────────────────────────────────────────────
# 3) Canvi puntual d'assignació  → edició directa
# ─────────────────────────────────────────────────────────────────────────────
def _quick_add_assignment_change(profs, year, professionals_path, pdf_output_dir, selected_months) -> None:
    with st.expander("➕ Afegir canvi puntual d'assignació", expanded=False):
        st.caption("Canvi manual immediat (sense solver): tries tu el facultatiu.")
        df = _load_schedule()
        if df is None or df.empty:
            st.info("Genera primer el calendari per canviar assignacions.")
            return
        if not {"day", "franja", "slot_id", "professional"}.issubset(df.columns):
            st.info("El calendari generat no té el format esperat.")
            return
        labels = {f"{i}: " + _row_label(r): i for i, r in df.iterrows()}
        with st.form("qa_change_form", clear_on_submit=True):
            label = st.selectbox("Assignació a canviar", list(labels.keys()), key="qa_chg_slot")
            new_prof = st.selectbox("Nou facultatiu", [""] + profs, key="qa_chg_prof")
            submitted = st.form_submit_button("Aplicar canvi al calendari", width="stretch")
        if submitted:
            idx = labels[label]
            old = df.at[idx, "professional"]
            df.at[idx, "professional"] = new_prof
            _save_and_rerender(
                df, professionals_path, pdf_output_dir, year, selected_months,
                f"Canvi aplicat: {df.at[idx, 'slot_id']} el {df.at[idx, 'day']} "
                f"({old or '—'} → {new_prof or '—'}).",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4) Ordinària ↔ peonada  → edició directa (bidireccional)
# ─────────────────────────────────────────────────────────────────────────────
def _quick_toggle_peonada(year, professionals_path, pdf_output_dir, selected_months) -> None:
    with st.expander("🔄 Canviar ordinària ↔ peonada", expanded=False):
        st.caption(
            "Marca manual immediata (sense solver): converteix una NP "
            "ordinària en peonada (extra) o torna una peonada a ordinària."
        )
        df = _load_schedule()
        if df is None or df.empty:
            st.info("Genera primer el calendari per marcar peonades.")
            return
        needed = {"day", "franja", "slot_id", "professional", "presentiality", "work_mode"}
        if not needed.issubset(set(df.columns)):
            st.info("El calendari generat no té el format esperat.")
            return
        slotU = df["slot_id"].str.strip().str.upper()
        wmU = df["work_mode"].str.strip().str.upper()
        presU = df["presentiality"].str.strip().str.upper()
        has_prof = df["professional"].str.strip() != ""
        occ = df.groupby(["day", "franja", "slot_id"])["professional"].transform("size")
        is_peonada = wmU == "PEONADA"
        # Ordinària → peonada: NP, no peonada, un sol facultatiu, no revisió.
        # is_review_slot: la revisió es determina pel CATÀLEG (review=1), mai
        # per la substring "REV" al nom (falsos positius/negatius).
        ord_to_peo = (
            (presU == "NO_PRESENCIAL")
            & ~is_peonada
            & has_prof
            & (~slotU.map(is_review_slot))
            & (occ == 1)
        )
        # Peonada → ordinària: qualsevol fila ja marcada com a peonada.
        peo_to_ord = is_peonada & has_prof
        elig = df[ord_to_peo | peo_to_ord]
        if elig.empty:
            st.info(
                "No hi ha assignacions elegibles (NP ordinària d'un sol "
                "facultatiu i no revisió, o peonades existents)."
            )
            return

        def _lab(i, r):
            direction = (
                "peonada→ordinària"
                if str(r["work_mode"]).strip().upper() == "PEONADA"
                else "ordinària→peonada"
            )
            return (f"{i}: {r['day']} · {r['franja']} · {r['slot_id']} "
                    f"({r['professional']})  [{direction}]")

        labels = {_lab(i, r): i for i, r in elig.iterrows()}
        with st.form("qa_peonada_form", clear_on_submit=True):
            label = st.selectbox(
                "Assignació a convertir", list(labels.keys()), key="qa_peo_slot",
            )
            submitted = st.form_submit_button("Convertir", width="stretch")
        if submitted:
            idx = labels[label]
            to_peonada = str(df.at[idx, "work_mode"]).strip().upper() != "PEONADA"
            df.at[idx, "work_mode"] = "PEONADA" if to_peonada else "NORMAL"
            verb = "Ordinària → peonada" if to_peonada else "Peonada → ordinària"
            _save_and_rerender(
                df, professionals_path, pdf_output_dir, year, selected_months,
                f"{verb}: {df.at[idx, 'professional']} a "
                f"{df.at[idx, 'slot_id']} ({df.at[idx, 'franja']}) el {df.at[idx, 'day']}.",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 5) Canviar presencialitat (PRES ↔ NP)  → edició directa
# ─────────────────────────────────────────────────────────────────────────────
def _quick_toggle_presentiality(year, professionals_path, pdf_output_dir, selected_months) -> None:
    with st.expander("🔁 Canviar presencialitat (PRES ↔ NP)", expanded=False):
        st.caption(
            "Canvi manual immediat (sense solver): gira una màquina de "
            "presencial a no presencial o al revés."
        )
        df = _load_schedule()
        if df is None or df.empty:
            st.info("Genera primer el calendari.")
            return
        needed = {"day", "franja", "slot_id", "professional", "presentiality", "work_mode"}
        if not needed.issubset(set(df.columns)):
            st.info("El calendari generat no té el format esperat.")
            return
        slotU = df["slot_id"].str.strip().str.upper()
        elig = df[
            (df["professional"].str.strip() != "")
            & (~slotU.map(is_review_slot))
            & (df["work_mode"].str.strip().str.upper() != "PEONADA")
        ]
        if elig.empty:
            st.info("No hi ha assignacions de màquina (no revisió, no peonada) per canviar.")
            return

        def _lab(i, r):
            cur = "PRES" if str(r["presentiality"]).strip().upper() == "PRESENCIAL" else "NP"
            new = "NP" if cur == "PRES" else "PRES"
            return (f"{i}: {r['day']} · {r['franja']} · {r['slot_id']} "
                    f"({r['professional']})  [{cur}→{new}]")

        labels = {_lab(i, r): i for i, r in elig.iterrows()}
        with st.form("qa_presflip_form", clear_on_submit=True):
            label = st.selectbox("Assignació a girar", list(labels.keys()), key="qa_presflip_slot")
            submitted = st.form_submit_button("Girar presencialitat", width="stretch")
        if submitted:
            idx = labels[label]
            cur = str(df.at[idx, "presentiality"]).strip().upper()
            new = "NO_PRESENCIAL" if cur == "PRESENCIAL" else "PRESENCIAL"
            df.at[idx, "presentiality"] = new
            if "is_flipped" in df.columns:
                df.at[idx, "is_flipped"] = "0"
            _save_and_rerender(
                df, professionals_path, pdf_output_dir, year, selected_months,
                f"Presencialitat canviada: {df.at[idx, 'slot_id']} "
                f"({df.at[idx, 'franja']}) el {df.at[idx, 'day']} → "
                f"{'NO PRESENCIAL' if new == 'NO_PRESENCIAL' else 'PRESENCIAL'}.",
            )


def render_quick_add_panels(
    year: int,
    month: int,
    selected_months: list[int],
    professional_options: list[str],
    all_professional_options: list[str] | None,
    professionals_path: Path,
    pdf_output_dir: Path,
    absences_path: Path,
    guards_path: Path,
    reajustar: Callable[[str], None] | None = None,
) -> None:
    """Renderitza els 5 desplegables d'ajust ràpid sota el render.

    Absència/guàrdia escriuen a dades i tenen un botó **Reajustar (mínims
    canvis)** que el solver resol conservant al màxim el calendari actual;
    canvi puntual, peonada i canvi de presencialitat editen el calendari
    directament (a l'instant)."""
    profs = _profs(all_professional_options or professional_options)
    st.markdown("##### Ajustos ràpids")
    st.caption(
        "**Absència** i **guàrdia** les resol el solver: afegeix-les i prem "
        "**Reajustar (mínims canvis)** dins el seu desplegable (només mou el "
        "necessari). **Canvi puntual**, **peonada** i **canvi de "
        "presencialitat** s'apliquen a l'instant (edició directa, es perden "
        "si tornes a Generar)."
    )
    _quick_add_absence(absences_path, profs, year, month, reajustar)
    _quick_add_guard(guards_path, profs, year, month, reajustar)
    _quick_add_assignment_change(profs, year, professionals_path, pdf_output_dir, selected_months)
    _quick_toggle_peonada(year, professionals_path, pdf_output_dir, selected_months)
    _quick_toggle_presentiality(year, professionals_path, pdf_output_dir, selected_months)
