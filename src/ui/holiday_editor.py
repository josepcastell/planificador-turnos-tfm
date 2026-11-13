from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.services.calendar_inputs import (
    load_base_calendar_overrides,
    overrides_to_manual_editor,
    save_base_calendar_overrides,
)
from src.ui.table_state import (
    autosave_draft_if_changed,
    data_editor_height,
    source_table_signature,
    table_draft,
)


_DEFAULT_OVERRIDE_TIPUS = "Festiu intern / extra"


def render_holidays_editor(
    year: int,
    month: int,
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    date_input_value_in_year: Callable[[str, int, int], date],
) -> None:
    st.subheader("Introducció manual")
    overrides_df = load_base_calendar_overrides(base_calendar_overrides_path)
    overrides_editor_source = overrides_to_manual_editor(overrides_df)
    existing_overrides_draft = st.session_state.get("base_calendar_overrides_draft")
    if isinstance(existing_overrides_draft, pd.DataFrame) and "tipus" not in existing_overrides_draft.columns:
        st.session_state.pop("base_calendar_overrides_draft", None)
        st.session_state.pop("base_calendar_overrides_draft_signature", None)
    overrides_editor_df = table_draft(
        "base_calendar_overrides_draft",
        overrides_editor_source,
        ["day", "tipus", "notes"],
        source_table_signature(base_calendar_overrides_path, overrides_df),
    )

    c_day, c_add = st.columns([3, 1], vertical_alignment="bottom")
    manual_day = c_day.date_input(
        "Dia",
        value=date_input_value_in_year("manual_calendar_day_main", year, 1),
        min_value=date(year, 1, 1),
        max_value=date(year, 12, 31),
        format="DD/MM/YYYY",
        key="manual_calendar_day_main",
    )

    if c_add.button("Afegir a la taula", key="add_calendar_override_main", width="stretch"):
        new_row = pd.DataFrame(
            [{
                "day": pd.Timestamp(manual_day),
                "tipus": _DEFAULT_OVERRIDE_TIPUS,
                "notes": "",
            }]
        )
        overrides_editor_df = pd.concat([overrides_editor_df, new_row], ignore_index=True)
        overrides_editor_df = (
            overrides_editor_df.drop_duplicates(subset=["day"], keep="last")
            .sort_values("day")
            .reset_index(drop=True)
        )
        st.session_state["base_calendar_overrides_draft"] = overrides_editor_df[
            ["day", "tipus", "notes"]
        ].copy()
        st.rerun()

    st.subheader("Festius introduïts")
    overrides_nonce = st.session_state.get("base_calendar_overrides_editor_nonce", 0)
    _n_overrides = len(overrides_editor_df)
    _overrides_src = overrides_editor_df.copy()
    _overrides_src["_eliminar"] = False
    edited_overrides = st.data_editor(
        _overrides_src,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=data_editor_height(_n_overrides),
        key=f"base_calendar_overrides_editor_main_{overrides_nonce}",
        column_order=["day", "_eliminar"],
        column_config={
            "day": st.column_config.DateColumn(
                "Dia",
                format="DD/MM/YYYY",
                min_value=date(year, 1, 1),
                max_value=date(year, 12, 31),
            ),
            "_eliminar": st.column_config.CheckboxColumn(
                "Eliminar",
                help="Marca les files que vulguis eliminar i prem el botó de sota.",
            ),
        },
    )
    edited_overrides["tipus"] = edited_overrides["tipus"].fillna("").astype(str).where(
        edited_overrides["tipus"].fillna("").astype(str) != "",
        _DEFAULT_OVERRIDE_TIPUS,
    )

    _mark = (
        edited_overrides["_eliminar"].fillna(False).astype(bool)
        if "_eliminar" in edited_overrides.columns
        else pd.Series(False, index=edited_overrides.index)
    )
    _n_marked = int(_mark.sum())
    if st.button(
        f"🗑️ Eliminar {_n_marked} festius/ajustos marcat(s)"
        if _n_marked
        else "🗑️ Eliminar festius/ajustos marcats",
        disabled=_n_marked == 0,
        key="overrides_delete_marked",
    ):
        kept = edited_overrides.loc[~_mark, ["day", "tipus", "notes"]].copy().reset_index(drop=True)
        st.session_state["base_calendar_overrides_draft"] = kept
        st.session_state["base_calendar_overrides_editor_nonce"] = overrides_nonce + 1
        save_base_calendar_overrides(base_calendar_overrides_path, kept)
        st.rerun()

    st.session_state["base_calendar_overrides_draft"] = edited_overrides[
        ["day", "tipus", "notes"]
    ].copy()
    autosave_draft_if_changed(
        "base_calendar_overrides",
        st.session_state["base_calendar_overrides_draft"],
        ["day", "tipus", "notes"],
        lambda df: save_base_calendar_overrides(base_calendar_overrides_path, df),
    )
