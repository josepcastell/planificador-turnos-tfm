"""Construcció d'invocacions del pipeline de tools.

Cada funció retorna una llista de comandes (cadascuna en format argv:
`list[str]`) llestes per passar-les a `subprocess.Popen`. NO s'usa cap
shell intermèdia — així funciona idènticament a Linux, macOS i Windows
natiu sense dependre de bash, WSL ni Git Bash. La cadena seqüencial
(equivalent a `&&` de bash) la fa `run_and_store`, executant les
comandes una a una i aturant-se a la primera que falla.

Usem `sys.executable` per invocar Python: així la subprocess utilitza
exactament el mateix intèrpret que serveix Streamlit i no depèn que
`python` estigui al PATH (un escull típic a Windows).
"""

import sys
from pathlib import Path


def _py(*args) -> list[str]:
    """Argv per a `<python_actual> -m <args...>`."""
    return [sys.executable, "-m", *[str(a) for a in args]]


def prepare_base_calendar_step(
    year: int,
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
) -> list[str]:
    return _py(
        "src.tools.prepare_base_calendar",
        public_holidays_path, year, base_calendar_overrides_path,
        f"data/base_calendar_{year}.csv",
        "data/weekday/day_info.csv",
    )


def generate_module_calendars_step(year: int, base_calendar_path: Path) -> list[str]:
    return _py(
        "src.tools.generate_module_calendars",
        base_calendar_path, year,
        "data/weekday/day_info.csv",
        "data/weekday/calendar_slots.csv",
    )


def prepare_operational_constraints_step(base_calendar_path: Path) -> list[str]:
    return _py(
        "src.tools.prepare_operational_constraints",
        base_calendar_path,
        "data/guards/assignments.csv",
        "data/absences/assignments.csv",
        "data/weekday/unavailability.csv",
        "data/weekday/preassignments.csv",
        "data/derived",
    )


def prepare_pipeline_steps(
    year: int,
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    base_calendar_path: Path,
) -> list[list[str]]:
    """Les 3 passes prèvies a la generació del planning: calendari base,
    calendaris per mòdul, restriccions operatives."""
    return [
        prepare_base_calendar_step(year, public_holidays_path, base_calendar_overrides_path),
        generate_module_calendars_step(year, base_calendar_path),
        prepare_operational_constraints_step(base_calendar_path),
    ]


def weekday_planning_step(
    year: int,
    scope_start_month: int,
    scope_end_month: int,
    stability_from: Path | None = None,
    initial: bool = False,
    keep_restriction: str | None = None,
    max_seconds: int | None = None,
    warm_start: bool = False,
) -> list[str]:
    """Generació del planning d'entre setmana per a un rang de mesos.
    Si es passa `stability_from`, el solver minimitza canvis respecte
    al schedule indicat (regeneració definitiva).
    Si `initial=True`, ignora les restriccions opcionals (vegeu
    `_strip_optional_restrictions` a generate_planning_part).
    Si `keep_restriction` es indicat, aplica NOMÉS aquella restricció
    (la resta s'esborren). S'usa pels botons per-desplegable.
    Si `max_seconds` es indicat, fixa el pressupost de temps del solver
    per mes (PLANNER_SOLVER_MAX_SECONDS) — més temps = més convergència."""
    args: list = [
        "src.tools.generate_planning_part",
        "weekday",
        "--year", year,
        "--start-month", scope_start_month,
        "--end-month", scope_end_month,
    ]
    if stability_from is not None:
        args.extend(["--stability-from", stability_from])
    if initial:
        args.append("--initial")
    if keep_restriction:
        args.extend(["--keep-restriction", keep_restriction])
    if max_seconds is not None:
        args.extend(["--max-seconds", max_seconds])
    if warm_start:
        args.append("--warm-start")
    return _py(*args)


def general_pdf_export_steps(
    schedule_path: Path,
    professionals_path: Path,
    output_dir: Path,
    selected_year: int,
    selected_months: list[int],
    weekdays_only: bool = False,
    show_operational_overlays: bool = True,
) -> list[list[str]]:
    """PDF clàssic (calendari general). Retorna una llista d'una sola
    comanda per uniformitat amb la resta d'steps.

    `show_operational_overlays=False` afegeix `--no-operational-overlays`
    al CLI per amagar absències/guàrdies/PG al PDF. S'usa per al
    calendari INICIAL (on el solver no les considera)."""
    if len(selected_months) > 1:
        args: list = [
            "src.tools.export_year_pdfs",
            schedule_path, professionals_path, selected_year, output_dir,
            "--start-month", selected_months[0],
            "--end-month", selected_months[-1],
            "--general-only",
        ]
    else:
        args = [
            "src.tools.export_monthly_pdfs",
            schedule_path, professionals_path,
            selected_year, selected_months[0], output_dir,
            "--general-only",
        ]
    if not show_operational_overlays:
        args.append("--no-operational-overlays")
    if weekdays_only:
        args.append("--weekdays-only")
    return [_py(*args)]


def by_professional_pdf_steps(
    schedule_path: Path,
    professionals_path: Path,
    output_dir: Path,
    selected_year: int,
    selected_months: list[int],
) -> list[list[str]]:
    """PDF facultatiu × dies (un per mes seleccionat)."""
    return [
        _py(
            "src.tools.export_monthly_pdfs",
            schedule_path, professionals_path, selected_year, m, output_dir,
            "--by-professional",
        )
        for m in (selected_months or [])
    ]
