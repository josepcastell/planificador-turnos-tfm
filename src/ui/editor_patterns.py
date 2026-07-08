"""Helpers comuns per als editors basats en formulari + `st.dataframe` amb
selecció de fila (catàleg d'activitats, facultatius...).

Centralitza el patró de:
- Inicialització del draft persistent a `session_state` (no es recarrega del
  disc a cada rerun, només al primer cop o si canvia el path origen).
- Lectura de la fila seleccionada al `st.dataframe`.
- Cerca segura de l'índex d'una opció a una llista (per a selectboxes amb
  defaults).
"""

from pathlib import Path

import pandas as pd
import streamlit as st


def init_sticky_draft(
    draft_key: str,
    source_df: pd.DataFrame,
    columns: list[str],
    source_path: Path,
) -> pd.DataFrame:
    """Inicialitza (o reutilitza) un draft persistent a `session_state`.

    El draft només s'inicialitza des de `source_df` la primera vegada o
    quan `source_path` canvia (p. ex. canvi de sessió). En reruns
    successius es retorna l'estat conservat.

    Args:
        draft_key: clau de `session_state` (p. ex. "slot_catalog_draft").
        source_df: DataFrame d'origen (típicament llegit del disc).
        columns: ordre i conjunt de columnes garantides al draft.
        source_path: ruta del fitxer d'origen; quan canvia es reinicialitza.

    Retorna una còpia del draft amb totes les columnes garantides.
    """
    path_key = f"{draft_key}_path"
    if (
        draft_key not in st.session_state
        or st.session_state.get(path_key) != str(source_path)
    ):
        st.session_state[draft_key] = source_df[columns].copy()
        st.session_state[path_key] = str(source_path)
    draft = st.session_state[draft_key].copy()
    for col in columns:
        if col not in draft.columns:
            draft[col] = ""
    return draft[columns].copy()


def read_table_selection(table_key: str, n_rows: int) -> int | None:
    """Llegeix l'índex de la primera fila seleccionada d'un `st.dataframe`
    (estat guardat a `session_state[table_key]` per la rerunada anterior).

    Retorna `None` si no hi ha selecció vàlida o si l'índex està fora de
    rang.
    """
    state = st.session_state.get(table_key)
    rows: list[int] = []
    try:
        if state is not None:
            if hasattr(state, "selection"):
                rows = list(getattr(state.selection, "rows", []) or [])
            elif isinstance(state, dict):
                rows = list(state.get("selection", {}).get("rows", []) or [])
    except Exception:
        rows = []
    if rows and 0 <= int(rows[0]) < n_rows:
        return int(rows[0])
    return None


def idx_of(value: str, options: list[str]) -> int:
    """Retorna l'índex de `value` dins `options`, o 0 si no s'hi troba.

    Útil per al paràmetre `index=` de `st.selectbox` quan vols un default
    "robust" (si la llista canvia, no peta)."""
    try:
        return options.index(value)
    except ValueError:
        return 0
