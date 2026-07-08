import calendar
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import CATALAN_MONTHS
from src.services.metrics_summary import load_schedule_for_display
from src.ui.calendar_html import render_schedule_calendar_html


def show_csv(path_str: str, title: str) -> None:
    path = Path(path_str)
    if path.exists() and path.stat().st_size > 0:
        st.subheader(title)

        if path.name == "schedule.csv":
            df = load_schedule_for_display(path_str)
        else:
            df = pd.read_csv(path)

        st.dataframe(df, width="stretch")
    else:
        st.info(f"No existe o està buit: {path_str}")


def render_generated_schedule_view(
    path: Path,
    title: str,
    selected_year: int,
    months_to_show: list[int],
    key_prefix: str,
    visible_weekdays: list[int] | None = None,
    fixed_month: int | None = None,
) -> None:
    st.subheader(title)
    if not path.exists() or path.stat().st_size == 0:
        st.info("Encara no hi ha cap calendari generat per aquesta part.")
        return
    schedule_df = load_schedule_for_display(str(path))
    if schedule_df is None or schedule_df.empty:
        st.info("El fitxer existeix, però no conté assignacions.")
        return

    visible_df = schedule_df[schedule_df["professional"].astype(str) != "NONE"].copy()
    if visible_df.empty:
        st.info("El calendari generat no conté facultatius assignats.")
        return

    view_month = fixed_month or (months_to_show[0] if months_to_show else 1)
    if fixed_month is None and len(months_to_show) > 1:
        view_month = st.selectbox(
            "Mes",
            months_to_show,
            format_func=lambda month_num: f"{CATALAN_MONTHS.get(month_num, month_num)} {selected_year}",
            key=f"{key_prefix}_month",
        )

    st.markdown(
        render_schedule_calendar_html(
            visible_df,
            int(selected_year),
            int(view_month),
            Path(f"data/base_calendar_{selected_year}.csv"),
            Path(f"data/derived/public_holidays_{selected_year}.csv"),
            visible_weekdays=visible_weekdays,
        ),
        unsafe_allow_html=True,
    )


def calendar_schedule_editor(
    schedule_df: pd.DataFrame,
    editor_cols: list[str],
    professional_options: list[str],
    selected_year: int,
    months_to_show: list[int],
    key_prefix: str,
    title: str,
    visible_weekdays: list[int] | None = None,
    fixed_month: int | None = None,
    absence_form_renderer=None,
) -> tuple[pd.DataFrame, int]:
    st.markdown(f"**{title}**")
    editable_df = schedule_df[editor_cols].copy()
    for col in editor_cols:
        editable_df[col] = editable_df[col].fillna("").astype(str)
    editable_df["day_dt"] = pd.to_datetime(editable_df["day"], errors="coerce")

    month_options = months_to_show or [1]
    editor_month = fixed_month or month_options[0]
    if fixed_month is None and len(month_options) > 1:
        editor_month = st.selectbox(
            "Mes a editar",
            month_options,
            format_func=lambda month_num: f"{CATALAN_MONTHS.get(month_num, month_num)} {selected_year}",
            key=f"{key_prefix}_editor_month",
        )

    selected_day_key = f"{key_prefix}_selected_day"
    first_day = date(selected_year, editor_month, 1)
    last_day = date(
        selected_year, editor_month,
        calendar.monthrange(selected_year, editor_month)[1],
    )
    default_day = st.session_state.get(selected_day_key) or first_day
    if not (first_day <= default_day <= last_day):
        default_day = first_day
    selected_day = st.date_input(
        "Dia a editar",
        value=default_day,
        min_value=first_day,
        max_value=last_day,
        format="DD/MM/YYYY",
        key=f"{key_prefix}_day_picker",
    )
    st.session_state[selected_day_key] = selected_day

    st.markdown(f"### {selected_day.strftime('%d/%m/%Y')}")

    if absence_form_renderer is not None:
        absence_form_renderer(selected_day)
        st.divider()

    day_mask = editable_df["day_dt"].dt.date == selected_day
    day_df = editable_df[day_mask & (editable_df["professional"].astype(str) != "NONE")].copy()
    if day_df.empty:
        st.info("Aquest dia no té assignacions assignades.")
        return editable_df.drop(columns=["day_dt"]), editor_month

    st.markdown("**Editar assignacions del dia**")
    updated_df = editable_df.copy()
    base_professionals = [p for p in professional_options if p]
    for row_index, row in day_df.iterrows():
        descriptor_parts = [
            str(row.get("franja", "")),
            str(row.get("slot_id", "")),
            str(row.get("reporting_machine", "")),
            str(row.get("presentiality", "")).replace("_", " ").title(),
            "Peonada" if str(row.get("work_mode", "")).upper() == "PEONADA" else "Ordinària",
        ]
        descriptor = " · ".join(part for part in descriptor_parts if part)
        current_professional = str(row.get("professional", "")).strip()
        options = sorted(set(base_professionals + [current_professional]))
        row_cols = st.columns([2.4, 1])
        with row_cols[0]:
            st.write(descriptor)
        with row_cols[1]:
            updated_df.loc[row_index, "professional"] = st.selectbox(
                "Facultatiu",
                options,
                index=options.index(current_professional) if current_professional in options else 0,
                key=f"{key_prefix}_professional_{row_index}",
                label_visibility="collapsed",
            )

    return updated_df.drop(columns=["day_dt"]), editor_month


