from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.schedule_format import slot_sort_key
from src.services.input_tables import save_eligibility_for_professional
from src.services.table_io import read_table
from src.ui.table_state import (
    autosave_draft_if_changed,
    data_editor_height,
    table_draft,
)


def render_eligibility_editor(
    eligibility_path: Path,
    professional_options: list[str],
    slot_options: list[str],
    key_prefix: str,
) -> None:
    eligibility_df = read_table(eligibility_path, ["professional_id", "slot_id", "allowed"])
    eligibility_df["professional_id"] = eligibility_df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    eligibility_df["slot_id"] = eligibility_df["slot_id"].fillna("").astype(str).str.strip()
    eligibility_df["allowed"] = pd.to_numeric(eligibility_df["allowed"], errors="coerce").fillna(0).astype(int).clip(0, 1)

    clean_professionals = sorted({
        str(prof).strip().upper()
        for prof in professional_options
        if str(prof).strip() and str(prof).strip().upper() != "NONE"
    })
    clean_slots = sorted({str(slot).strip() for slot in slot_options if str(slot).strip()}, key=slot_sort_key)
    if not clean_professionals:
        st.info("Primer introdueix facultatius.")
        return
    if not clean_slots:
        st.info("Primer crea activitats a la pestanya Activitat.")
        return

    selected_professional = st.selectbox("Facultatiu", clean_professionals, key=f"{key_prefix}_professional_selector")
    prof_eligibility = eligibility_df[
        eligibility_df["professional_id"].astype(str) == selected_professional
    ][["slot_id", "allowed"]].copy()
    existing_prof_slots = set(prof_eligibility["slot_id"].astype(str))
    missing_slots = [{"slot_id": slot_id, "allowed": 1} for slot_id in clean_slots if slot_id not in existing_prof_slots]
    if missing_slots:
        prof_eligibility = pd.concat([prof_eligibility, pd.DataFrame(missing_slots)], ignore_index=True)
    prof_eligibility = prof_eligibility[prof_eligibility["slot_id"].isin(clean_slots)].copy()
    prof_eligibility["slot_order"] = prof_eligibility["slot_id"].apply(slot_sort_key)
    prof_eligibility = prof_eligibility.sort_values(["slot_order", "slot_id"]).drop(columns=["slot_order"]).reset_index(drop=True)
    draft_key = f"{key_prefix}_eligibility_draft_{selected_professional}"
    # Signatura nomes de context (path + facultatiu + llista de slots).
    # NO inclou el hash del contingut del fitxer: si l'hi inclogues, cada
    # autosave canviaria el contingut, forcaria un reset del draft, i el
    # data_editor rebria un `data` prop diferent del rerun anterior —
    # cosa que fa Streamlit descartar els pending edits (bug «cal clicar
    # dos cops la seguent casella»). Amb una signatura de context,
    # el draft inicial es estable durant tota la sessio d'edicio d'aquest
    # facultatiu, i els pending edits del data_editor s'acumulen.
    context_signature = (
        f"{key_prefix}|{selected_professional}|"
        f"{str(eligibility_path.resolve())}|{','.join(clean_slots)}"
    )
    # En canviar de facultatiu, el draft es refà del FITXER i el data_editor
    # es munta de nou (nonce). Abans es reutilitzava el draft de la primera
    # visita: en tornar-hi, les caselles desmarcades sortien marcades i el
    # següent autodesat ho reescrivia al fitxer («es tornen a marcar
    # soles»). Cada canvi ja s'ha desat al moment, així que partir del
    # fitxer no perd res.
    # El mateix si el fitxer ha canviat des d'un altre lloc (p.ex. en
    # restaurar una versió de la sessió): l'empremta del disc no és la que
    # aquest editor va deixar.
    last_professional_key = f"{key_prefix}_eligibility_last_professional"
    nonce_key = f"{key_prefix}_eligibility_editor_nonce"
    disk_sig_key = f"{key_prefix}_eligibility_disk_{selected_professional}"
    disk_sig = _eligibility_signature(prof_eligibility)
    known_sig = st.session_state.get(disk_sig_key)
    if (
        st.session_state.get(last_professional_key) != selected_professional
        or (known_sig is not None and known_sig != disk_sig)
    ):
        st.session_state.pop(draft_key, None)
        st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1
        st.session_state[last_professional_key] = selected_professional
    prof_eligibility_editor_df = table_draft(
        draft_key,
        prof_eligibility,
        ["slot_id", "allowed"],
        context_signature,
    )

    edited_prof_eligibility = st.data_editor(
        prof_eligibility_editor_df,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=data_editor_height(len(prof_eligibility_editor_df)),
        key=(
            f"{key_prefix}_eligibility_editor_{selected_professional}"
            f"_{st.session_state[nonce_key]}"
        ),
        column_config={
            "slot_id": st.column_config.TextColumn("Activitat", disabled=True),
            "allowed": st.column_config.CheckboxColumn("Elegible"),
        },
    )
    # Important: NO actualitzem session_state[draft_key] amb el resultat
    # del data_editor. Si ho fessim, el draft canviaria dtype (BOOL post-
    # CheckboxColumn enfront del INT del disc), i el `data` prop del
    # rerun seguent seria diferent del rerun anterior, perdent els
    # pending edits. Deixant el draft inicial intacte, el data_editor
    # rep `data` ESTABLE i els `edited_rows` interns s'acumulen. La
    # persistencia es fa amb `edited_prof_eligibility` directament.

    def _save(df: pd.DataFrame) -> None:
        fresh = read_table(eligibility_path, ["professional_id", "slot_id", "allowed"])
        save_eligibility_for_professional(fresh, selected_professional, df, eligibility_path)

    saved = autosave_draft_if_changed(
        draft_key,
        edited_prof_eligibility[["slot_id", "allowed"]],
        ["slot_id", "allowed"],
        _save,
    )
    st.session_state[disk_sig_key] = (
        _eligibility_signature(edited_prof_eligibility) if saved else disk_sig
    )


def _eligibility_signature(df: pd.DataFrame) -> tuple:
    """Empremta (slot, permès) d'una taula d'elegibilitat, igual per a
    int i bool (el data_editor retorna bool, el disc int)."""
    return tuple(sorted(
        (str(r.slot_id).strip(), int(bool(r.allowed))) for r in df.itertuples(index=False)
    ))
