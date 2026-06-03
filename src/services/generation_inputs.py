from pathlib import Path

from src.services.calendar_inputs import load_base_calendar_overrides, save_base_calendar_overrides
from src.services.table_io import ensure_csv_file


def ensure_generation_inputs(
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    absences_path: Path,
    guards_path: Path,
    manual_assignments_path: Path,
) -> None:
    ensure_csv_file(public_holidays_path, ["day", "location"])
    save_base_calendar_overrides(base_calendar_overrides_path, load_base_calendar_overrides(base_calendar_overrides_path))
    ensure_csv_file(absences_path, ["absence_type", "professional_id", "start_day", "end_day", "notes"])
    ensure_csv_file(guards_path, ["day", "professional_id", "guard_kind", "notes"])
    ensure_csv_file(
        manual_assignments_path,
        ["professional_id", "day", "franja", "slot_id", "presentiality", "work_mode", "fixed", "source"],
    )
