"""Helper d'UI per mostrar notificacions de conflictes entre les
restriccions opcionals i el calendari inicial."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.services.restriction_conflicts import (
    detect_absences_conflicts,
    detect_eligibility_conflicts,
    detect_fixed_machines_conflicts,
    detect_guards_conflicts,
    detect_no_pres_weekday_conflicts,
    detect_pres_weekday_conflicts,
    load_initial_schedule,
)


def _render_conflict_list(msgs: list[str]) -> None:
    """Mostra els missatges com a `st.warning` amb un bullet per cadascun."""
    if not msgs:
        return
    body = "\n".join(f"- {m}" for m in msgs)
    st.warning(
        f"⚠️ **Aquesta restricció trenca el calendari inicial:**\n\n{body}\n\n"
        "Prem **Regenerar** per actualitzar el definitiu amb la restricció.",
        icon="⚠️",
    )


def warn_absences_vs_initial(absences_path: Path) -> None:
    """Comprova absències vs inicial i mostra warning si hi ha conflictes."""
    initial = load_initial_schedule()
    if initial.empty:
        return
    try:
        absences = pd.read_csv(absences_path)
    except (OSError, pd.errors.EmptyDataError):
        return
    _render_conflict_list(detect_absences_conflicts(initial, absences))


def warn_eligibility_vs_initial(eligibility_path: Path) -> None:
    initial = load_initial_schedule()
    if initial.empty:
        return
    try:
        eligibility = pd.read_csv(eligibility_path)
    except (OSError, pd.errors.EmptyDataError):
        return
    _render_conflict_list(detect_eligibility_conflicts(initial, eligibility))


def warn_no_pres_weekday_vs_initial(professionals_path: Path) -> None:
    initial = load_initial_schedule()
    if initial.empty:
        return
    try:
        prof = pd.read_csv(professionals_path)
    except (OSError, pd.errors.EmptyDataError):
        return
    _render_conflict_list(detect_no_pres_weekday_conflicts(initial, prof))


def warn_pres_weekday_vs_initial(professionals_path: Path) -> None:
    initial = load_initial_schedule()
    if initial.empty:
        return
    try:
        prof = pd.read_csv(professionals_path)
    except (OSError, pd.errors.EmptyDataError):
        return
    _render_conflict_list(detect_pres_weekday_conflicts(initial, prof))


def warn_fixed_machines_vs_initial(catalog_path: Path) -> None:
    initial = load_initial_schedule()
    if initial.empty:
        return
    try:
        catalog = pd.read_csv(catalog_path)
    except (OSError, pd.errors.EmptyDataError):
        return
    _render_conflict_list(detect_fixed_machines_conflicts(initial, catalog))


def warn_guards_vs_initial(guards_path: Path) -> None:
    initial = load_initial_schedule()
    if initial.empty:
        return
    try:
        guards = pd.read_csv(guards_path)
    except (OSError, pd.errors.EmptyDataError):
        return
    _render_conflict_list(detect_guards_conflicts(initial, guards))
