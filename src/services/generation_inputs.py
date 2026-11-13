from pathlib import Path

from src.domain.schemas import CSV_HEADERS
from src.services.calendar_inputs import load_base_calendar_overrides, save_base_calendar_overrides
from src.services.table_io import ensure_csv_file


def _cols(schema_key: str) -> list[str]:
    """Capçalera des de la font única (domain.schemas.CSV_HEADERS) — mai
    llistes re-declarades aquí que puguin divergir de l'esquema real."""
    return CSV_HEADERS[schema_key].strip().split(",")


def ensure_generation_inputs(
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    absences_path: Path,
    guards_path: Path,
    manual_assignments_path: Path,
) -> None:
    ensure_csv_file(public_holidays_path, _cols("data/derived/public_holidays_{year}.csv"))
    save_base_calendar_overrides(base_calendar_overrides_path, load_base_calendar_overrides(base_calendar_overrides_path))
    ensure_csv_file(absences_path, _cols("data/absences/assignments.csv"))
    ensure_csv_file(guards_path, _cols("data/guards/assignments.csv"))
    ensure_csv_file(manual_assignments_path, _cols("data/weekday/preassignments.csv"))
