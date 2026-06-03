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


def render_planning_rules_editor(rules_path: Path = _RULES_PATH) -> PlanningRules:
    """Render the weekly target rules editor. Returns current PlanningRules."""
    rules_path = Path(rules_path)
    rules = _load_rules(rules_path)

    st.caption(
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

    edited = st.data_editor(
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

    def _persist(_df: pd.DataFrame) -> None:
        updated_rules.to_csv(rules_path)

    autosave_draft_if_changed(
        "planning_rules",
        edited[["active_days", "dies_presencials", "dies_no_presencials"]],
        ["active_days", "dies_presencials", "dies_no_presencials"],
        _persist,
    )
    return updated_rules
