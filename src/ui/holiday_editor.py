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
from src.services.public_holidays_csv import load_public_holidays_from_csv
from src.ui.table_state import (
    autosave_draft_if_changed,
    data_editor_height,
    source_table_signature,
    table_draft,
)
from src.ui.workflow_state import WORKFLOW_KEYS


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

    manual_day = st.date_input(
        "Dia",
        value=date_input_value_in_year("manual_calendar_day_main", year, 1),
        min_value=date(year, 1, 1),
        max_value=date(year, 12, 31),
        format="DD/MM/YYYY",
        key="manual_calendar_day_main",
    )

    if st.button("Afegir a la taula", key="add_calendar_override_main", width="stretch"):
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

    st.subheader("Introducció amb arxiu csv de la Generalitat")

    uploaded_holidays_csv = st.file_uploader(
        "Carrega CSV de festius oficials de la Generalitat (opcional)",
        type=["csv"],
        key="uploaded_holidays_csv_main",
    )

    if uploaded_holidays_csv is not None:
        tmp_holidays_path = Path("data/uploads/holidays_uploaded.csv")
        tmp_holidays_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            upload_key = f"{year}:{uploaded_holidays_csv.name}:{uploaded_holidays_csv.size}"
            should_process_upload = st.session_state.get("processed_holidays_upload") != upload_key
            # El fitxer es processa UNA SOLA vegada: si el bloc de merge+desat
            # corregués a cada rerun (el uploader conserva el fitxer), els
            # festius que l'usuari esborra de la taula ressuscitarien
            # immediatament des del CSV carregat.
            if should_process_upload:
                tmp_holidays_path.write_bytes(uploaded_holidays_csv.getvalue())
                holidays_df = load_public_holidays_from_csv(tmp_holidays_path, year)
                if holidays_df.empty:
                    st.warning(f"No s'han trobat festius per a l'any {year} dins del CSV.")
                else:
                    export_holidays_path = Path(f"data/derived/public_holidays_{year}.csv")
                    export_holidays_path.parent.mkdir(parents=True, exist_ok=True)
                    holidays_df.to_csv(export_holidays_path, index=False)
                    # Merge into the manual overrides table so they show up there too.
                    csv_rows = pd.DataFrame({
                        "day": pd.to_datetime(holidays_df["day"], errors="coerce"),
                        "tipus": "Festiu oficial manual",
                        "notes": holidays_df.get("location", "").astype(str),
                    })
                    merged = pd.concat(
                        [overrides_editor_source, csv_rows], ignore_index=True,
                    )
                    merged["day"] = pd.to_datetime(merged["day"], errors="coerce")
                    merged = (
                        merged.dropna(subset=["day"])
                        .drop_duplicates(subset=["day"], keep="first")
                        .sort_values("day")
                        .reset_index(drop=True)
                    )
                    save_base_calendar_overrides(base_calendar_overrides_path, merged)
                    st.session_state.pop("base_calendar_overrides_draft", None)
                    st.session_state.pop("base_calendar_overrides_draft_signature", None)
                    st.session_state["step_public_holidays"] = True
                    for key in WORKFLOW_KEYS:
                        if key != "step_public_holidays":
                            st.session_state[key] = False
                    st.session_state["processed_holidays_upload"] = upload_key
                    st.rerun()
            else:
                st.success(
                    "Festius del CSV ja incorporats a la taula. Pots editar-la "
                    "o esborrar-ne files lliurement."
                )
        except Exception as e:
            st.error(f"No s'ha pogut llegir el CSV de festius: {e}")

    st.divider()

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
