from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


EXCLUDE_DIRS = {".git", ".venv", "__pycache__", "snapshots"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def copy_project(source: Path, target: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        ignored = set()
        for name in names:
            if name in EXCLUDE_DIRS:
                ignored.add(name)
            elif Path(name).suffix in EXCLUDE_SUFFIXES:
                ignored.add(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore)
    outputs = target / "outputs"
    if outputs.exists():
        shutil.rmtree(outputs)
    outputs.mkdir(parents=True, exist_ok=True)


def run(command: list[str], cwd: Path) -> None:
    printable = " ".join(command)
    print(f"$ {printable}")
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if completed.returncode != 0:
        if completed.stdout:
            print("\nSTDOUT:\n" + completed.stdout)
        if completed.stderr:
            print("\nSTDERR:\n" + completed.stderr)
        raise RuntimeError(f"Command failed: {printable}")


def assert_csv(path: Path, min_rows: int = 1) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise AssertionError(f"Missing or empty CSV: {path}")
    df = pd.read_csv(path)
    if len(df) < min_rows:
        raise AssertionError(f"CSV has fewer rows than expected: {path}")
    return df


def assert_pdf(path: Path) -> None:
    if not path.exists() or path.stat().st_size < 1024:
        raise AssertionError(f"Missing or too small PDF: {path}")


def smoke(project_root: Path, year: int, month: int, keep: bool) -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix="planner_smoke_"))
    workdir = temp_root / "project"
    copy_project(project_root, workdir)

    python = sys.executable
    public_holidays = f"data/derived/public_holidays_{year}.csv"
    base_overrides = f"data/base_calendar_overrides_{year}.csv"
    base_calendar = f"data/base_calendar_{year}.csv"

    try:
        run([
            python,
            "-m",
            "src.tools.prepare_base_calendar",
            public_holidays,
            str(year),
            base_overrides,
            base_calendar,
            "data/weekday/day_info.csv",
        ], workdir)
        run([
            python,
            "-m",
            "src.tools.generate_module_calendars",
            base_calendar,
            str(year),
            "data/weekday/day_info.csv",
            "data/weekday/calendar_slots.csv",
        ], workdir)
        run([
            python,
            "-m",
            "src.tools.prepare_operational_constraints",
            base_calendar,
            "data/guards/assignments.csv",
            "data/absences/assignments.csv",
            "data/weekday/unavailability.csv",
            "data/weekday/preassignments.csv",
            "data/derived",
        ], workdir)
        run([
            python,
            "-m",
            "src.tools.generate_planning_part",
            "weekday",
            "--year",
            str(year),
            "--start-month",
            str(month),
            "--end-month",
            str(month),
        ], workdir)

        weekday_schedule = assert_csv(workdir / "outputs/schedule_weekday.csv")
        assert_csv(workdir / "outputs/metrics_weekday.csv")

        weekday_days = pd.to_datetime(weekday_schedule["day"], errors="coerce")
        if not weekday_days.dt.weekday.dropna().isin(range(5)).all():
            raise AssertionError("Weekday schedule contains non-working-week days")

        run([
            python,
            "-m",
            "src.tools.export_monthly_pdfs",
            "outputs/schedule_weekday.csv",
            "data/professionals.csv",
            str(year),
            str(month),
            "outputs/pdf_weekday",
            "--general-only",
            "--weekdays-only",
        ], workdir)

        assert_pdf(workdir / f"outputs/pdf_weekday/general_calendar_{year}_{month:02d}.pdf")
        print(f"\nSmoke generation completed in: {workdir}")
        return workdir
    except Exception:
        print(f"\nSmoke workspace kept for inspection: {workdir}")
        raise
    finally:
        if not keep:
            shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an isolated end-to-end generation smoke test.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=1)
    parser.add_argument("--keep", action="store_true", help="Keep the temporary workspace after finishing.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    smoke(project_root, args.year, args.month, args.keep)


if __name__ == "__main__":
    main()
