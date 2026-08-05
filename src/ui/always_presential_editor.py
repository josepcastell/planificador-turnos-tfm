"""Editor de les activitats OBLIGATÒRIAMENT PRESENCIALS.

El flag viu al catàleg (`data/slot_catalog.csv`, columna
`always_presential`), però s'edita NOMÉS des d'aquí: tenir-hi dos punts
d'edició faria que l'esborrany en memòria del catàleg (pestanya
Activitats) pogués desfer el canvi en silenci. Per això, en desar,
s'invaliden les claus de l'esborrany perquè es rellegeixi del disc.
"""
from pathlib import Path

import streamlit as st

from src.services.slot_catalog import (
    always_presential_slot_ids,
    load_slot_catalog,
    review_slot_ids,
    save_slot_catalog,
    weekday_slot_ids,
)


def render_always_presential_editor(catalog_path: Path) -> None:
    st.caption(
        "Activitats que **no es poden fer en remot**. El solver mai les "
        "convertirà en no-presencials per quadrar les regles d'equilibri "
        "(per això van per sobre seu). No afecta el que hagis definit a "
        "les Franges: si hi has posat una instància com a no presencial, "
        "es respecta."
    )
    catalog_path = Path(catalog_path)
    try:
        catalog = load_slot_catalog(catalog_path)
    except Exception:
        st.info("Encara no hi ha catàleg d'activitats.")
        return

    reviews = {str(r).strip().upper() for r in review_slot_ids(catalog)}
    options = [
        s for s in weekday_slot_ids(catalog)
        if str(s).strip().upper() not in reviews
    ]
    if not options:
        st.info(
            "No hi ha activitats al catàleg entre setmana. Crea-les primer "
            "a la pestanya Activitats."
        )
        return

    current = sorted(always_presential_slot_ids(catalog) & set(options))
    selected = st.multiselect(
        "Activitats sempre presencials",
        options=options,
        default=current,
        key="always_presential_picker",
        placeholder="Cap activitat marcada",
        label_visibility="collapsed",
    )
    if sorted(selected) == current:
        return

    marked = {str(s).strip().upper() for s in selected}
    updated = catalog.copy()
    ids = updated["slot_id"].fillna("").astype(str).str.strip().str.upper()
    updated["always_presential"] = ids.isin(marked).astype(int)
    save_slot_catalog(catalog_path, updated)
    # L'esborrany del catàleg queda obsolet: es força la rellegida.
    st.session_state.pop("slot_catalog_draft", None)
    st.session_state.pop("slot_catalog_current", None)
    st.toast(
        f"{len(marked)} activitat(s) sempre presencial(s)", icon="🏥",
    )
    st.rerun()
