"""Editor de la Roda d'assignació (torns rotatoris per activitat)."""

import pandas as pd
import streamlit as st

from src.services.wheel_assignments import load_wheel, save_wheel


def render_wheel_editor(existing_slots: list[str], professional_options: list[str]) -> None:
    st.caption(
        "Les activitats de la **roda** s'assignen per **torn rotatori**: cada "
        "vegada que l'activitat apareix al calendari li toca al següent de la "
        "llista (si està absent aquell dia, perd el torn i passa al següent). "
        "La roda continua entre mesos. És una restricció **tova**: el solver "
        "segueix el torn sempre que el calendari ho permeti, però pot "
        "desviar-se'n si cal per cobrir-ho tot. Les màquines fixes i els "
        "canvis manuals hi prevalen."
    )
    wheel = load_wheel()

    _DAY_LABELS = {
        "": "Tots els dies", "MONDAY": "Dilluns", "TUESDAY": "Dimarts",
        "WEDNESDAY": "Dimecres", "THURSDAY": "Dijous", "FRIDAY": "Divendres",
    }
    if not wheel.empty:
        for i, row in enumerate(wheel.itertuples(index=False)):
            col_txt, col_del = st.columns([5, 1])
            participants = str(row.professionals or "").strip() or "tots els facultatius"
            _wd = str(getattr(row, "weekday_name", "") or "").strip().upper()
            _dia = _DAY_LABELS.get(_wd, _wd)
            col_txt.markdown(f"🎡 **{row.slot_id}** · {_dia} — ordre: {participants}")
            if col_del.button("Treure", key=f"wheel_rm_{i}", width="stretch"):
                save_wheel(wheel[
                    ~((wheel["slot_id"] == row.slot_id)
                      & (wheel["weekday_name"] == _wd))
                ])
                st.toast(f"«{row.slot_id}» ({_dia}) fora de la roda", icon="🗑️")
                st.rerun()
    else:
        st.caption("Cap activitat a la roda encara.")

    _slots = sorted(
        {str(s).strip().upper() for s in (existing_slots or []) if str(s).strip()}
    )
    _profs = sorted(
        p for p in (professional_options or [])
        if str(p).strip().upper() not in {"", "NONE", "NAN"}
    )
    col_slot, col_day, col_profs = st.columns([1.2, 0.9, 2])
    with col_slot:
        new_slot = st.selectbox(
            "Activitat", [""] + _slots, key="wheel_new_slot",
        )
    with col_day:
        new_day = st.selectbox(
            "Dia",
            options=list(_DAY_LABELS),
            format_func=lambda v: _DAY_LABELS[v],
            key="wheel_new_day",
            help="«Tots els dies» = una sola roda per a totes les "
                 "ocurrències. Un dia concret = roda pròpia (amb la seva "
                 "llista) només aquell dia; preval sobre la de «tots».",
        )
    with col_profs:
        new_profs = st.multiselect(
            "Participants i ordre (buit = tots)",
            options=_profs,
            key="wheel_new_profs",
            help="L'ordre de selecció és l'ordre del torn. Si ho deixes "
                 "buit, hi roten tots els facultatius (ordre alfabètic).",
        )
    _dup = (
        not wheel.empty
        and ((wheel["slot_id"] == str(new_slot).strip().upper())
             & (wheel["weekday_name"] == new_day)).any()
    )
    if _dup:
        st.warning("Aquesta activitat ja té roda per a aquest dia (es substituirà).")
    if st.button(
        "Afegir a la roda",
        type="primary",
        disabled=not str(new_slot).strip(),
        key="wheel_add",
    ):
        updated = pd.concat([
            wheel,
            pd.DataFrame([{
                "slot_id": str(new_slot).strip().upper(),
                "weekday_name": new_day,
                "professionals": ";".join(new_profs),
            }]),
        ], ignore_index=True)
        save_wheel(updated)
        st.toast(f"«{new_slot}» afegida a la roda", icon="🎡")
        st.rerun()
