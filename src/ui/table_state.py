from collections.abc import Callable
from pathlib import Path

import pandas as pd
import streamlit as st


def data_editor_height(n_rows: int) -> int:
    """Pixel height that fits n_rows + the add-row line (dynamic editor)."""
    return 38 + 35 * (max(n_rows, 0) + 1) + 8


def source_table_signature(path: Path, df: pd.DataFrame) -> str:
    """Content-based signature: changes only when df content (rows × cols) changes,
    not when the file's mtime is touched (e.g., by an idempotent re-save).

    This lets autosave callers persist drafts without spuriously resetting the
    in-memory draft on the next rerun.
    """
    if df is None:
        return f"{path.resolve()}|none"
    cols = ",".join(df.columns.astype(str))
    if df.empty:
        return f"{path.resolve()}|empty|{cols}"
    try:
        content_hash = int(pd.util.hash_pandas_object(df.fillna(""), index=False).sum())
    except Exception:
        content_hash = hash(df.fillna("").astype(str).to_csv(index=False))
    return f"{path.resolve()}|{len(df)}|{cols}|{content_hash}"


def _normalize_cell(col: pd.Series) -> pd.Series:
    """Normalitza una columna per a comparació de continguts: els valors
    bool/int/float numèrics colapsen al mateix string ("1"/"0"); la resta
    es stringifica directament. Necessari perquè el `data_editor` amb
    `CheckboxColumn` retorna bool i el disc emmagatzema int, així
    `True` ≡ `1` ≡ `"1"` quan comparem el draft amb el source."""
    if col.dtype == bool:
        return col.astype(int).astype(str)
    try:
        num = pd.to_numeric(col, errors="coerce")
        if num.notna().all():
            if (num == num.round()).all():
                return num.astype(int).astype(str)
            return num.astype(str)
    except Exception:
        pass
    return col.fillna("").astype(str)


def _content_match(a: pd.DataFrame, b: pd.DataFrame, columns: list[str]) -> bool:
    """Compara dos DataFrames pel contingut de les columnes indicades,
    ignorant l'index i normalitzant bool↔int. Retorna True si coincideixen
    cel·la a cel·la després de la normalització."""
    try:
        if len(a) != len(b):
            return False
        a_r = a[columns].reset_index(drop=True)
        b_r = b[columns].reset_index(drop=True)
        for col in columns:
            if not _normalize_cell(a_r[col]).equals(_normalize_cell(b_r[col])):
                return False
        return True
    except Exception:
        return False


def table_draft(key: str, source_df: pd.DataFrame, columns: list[str], signature: str) -> pd.DataFrame:
    """Sticky draft per a un `st.data_editor`. Si la `signature` canvia,
    normalment es reinicia el draft amb el `source_df` actual. Excepció
    crítica: quan el draft existent JA conté exactament el mateix
    contingut que el nou source (cas post-autosave: l'edició de l'usuari
    s'ha acabat d'escriure a disc, el fitxer ha canviat només per això),
    només actualitzem la signatura SENSE resetejar el draft. Així el
    `data_editor` rep el mateix `data` prop al rerun següent i Streamlit
    no descarta els pending edits acumulats (bug típic en columnes
    `CheckboxColumn`: «cal clicar dos cops la cel·la següent»)."""
    signature_key = f"{key}_signature"
    stored_sig = st.session_state.get(signature_key)
    if stored_sig != signature or key not in st.session_state:
        if key in st.session_state and _content_match(
            st.session_state[key], source_df, columns
        ):
            st.session_state[signature_key] = signature
        else:
            st.session_state[key] = source_df[columns].copy()
            st.session_state[signature_key] = signature
    draft = st.session_state[key].copy()
    for col in columns:
        if col not in draft.columns:
            draft[col] = ""
    return draft[columns].copy()


def _draft_signature_for_autosave(df: pd.DataFrame, columns: list[str]) -> str:
    if df is None or df.empty:
        return "empty"
    try:
        return df[columns].fillna("").astype(str).to_csv(index=False)
    except Exception:
        return repr(df[columns].values.tolist())


def autosave_draft_if_changed(
    draft_key: str,
    df: pd.DataFrame,
    columns: list[str],
    save_fn: Callable[[pd.DataFrame], None],
    on_change: Callable[[], None] | None = None,
) -> bool:
    """Persist df via save_fn only when its content has changed since the last
    call (compared by stable string signature on `columns`). Returns True if a
    save was actually performed.
    """
    sig = _draft_signature_for_autosave(df, columns)
    sig_key = f"_autosave_sig_{draft_key}"
    if st.session_state.get(sig_key) == sig:
        return False
    save_fn(df)
    st.session_state[sig_key] = sig
    if on_change is not None:
        on_change()
    return True


def commit_new_row(
    draft_key: str,
    new_row: dict,
    columns: list[str],
    save_fn: Callable[[pd.DataFrame], None],
    fallback_df: pd.DataFrame | None = None,
) -> None:
    """Common tail of every quick-add form: append `new_row` to the draft in
    session_state, increment the editor's nonce (so the data_editor remounts and
    picks up the change), persist via `save_fn`, then `st.rerun()`.

    `draft_key` is the session_state key of the draft (e.g. "comite_draft");
    the matching nonce key is derived by stripping the trailing "_draft".
    """
    existing = st.session_state.get(draft_key)
    if existing is None:
        existing = fallback_df if fallback_df is not None else pd.DataFrame(columns=columns)
    combined = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True)[columns].copy()
    st.session_state[draft_key] = combined
    nonce_key = (
        draft_key.removesuffix("_draft") + "_editor_nonce"
        if draft_key.endswith("_draft")
        else f"{draft_key}_editor_nonce"
    )
    st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1
    save_fn(combined)
    st.rerun()
