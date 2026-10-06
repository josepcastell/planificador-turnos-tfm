import json
from pathlib import Path

import streamlit as st

from src.domain.constants import CATALAN_MONTHS, WEEKDAY_SCOPE_OPTIONS
from src.domain.planning_scope import clamp_month, months_for_scope


# Persistència de la selecció del desplegable (àmbit/mes) de la pestanya
# "Generar i revisar": s'autoguarda a disc i es restaura en obrir l'app.
_SCOPE_PREFS_PATH = Path("data/calendar_view_settings.json")
_SCOPE_KEYS = {
    "weekday_planning_scope": "planning_scope",
    # L'ANY forma part de l'àmbit (com el mes o el trimestre): no és una
    # propietat de la sessió, que conté tots els anys.
    "weekday_selected_year": "selected_year",
    "weekday_selected_month": "selected_month",
    "weekday_selected_quarter": "selected_quarter",
    "weekday_selected_semester": "selected_semester",
    "weekday_display_month": "display_month",
}


def _DEFAULT_YEAR_FALLBACK() -> int:
    from datetime import date
    return date.today().year


def year_options(default_year: int) -> list[int]:
    """Anys triables: des de l'anterior a l'actual fins a cinc endavant,
    incloent-hi sempre el que ja estigui seleccionat."""
    from datetime import date
    today = date.today().year
    anys = set(range(today - 1, today + 6))
    anys.add(int(default_year))
    return sorted(anys)


def weekday_scope_year(default_year: int) -> int:
    """Any de l'àmbit. Es llegeix de l'estat (el desplegable es dibuixa
    més avall, com la resta de l'àmbit), amb el valor desat a disc com a
    punt de partida."""
    if "weekday_selected_year" not in st.session_state:
        prefs = _load_scope_prefs()
        valor = prefs.get("selected_year", default_year)
        try:
            st.session_state["weekday_selected_year"] = int(valor)
        except (TypeError, ValueError):
            st.session_state["weekday_selected_year"] = int(default_year)
    try:
        return int(st.session_state["weekday_selected_year"])
    except (TypeError, ValueError):
        return int(default_year)


def _load_scope_prefs() -> dict:
    try:
        if _SCOPE_PREFS_PATH.exists() and _SCOPE_PREFS_PATH.stat().st_size:
            data = json.loads(_SCOPE_PREFS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        pass
    return {}


def _save_scope_prefs() -> None:
    data = {
        file_key: st.session_state[state_key]
        for state_key, file_key in _SCOPE_KEYS.items()
        if state_key in st.session_state
    }
    try:
        payload = json.dumps(data, ensure_ascii=False)
        if (
            not _SCOPE_PREFS_PATH.exists()
            or _SCOPE_PREFS_PATH.read_text(encoding="utf-8") != payload
        ):
            _SCOPE_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _SCOPE_PREFS_PATH.write_text(payload, encoding="utf-8")
    except OSError:
        pass


def sync_weekday_scope_state(default_month: int, allow_widget_updates: bool = True) -> None:
    if "weekday_scope_loaded" not in st.session_state:
        prefs = _load_scope_prefs()
        for state_key, file_key in _SCOPE_KEYS.items():
            if file_key in prefs and state_key not in st.session_state:
                st.session_state[state_key] = prefs[file_key]
        st.session_state["weekday_scope_loaded"] = True

    st.session_state.setdefault("weekday_planning_scope", "Mes seleccionat")
    st.session_state.setdefault("weekday_selected_month", default_month)
    st.session_state.setdefault("weekday_selected_year", _DEFAULT_YEAR_FALLBACK())
    st.session_state.setdefault("weekday_selected_quarter", 1)
    st.session_state.setdefault("weekday_selected_semester", 1)
    st.session_state.setdefault(
        "weekday_display_month",
        st.session_state["weekday_selected_month"],
    )

    if allow_widget_updates:
        st.session_state["weekday_selected_month"] = clamp_month(
            st.session_state["weekday_selected_month"]
        )
        st.session_state["weekday_display_month"] = clamp_month(
            st.session_state["weekday_display_month"]
        )

    current_scope = st.session_state["weekday_planning_scope"]
    if current_scope not in WEEKDAY_SCOPE_OPTIONS:
        current_scope = "Mes seleccionat"
        if allow_widget_updates:
            st.session_state["weekday_planning_scope"] = current_scope

    previous_scope = st.session_state.get("weekday_previous_scope")
    if previous_scope != current_scope:
        previous_month = clamp_month(
            st.session_state.get(
                "weekday_display_month",
                st.session_state["weekday_selected_month"],
            )
        )
        if allow_widget_updates:
            if current_scope == "Mes seleccionat":
                st.session_state["weekday_selected_month"] = previous_month
            elif current_scope == "Trimestre":
                st.session_state["weekday_selected_quarter"] = (previous_month - 1) // 3 + 1
            elif current_scope == "Semestre":
                st.session_state["weekday_selected_semester"] = 1 if previous_month <= 6 else 2
        st.session_state["weekday_previous_scope"] = current_scope

    if allow_widget_updates:
        _save_scope_prefs()


def weekday_scope_values(
    default_month: int,
    update_state: bool = True,
) -> tuple[str, int, int, int, list[int], int]:
    if update_state:
        sync_weekday_scope_state(default_month)
    planning_scope_value = st.session_state.get("weekday_planning_scope", "Mes seleccionat")
    if planning_scope_value not in WEEKDAY_SCOPE_OPTIONS:
        planning_scope_value = "Mes seleccionat"
    month_value = clamp_month(st.session_state.get("weekday_selected_month", default_month))
    quarter_value = int(st.session_state.get("weekday_selected_quarter", 1) or 1)
    semester_value = int(st.session_state.get("weekday_selected_semester", 1) or 1)
    quarter_value = min(4, max(1, quarter_value))
    semester_value = min(2, max(1, semester_value))
    selected_months_value = months_for_scope(
        planning_scope_value,
        month_value,
        quarter_value,
        semester_value,
    )
    display_month_value = clamp_month(
        st.session_state.get("weekday_display_month", month_value),
        month_value,
    )
    if display_month_value not in selected_months_value:
        display_month_value = (
            month_value if month_value in selected_months_value else selected_months_value[0]
        )
        if update_state:
            st.session_state["weekday_display_month"] = display_month_value
    return (
        planning_scope_value,
        month_value,
        quarter_value,
        semester_value,
        selected_months_value,
        display_month_value,
    )


def render_weekday_scope_controls(
    session_name: str,
    year: int,
    default_month: int,
) -> tuple[str, int, int, int, list[int], int]:
    year_col, scope_col, period_col, display_col = st.columns([1, 1.4, 1, 1.4])
    with year_col:
        # L'ANY es tria AQUÍ, amb la resta de l'àmbit. No és de la sessió:
        # una mateixa sessió conté tots els anys i només canvien els
        # festius, el calendari base i el planning.
        st.selectbox(
            "Any",
            year_options(year),
            key="weekday_selected_year",
            help="Canviar l'any NO canvia de sessió: la configuració "
                 "(activitats, franges, màquines fixes, rodes…) és la "
                 "mateixa per a tots els anys.",
        )
    year = weekday_scope_year(year)
    with scope_col:
        planning_scope = st.radio(
            "Àmbit del calendari",
            WEEKDAY_SCOPE_OPTIONS,
            key="weekday_planning_scope",
        )
    sync_weekday_scope_state(default_month)
    with period_col:
        if planning_scope == "Semestre":
            st.selectbox(
                "Semestre",
                [1, 2],
                format_func=lambda value: f"S{value}",
                key="weekday_selected_semester",
            )
        elif planning_scope == "Trimestre":
            st.selectbox(
                "Trimestre",
                [1, 2, 3, 4],
                format_func=lambda value: f"T{value}",
                key="weekday_selected_quarter",
            )
        elif planning_scope == "Mes seleccionat":
            st.selectbox(
                "Mes",
                list(range(1, 13)),
                format_func=lambda month_num: f"{CATALAN_MONTHS.get(month_num, month_num)} {year}",
                key="weekday_selected_month",
            )

    values = weekday_scope_values(default_month, update_state=False)
    planning_scope, _month, _quarter, _semester, selected_months, _display_month = values
    if planning_scope != "Mes seleccionat":
        with display_col:
            st.selectbox(
                "Mes a visualitzar",
                selected_months,
                format_func=lambda month_num: f"{CATALAN_MONTHS.get(month_num, month_num)} {year}",
                key="weekday_display_month",
            )
    return weekday_scope_values(default_month, update_state=False)
