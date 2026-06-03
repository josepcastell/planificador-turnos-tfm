import sys

from src.tools.build_weekday_calendar_from_templates import build_weekday_calendar_from_templates
from src.tools.validate_module_calendar import validate_module_calendar


def generate_module_calendars(
    base_calendar_csv: str,
    year: int,
    weekday_day_info_csv: str,
    weekday_calendar_slots_csv: str,
) -> None:
    print("[1/2] Generant calendari d'entre setmana amb franges...")
    build_weekday_calendar_from_templates(
        base_calendar_csv=base_calendar_csv,
        weekly_templates_csv="data/weekday/weekly_slot_templates.csv",
        overrides_csv=f"data/weekday/template_overrides_{year}.csv",
        output_csv=weekday_calendar_slots_csv,
    )

    print("[2/2] Validando calendario de módulo...")
    validate_module_calendar(
        calendar_slots_csv=weekday_calendar_slots_csv,
        day_info_csv=weekday_day_info_csv,
        expected_working_day=1,
        module_name="weekday",
    )

    print("\nCalendari d'entre setmana generat correctament.")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "Uso: python -m src.tools.generate_module_calendars "
            "<base_calendar_csv> <year> <weekday_day_info_csv> "
            "<weekday_calendar_slots_csv>"
        )
        sys.exit(1)

    generate_module_calendars(
        base_calendar_csv=sys.argv[1],
        year=int(sys.argv[2]),
        weekday_day_info_csv=sys.argv[3],
        weekday_calendar_slots_csv=sys.argv[4],
    )
