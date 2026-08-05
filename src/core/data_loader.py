from pathlib import Path
import pandas as pd


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path)
    return pd.DataFrame()


def _load_prefer_derived(manual_path: Path, derived_path: Path) -> pd.DataFrame:
    if derived_path.exists() and derived_path.stat().st_size > 0:
        return pd.read_csv(derived_path)
    if manual_path.exists() and manual_path.stat().st_size > 0:
        return pd.read_csv(manual_path)
    return pd.DataFrame()


def _validate_columns(df: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{name}: falten columnes obligatòries: {', '.join(sorted(missing))}"
        )


def load_common_data(base_dir: str = "data") -> dict:
    from src.domain.planning_rules import PlanningRules

    base = Path(base_dir)
    professionals = pd.read_csv(base / "professionals.csv")
    _validate_columns(professionals, {"professional_id"}, "professionals.csv")

    eligibility = pd.read_csv(base / "eligibility.csv")
    _validate_columns(eligibility, {"professional_id", "slot_id", "allowed"}, "eligibility.csv")

    from src.services.comite import load_comite_assignments
    from src.services.slot_catalog import (
        always_presential_slot_ids,
        fixed_assignments_from_catalog,
        load_slot_catalog,
        review_slot_ids,
        slot_area_map,
        slot_link_pairs,
        slot_metric_family_map,
        slot_secondary_ids,
    )
    from src.domain.schedule_format import (
        set_slot_area_overrides,
        set_slot_metric_overrides,
        set_slot_review_overrides,
    )
    from src.services.facultatiu_targets import load_facultatiu_targets
    from src.services.weekly_tolerance import load_presential_tolerance as _load_tolerance
    from src.services.extraordinary_activity import load_extraordinary_cap as _load_extra_cap

    slot_catalog_df = load_slot_catalog(base / "slot_catalog.csv")
    set_slot_area_overrides(slot_area_map(slot_catalog_df))
    set_slot_metric_overrides(slot_metric_family_map(slot_catalog_df))
    set_slot_review_overrides(review_slot_ids(slot_catalog_df))

    return {
        "professionals": professionals,
        "eligibility": eligibility,
        "facultatiu_targets": load_facultatiu_targets(
            base / "metrics" / "facultatiu_targets.csv"
        ),
        "absences": _read_csv_if_exists(base / "absences" / "assignments.csv"),
        "comite": load_comite_assignments(base / "comite" / "assignments.csv"),
        "planning_rules": PlanningRules.from_csv(base / "planning_rules.csv"),
        "presential_tolerance": _load_tolerance(base / "metrics" / "presential_tolerance.txt"),
        "peonada_cap": _load_extra_cap(base / "metrics" / "extraordinary_activity_cap.txt"),
        "slot_links": slot_link_pairs(slot_catalog_df),
        "slot_secondary_ids": slot_secondary_ids(slot_catalog_df),
        "slot_fixed_assignments": fixed_assignments_from_catalog(slot_catalog_df),
        "review_slots": review_slot_ids(slot_catalog_df),
        # Activitats que el solver NO pot convertir en no-presencials
        # (queden fora del flip PRES→NP de les regles d'equilibri).
        "always_presential_slots": always_presential_slot_ids(slot_catalog_df),
    }


def load_weekday_data(
    base_dir: str = "data/weekday",
    derived_dir: str = "data/derived",
    year: int = 2026,
) -> dict:
    base = Path(base_dir)
    derived = Path(derived_dir)

    calendar_slots = pd.read_csv(base / "calendar_slots.csv")
    _validate_columns(calendar_slots, {"day", "slot_id"}, "weekday/calendar_slots.csv")

    day_info = pd.read_csv(base / "day_info.csv")
    _validate_columns(day_info, {"day", "is_working_day"}, "weekday/day_info.csv")

    return {
        "professionals": _read_csv_if_exists(base / "professionals.csv"),
        "calendar_slots": calendar_slots,
        "unavailability": _load_prefer_derived(
            base / "unavailability.csv",
            derived / f"unavailability_weekday_{year}.csv",
        ),
        "preassignments": _load_prefer_derived(
            base / "preassignments.csv",
            derived / f"preassignments_weekday_{year}.csv",
        ),
        "fixed_machines": _read_csv_if_exists(base / "fixed_machines.csv"),
        "day_info": day_info,
    }


