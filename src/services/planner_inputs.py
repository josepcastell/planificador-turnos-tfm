from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.domain.schedule_format import slot_sort_key
from src.services.table_io import read_table


WEEKDAY_TEMPLATE_COLUMNS = [
    "weekday_name",
    "franja",
    "slot_id",
    "presentiality",
    "work_mode",
    "required_staff",
    "is_active",
    "doubled",
    "linked_to",
    "week_interval",
    "week_offset",
]


@dataclass(frozen=True)
class PlannerInputs:
    professionals_df: pd.DataFrame
    professional_options: list[str]
    all_professional_options: list[str]
    templates_df: pd.DataFrame
    eligibility_slots_df: pd.DataFrame
    existing_slots: list[str]
    weekday_eligibility_slots: list[str]


def _migrate_catalog_doubled_to_template(
    templates_df: pd.DataFrame,
    weekly_templates_path: Path,
    catalog_path: Path = Path("data/slot_catalog.csv"),
) -> pd.DataFrame:
    """Si el template no té cap fila doblada però el catàleg encara conserva
    el flag (versions antigues), el propaga per slot_id i persisteix.

    TODO(transitional): eliminable un cop totes les sessions tinguin el
    `doubled` migrat al template."""
    if templates_df.empty or not (templates_df["doubled"] == 0).all():
        return templates_df
    if not catalog_path.exists():
        return templates_df
    from src.services.slot_catalog import doubled_extras_by_slot, load_slot_catalog
    from src.services.input_tables import save_weekly_slot_templates

    catalog_doubled = doubled_extras_by_slot(load_slot_catalog(catalog_path))
    if not any(v > 0 for v in catalog_doubled.values()):
        return templates_df
    templates_df = templates_df.copy()
    slot_norm = templates_df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    templates_df["doubled"] = slot_norm.map(catalog_doubled).fillna(0).astype(int).clip(0, 1)
    save_weekly_slot_templates(templates_df, weekly_templates_path)
    return templates_df


def load_planner_inputs(
    professionals_path: Path,
    weekly_templates_path: Path,
    eligibility_path: Path,
    catalog_weekday_slots: list[str] | None = None,
) -> PlannerInputs:
    professionals_df = read_table(
        professionals_path,
        ["professional_id", "name", "doubled_machines", "non_working_weekdays",
         "fallback", "presence_mode"],
    )
    professionals_df["non_working_weekdays"] = professionals_df["non_working_weekdays"].fillna("").astype(str)
    professionals_df["fallback"] = (
        pd.to_numeric(professionals_df["fallback"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    )
    professionals_df["presence_mode"] = (
        professionals_df["presence_mode"].fillna("").astype(str).str.strip().str.upper()
    )
    professional_options = sorted(
        p
        for p in professionals_df["professional_id"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .tolist()
        if p and p != "NONE"
    )
    all_professional_options = sorted(set(professional_options))

    templates_df = read_table(weekly_templates_path, WEEKDAY_TEMPLATE_COLUMNS)
    templates_df["required_staff"] = (
        pd.to_numeric(templates_df["required_staff"], errors="coerce")
        .fillna(1)
        .astype(int)
        .clip(lower=1, upper=6)
    )
    templates_df["is_active"] = (
        pd.to_numeric(templates_df["is_active"], errors="coerce")
        .fillna(1)
        .astype(int)
    )
    templates_df["doubled"] = (
        pd.to_numeric(templates_df["doubled"], errors="coerce")
        .fillna(0)
        .astype(int)
        .clip(0, 1)
    )
    templates_df = _migrate_catalog_doubled_to_template(templates_df, weekly_templates_path)
    # ── NOU MODEL DE DOBLAT ───────────────────────────────────────────────
    # Una activitat doblada s'expressa ara com a DUES files independents al
    # template (1 PRES + 1 NP) en comptes d'1 fila amb doubled=1 que
    # s'expandia a 2 posicions al runtime. Si llegim un CSV legacy amb
    # files doubled=1 i presentiality=PRESENCIAL, hi afegim la sibling
    # NO_PRESENCIAL en memòria. El CSV del disc es regenerarà al primer
    # save explícit. Així cada fila del template és, des d'aquest punt
    # endavant, una activitat única editable / eliminable per separat.
    legacy_pres_doubled = (
        (templates_df["doubled"] == 1)
        & (templates_df["presentiality"].astype(str).str.upper() == "PRESENCIAL")
    )
    if legacy_pres_doubled.any():
        siblings = templates_df.loc[legacy_pres_doubled].copy()
        siblings["presentiality"] = "NO_PRESENCIAL"
        siblings["doubled"] = 0
        templates_df = pd.concat([templates_df, siblings], ignore_index=True)
        templates_df = templates_df.drop_duplicates(
            subset=["weekday_name", "franja", "slot_id", "presentiality", "work_mode"],
            keep="last",
        ).reset_index(drop=True)
    templates_df["doubled"] = 0  # ja no condiciona el comportament

    # ── MODEL DE PEONADES ─────────────────────────────────────────────────
    # El `work_mode` del template ja no diferencia peonada vs ordinària:
    # tot és NORMAL al solver. Les peonades són una SORTIDA del solver
    # (boolean `pn[p, sk]` a `_add_peonada_monthly_cap`): per cada
    # facultatiu, el solver pot marcar fins a N NO_PRES/mes com a peonada
    # (cap HARD), amb N proporcional a la jornada. Si el CSV legacy
    # encara té PEONADA, el normalitzem aquí en memòria perquè el solver
    # mai ho vegi. El CSV del disc es regenerarà al primer save de
    # templates (és cosmètic).
    if "work_mode" in templates_df.columns:
        templates_df["work_mode"] = (
            templates_df["work_mode"].fillna("NORMAL").astype(str).str.upper()
        )
        templates_df.loc[templates_df["work_mode"] != "NORMAL", "work_mode"] = "NORMAL"

    # NOTA: anteriorment es sembraven aquí files Mon-Fri MATI per defecte per
    # cada slot del catàleg sense files al template. S'ha tret per evitar
    # que apareguin franges fixes sense que l'usuari les hagi afegit. Les
    # franges es configuren explícitament a Restriccions › Franges de treball.

    eligibility_slots_df = read_table(eligibility_path, ["professional_id", "slot_id", "allowed"])
    existing_slots = sorted(
        {s for s in (catalog_weekday_slots or []) if s and s not in GUARDS_RESERVED_SLOT_IDS},
        key=slot_sort_key,
    )
    weekday_eligibility_slots = existing_slots

    return PlannerInputs(
        professionals_df=professionals_df,
        professional_options=professional_options,
        all_professional_options=all_professional_options,
        templates_df=templates_df,
        eligibility_slots_df=eligibility_slots_df,
        existing_slots=existing_slots,
        weekday_eligibility_slots=weekday_eligibility_slots,
    )
