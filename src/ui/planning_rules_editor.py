"""Editor de regles d'equilibri setmanal."""
from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.planning_rules import PlanningRules
from src.ui.table_state import (
    autosave_draft_if_changed,
    data_editor_height,
    table_draft,
)


_RULES_PATH = Path("data/planning_rules.csv")

_DAY_LABELS = {
    5: "Setmana completa (5 dies)",
    4: "Setmana de 4 dies",
    3: "Setmana de 3 dies",
    2: "Setmana de 2 dies",
    1: "Setmana d'1 dia",
}


def _load_rules(rules_path: Path) -> PlanningRules:
    return PlanningRules.from_csv(rules_path)


def _rules_to_dataframe(rules: PlanningRules) -> pd.DataFrame:
    """Construeix el DataFrame de l'editor exposant 3 valors per fila:
    dies presencials, dies no presencials i dies laborables totals.
    Internament, `target_machines = dies_pres + dies_no_pres` i
    `target_presential = dies_pres`."""
    return pd.DataFrame([
        {
            "active_days": days,
            "setmana": _DAY_LABELS[days],
            "dies_presencials": rules.target_presential.get(days, 0),
            "dies_no_presencials": max(
                0,
                rules.target_machines.get(days, 0) - rules.target_presential.get(days, 0),
            ),
        }
        for days in range(5, 0, -1)
    ])


def _rules_from_dataframe(df: pd.DataFrame) -> PlanningRules:
    """Build PlanningRules from the edited DataFrame.
    `target_machines = dies_presencials + dies_no_presencials`, clampejat
    a [0, active_days]. `target_presential = dies_presencials`."""
    target_machines: dict[int, int] = {}
    target_presential: dict[int, int] = {}
    for _, row in df.iterrows():
        days = int(row["active_days"])
        pres = max(0, int(row.get("dies_presencials", 0)))
        no_pres = max(0, int(row.get("dies_no_presencials", 0)))
        # Clampegem perquè PRES + NO_PRES no superi els dies laborables.
        if pres + no_pres > days:
            # Prioritzem mantenir el PRES; reduim NO_PRES si cal.
            no_pres = max(0, days - pres)
            if pres > days:
                pres = days
                no_pres = 0
        target_machines[days] = pres + no_pres
        target_presential[days] = pres
    return PlanningRules(
        target_machines=target_machines,
        target_presential=target_presential,
    )


_MODE_LABELS = {
    "none": "No equilibrar",
    "presencial": "Equilibrar per càrrega presencial setmanal",
    "total": "Equilibrar per càrrega total setmanal",
    "mensual_presencial": "Equilibrar per càrrega presencial mensual",
    "mensual_total": "Equilibrar per càrrega total mensual",
    "activitat": "Equilibrar per càrrega d'una activitat concreta",
    "personalitzat": "Personalitzar (taula per tipus de setmana)",
}
_MODE_ORDER = [
    "none", "presencial", "total",
    "mensual_presencial", "mensual_total", "activitat", "personalitzat",
]
_MODE_HELP = {
    "none": "El solver segueix NOMÉS les franges i l'equitat mensual entre "
            "facultatius. Cap objectiu setmanal.",
    "presencial": "Cada setmana, la càrrega PRESENCIAL real es reparteix "
                  "automàticament entre els facultatius actius, proporcional "
                  "a la jornada. Les no presencials queden lliures (l'equitat "
                  "mensual ja les equilibra).",
    "total": "Cada setmana, el TOTAL de màquines es reparteix automàticament "
             "(presencials i no presencials juntes; la barreja la determinen "
             "les franges).",
    "mensual_presencial": "La càrrega PRESENCIAL de TOT EL MES es reparteix "
                          "proporcionalment a la jornada, sense cap objectiu "
                          "per setmana: un facultatiu pot carregar-se més una "
                          "setmana i menys una altra mentre el mes quadri.",
    "mensual_total": "El TOTAL de màquines de TOT EL MES es reparteix "
                     "proporcionalment a la jornada, sense cap objectiu per "
                     "setmana (presencials i no presencials juntes).",
    "activitat": "Criteri PRINCIPAL: les instàncies de l'activitat triada "
                 "es reparteixen equitativament entre els facultatius "
                 "elegibles al llarg del mes, proporcionalment a la "
                 "jornada. En SEGON terme, la resta de màquines del mes "
                 "també s'equilibra entre tots els facultatius.",
    "personalitzat": "Tu fixes els dies presencials i no presencials per "
                     "tipus de setmana (comportament clàssic).",
}


def _weekday_activity_options() -> list[str]:
    """Activitats candidates per al mode «activitat»: els slots del catàleg
    actius entre setmana (els que apareixen a les franges), SENSE les
    revisions — tenen assignació pròpia (continuïtat + equilibri de
    revisions) i equilibrar-les des d'aquí crearia objectius en conflicte."""
    from src.services.slot_catalog import (
        load_slot_catalog,
        review_slot_ids,
        weekday_slot_ids,
    )
    try:
        catalog = load_slot_catalog(Path("data/slot_catalog.csv"))
    except Exception:
        return []
    reviews = {str(r).strip().upper() for r in review_slot_ids(catalog)}
    return [
        s for s in weekday_slot_ids(catalog)
        if str(s).strip().upper() not in reviews
    ]


def render_planning_rules_editor(rules_path: Path = _RULES_PATH) -> PlanningRules:
    """Render the balance rules editor. Returns current PlanningRules."""
    rules_path = Path(rules_path)
    rules = _load_rules(rules_path)

    mode_choice = st.selectbox(
        "Mode d'equilibri",
        _MODE_ORDER,
        index=_MODE_ORDER.index(rules.mode) if rules.mode in _MODE_ORDER else 2,
        format_func=lambda m: _MODE_LABELS[m],
        key="planning_rules_mode",
        help="Per defecte: equilibrar per càrrega total setmanal. En "
             "generar, si hi ha un mode actiu, veuràs els canvis que les "
             "regles volen fer sobre el calendari de les franges i els "
             "hauràs d'acceptar o descartar.",
    )
    st.caption(_MODE_HELP[mode_choice])
    if mode_choice != rules.mode:
        rules.mode = mode_choice
        rules.to_csv(rules_path)
        st.toast(f"Mode d'equilibri: {_MODE_LABELS[mode_choice]}", icon="⚖️")

    if mode_choice == "activitat":
        options = _weekday_activity_options()
        if not options:
            st.warning(
                "No hi ha activitats al catàleg entre setmana. Crea-les "
                "primer a la pestanya de Franges."
            )
            return rules
        current = rules.balance_activity if rules.balance_activity in options else None
        if rules.balance_activity and current is None:
            st.warning(
                f"L'activitat guardada «{rules.balance_activity}» ja no és "
                "al catàleg. Tria'n una altra — mentrestant, l'equilibri "
                "per activitat no s'aplicarà."
            )
        # Placeholder mentre no hi ha cap tria vàlida: mai persistim una
        # activitat que l'usuari no hagi seleccionat explícitament.
        display_options = options if current is not None else ["", *options]
        activity_choice = st.selectbox(
            "Activitat a equilibrar",
            display_options,
            index=display_options.index(current) if current is not None else 0,
            format_func=lambda v: v or "— tria una activitat —",
            key="planning_rules_balance_activity",
            help="El solver reparteix les instàncies d'aquesta activitat "
                 "entre els facultatius elegibles, proporcionalment a la "
                 "jornada de cadascú.",
        )
        if not activity_choice:
            st.info(
                "Sense activitat triada, en generar no s'aplicarà cap "
                "equilibri per activitat."
            )
        elif activity_choice != rules.balance_activity:
            rules.balance_activity = activity_choice
            rules.to_csv(rules_path)
            st.toast(f"Equilibrant per: {activity_choice}", icon="⚖️")

    if mode_choice != "personalitzat":
        return rules

    _pers = st.expander("Personalitzar la taula setmanal", expanded=True)
    _pers.caption(
        "Per a cada tipus de setmana (segons dies laborables), defineix "
        "el nombre objectiu de dies presencials i de dies no presencials. "
        "El solver intentarà fer-la complir per a tots els facultatius."
    )

    # Signatura nomes de context (path del fitxer) — NO depen del contingut
    # del CSV. Aixo es clau: si depengues, despres de cada autosave la
    # signatura canviaria, table_draft resetejaria el draft, i el
    # `st.data_editor` perdria els pending edits acumulats (efecte
    # «cal escriure dos cops al següent camp»).
    columns = ["active_days", "setmana", "dies_presencials", "dies_no_presencials"]
    _rules_df = _rules_to_dataframe(rules)
    editor_df = table_draft(
        "planning_rules_draft",
        _rules_df,
        columns,
        f"planning_rules|{rules_path.resolve()}",
    )

    edited = _pers.data_editor(
        editor_df,
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        height=data_editor_height(len(editor_df)),
        key="planning_rules_editor",
        column_order=["setmana", "dies_presencials", "dies_no_presencials"],
        column_config={
            "setmana": st.column_config.TextColumn(
                "Dies laborables (setmana)", disabled=True,
                help="Nombre total de dies laborables a la setmana del "
                     "facultatiu (segons jornada efectiva).",
            ),
            "dies_presencials": st.column_config.NumberColumn(
                "Dies presencials", min_value=0, max_value=10, step=1,
                help="Dies amb assignació PRESENCIAL per facultatiu i setmana.",
            ),
            "dies_no_presencials": st.column_config.NumberColumn(
                "Dies no presencials", min_value=0, max_value=10, step=1,
                help="Dies amb assignació NO PRESENCIAL ordinària per "
                     "facultatiu i setmana (peonades a part).",
            ),
        },
    )

    updated_rules = _rules_from_dataframe(edited)
    # Preservem mode i activitat: `_rules_from_dataframe` només reconstrueix
    # la taula — sense això, l'autosave de la taula escriuria el mode per
    # defecte («total») al CSV tot i que el desplegable diu «personalitzat».
    updated_rules.mode = mode_choice
    updated_rules.balance_activity = rules.balance_activity

    def _persist(_df: pd.DataFrame) -> None:
        updated_rules.to_csv(rules_path)

    autosave_draft_if_changed(
        "planning_rules",
        edited[["active_days", "dies_presencials", "dies_no_presencials"]],
        ["active_days", "dies_presencials", "dies_no_presencials"],
        _persist,
    )
    return updated_rules
