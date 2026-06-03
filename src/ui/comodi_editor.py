"""Editor del comodí (fallback) per facultatiu. Es viu a Restriccions
› expander "Comodí". El comodí absorbeix els slots sobrants sense
límit de quota setmanal i no se li compta peonada.

Es persisteix a la columna `fallback` de `data/professionals.csv`."""
from pathlib import Path

import pandas as pd
import streamlit as st


def render_comodi_editor(
    professionals_path: Path,
) -> None:
    """Multiselect dels facultatius marcats com a comodí (fallback=1).
    Autosave a `professionals.csv`."""
    try:
        df = pd.read_csv(professionals_path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        st.info("Primer introdueix facultatius a la pestanya Facultatius.")
        return

    if "professional_id" not in df.columns:
        st.info("Fitxer de facultatius invàlid.")
        return
    if "fallback" not in df.columns:
        df["fallback"] = 0

    df["professional_id"] = (
        df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    )
    df["fallback"] = pd.to_numeric(
        df["fallback"], errors="coerce"
    ).fillna(0).astype(int).clip(0, 1)
    eligible = df[
        (df["professional_id"] != "") & (df["professional_id"] != "NONE")
    ].copy()
    if eligible.empty:
        st.info("Primer introdueix facultatius a la pestanya Facultatius.")
        return

    st.markdown(
        "Marca quins facultatius són **comodí** (fallback). El comodí "
        "absorbeix els slots sobrants sense límit setmanal i no se li "
        "compta peonada. Normalment és un sol facultatiu (p. ex. el "
        "TLD/telediagnòstic remot)."
    )

    all_pids = sorted(eligible["professional_id"].unique().tolist())
    current_fb = sorted(
        eligible.loc[eligible["fallback"] == 1, "professional_id"]
        .unique().tolist()
    )

    selected = st.multiselect(
        "Facultatius comodí",
        options=all_pids,
        default=current_fb,
        key="comodi_picker",
        placeholder="Cap facultatiu marcat com a comodí",
    )

    # Si la selecció canvia, persistim.
    new_set = {str(p).strip().upper() for p in selected}
    current_set = set(current_fb)
    if new_set != current_set:
        df["fallback"] = df["professional_id"].map(
            lambda p: 1 if str(p).strip().upper() in new_set else 0
        )
        df.to_csv(professionals_path, index=False)
        st.toast(
            f"Comodí actualitzat: {len(new_set)} facultatiu(s)",
            icon="✅",
        )
