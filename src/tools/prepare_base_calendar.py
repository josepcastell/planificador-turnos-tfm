import sys
from pathlib import Path

from src.tools.build_base_calendar import build_base_calendar
from src.tools.split_base_calendar import split_base_calendar


def prepare_base_calendar(
    import_csv: str,
    year: int,
    overrides_csv: str,
    base_calendar_csv: str,
    weekday_day_info_csv: str,
) -> None:
    Path(base_calendar_csv).parent.mkdir(parents=True, exist_ok=True)
    Path(weekday_day_info_csv).parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/2] Generando calendario base anual {year}...")
    build_base_calendar(
        import_csv=import_csv,
        year=year,
        overrides_csv=overrides_csv,
        output_csv=base_calendar_csv,
    )

    print("[2/2] Separant calendari base en entre setmana...")
    split_base_calendar(
        base_calendar_csv=base_calendar_csv,
        weekday_output=weekday_day_info_csv,
    )

    print("\nCalendario base anual preparado correctamente.")


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(
            "Uso: python -m src.tools.prepare_base_calendar "
            "<import_csv> <year> <overrides_csv> <base_calendar_csv> "
            "<weekday_day_info_csv>"
        )
        sys.exit(1)

    prepare_base_calendar(
        import_csv=sys.argv[1],
        year=int(sys.argv[2]),
        overrides_csv=sys.argv[3],
        base_calendar_csv=sys.argv[4],
        weekday_day_info_csv=sys.argv[5],
    )
