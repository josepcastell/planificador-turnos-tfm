from pathlib import Path
import re
import sys

from src.tools.apply_guards_to_calendar import apply_guards_to_calendar
from src.tools.apply_absences_to_calendar import apply_absences_to_calendar
from src.tools.build_unavailability_layer import build_unavailability_layer
from src.tools.split_unavailability_layer import split_unavailability_layer
from src.tools.reconcile_preassignments import reconcile_preassignments


def prepare_operational_constraints(
    base_calendar_csv: str,
    guards_csv: str,
    absences_csv: str,
    weekday_unavailability_csv: str,
    weekday_preassignments_csv: str,
    derived_dir: str,
) -> None:
    derived = Path(derived_dir)
    derived.mkdir(parents=True, exist_ok=True)
    match = re.search(r"(\d{4})", Path(base_calendar_csv).stem)
    year = int(match.group(1)) if match else 2026

    guard_constraints_csv = str(derived / f"guard_constraints_{year}.csv")
    unavailability_from_absences_csv = str(derived / f"unavailability_from_absences_{year}.csv")
    unavailability_csv = str(derived / f"unavailability_{year}.csv")
    unavailability_weekday_csv = str(derived / f"unavailability_weekday_{year}.csv")
    preassignments_weekday_csv = str(derived / f"preassignments_weekday_{year}.csv")

    print("[1/5] Aplicando guardias y refuerzos...")
    apply_guards_to_calendar(
        base_calendar_csv=base_calendar_csv,
        guards_csv=guards_csv,
        output_constraints_csv=guard_constraints_csv,
    )

    print("[2/5] Aplicando ausencias...")
    apply_absences_to_calendar(
        base_calendar_csv=base_calendar_csv,
        absences_csv=absences_csv,
        output_unavailability_csv=unavailability_from_absences_csv,
    )

    print("[3/5] Construyendo capa unificada de indisponibilidades...")
    build_unavailability_layer(
        weekday_unavailability_csv=weekday_unavailability_csv,
        weekend_unavailability_csv="",
        absences_unavailability_csv=unavailability_from_absences_csv,
        guard_constraints_csv=guard_constraints_csv,
        output_csv=unavailability_csv,
    )

    print("[4/5] Separando indisponibilidades laborables...")
    split_unavailability_layer(
        unavailability_csv=unavailability_csv,
        base_calendar_csv=base_calendar_csv,
        weekday_output_csv=unavailability_weekday_csv,
    )

    print("[5/5] Reconciliando preasignaciones laborables...")
    reconcile_preassignments(
        preassignments_csv=weekday_preassignments_csv,
        unavailability_csv=unavailability_weekday_csv,
        output_csv=preassignments_weekday_csv,
    )

    print("\nPreparación operativa completada correctamente.")
    print(f"- {guard_constraints_csv}")
    print(f"- {unavailability_from_absences_csv}")
    print(f"- {unavailability_csv}")
    print(f"- {unavailability_weekday_csv}")
    print(f"- {preassignments_weekday_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 7:
        print(
            "Uso: python -m src.tools.prepare_operational_constraints "
            "<base_calendar_csv> <guards_csv> <absences_csv> "
            "<weekday_unavailability_csv> "
            "<weekday_preassignments_csv> <derived_dir>"
        )
        sys.exit(1)

    prepare_operational_constraints(
        base_calendar_csv=sys.argv[1],
        guards_csv=sys.argv[2],
        absences_csv=sys.argv[3],
        weekday_unavailability_csv=sys.argv[4],
        weekday_preassignments_csv=sys.argv[5],
        derived_dir=sys.argv[6],
    )
