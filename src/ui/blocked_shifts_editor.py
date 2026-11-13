"""Elegibilitat per TORN: un facultatiu no ha de tenir programació en una
franja (matí, tarda o nit) un dia de la setmana (cada setmana) o un dia
concret. Restricció pròpia a Restriccions › Altres restriccions."""
from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import WEEKDAY_TEMPLATE_COLUMNS
from src.services.input_tables import (
    add_blocked_shift,
    load_blocked_shifts,
    remove_blocked_shift,
)

_WEEKDAY_NAMES = ["dilluns", "dimarts", "dimecres", "dijous", "divendres",
                  "dissabte", "diumenge"]
_FRANJA_NAMES = {"MATI": "matí", "TARDA": "tarda", "NIT": "nit"}
_FRANJA_TXT = {"MATI": "al **matí**", "TARDA": "a la **tarda**", "NIT": "a la **nit**"}


def blocked_shift_label(row) -> str:
    """«cada **dilluns** a la **tarda**» o «**dimarts 15/12/2026** al **matí**»."""
    if row.day:
        d = pd.Timestamp(row.day)
        when = f"**{_WEEKDAY_NAMES[d.weekday()]} {d.strftime('%d/%m/%Y')}**"
    else:
        when = f"cada **{_WEEKDAY_NAMES[WEEKDAY_TEMPLATE_COLUMNS.index(row.weekday)]}**"
    return f"{when} {_FRANJA_TXT[row.franja]}"


def render_blocked_shifts_editor(shifts_path: Path, professional_options: list[str]) -> None:
    st.caption(
        "Franges (matí, tarda o nit) en què un facultatiu **no ha de tenir "
        "programació**: **cada setmana** un dia (p. ex. els dilluns a la "
        "tarda) o **un dia concret**. El solver no li'n posa cap activitat — "
        "si falta gent, un altre en fa doble feina —, les activitats fixes i "
        "la roda se la salten i els ajustos ràpids tampoc no l'hi posen. La "
        "resta del dia treballa amb normalitat."
    )
    profs = sorted(
        p for p in (professional_options or [])
        if str(p).strip() and str(p).strip().upper() != "NONE"
    )
    # Camps nous després de cada alta (nonce a les claus).
    nonce = st.session_state.get("bshift_nonce", 0)
    with st.form("bshift_form"):
        c_prof, c_wd, c_day, c_fr, c_btn = st.columns(
            [1.6, 1.8, 1.8, 1.3, 1], vertical_alignment="bottom",
        )
        prof = c_prof.selectbox(
            "Facultatiu", profs, index=None, placeholder="Tria'l",
            key=f"bshift_prof_{nonce}",
        )
        weekday = c_wd.selectbox(
            "Cada setmana, el…", WEEKDAY_TEMPLATE_COLUMNS, index=None,
            placeholder="dia de la setmana",
            format_func=lambda w: _WEEKDAY_NAMES[WEEKDAY_TEMPLATE_COLUMNS.index(w)],
            key=f"bshift_wd_{nonce}",
        )
        day = c_day.date_input(
            "…o només el dia", value=None, format="DD/MM/YYYY",
            key=f"bshift_day_{nonce}",
        )
        franja = c_fr.selectbox(
            "Franja", list(_FRANJA_NAMES), index=None, placeholder="franja",
            format_func=lambda f: _FRANJA_NAMES[f], key=f"bshift_fr_{nonce}",
        )
        if c_btn.form_submit_button("Afegir", width="stretch"):
            if not prof or not franja:
                st.error("Tria el facultatiu i la franja.")
            elif bool(weekday) == bool(day):
                st.error("Tria un dia de la setmana o un dia concret (només un dels dos).")
            else:
                add_blocked_shift(shifts_path, prof, franja, weekday=weekday or "", day=day)
                st.session_state["bshift_nonce"] = nonce + 1
                st.rerun()

    rows = load_blocked_shifts(shifts_path)
    if rows.empty:
        st.caption("Cap franja bloquejada.")
        return
    for r in rows.itertuples(index=False):
        c_txt, c_del = st.columns([5, 1], vertical_alignment="center")
        c_txt.markdown(f"**{r.professional_id}** · {blocked_shift_label(r)}")
        if c_del.button(
            "Treure",
            key=f"bshift_del_{r.professional_id}_{r.weekday or r.day}_{r.franja}",
            width="stretch",
        ):
            remove_blocked_shift(
                shifts_path, r.professional_id, r.franja, weekday=r.weekday, day=r.day,
            )
            st.rerun()
