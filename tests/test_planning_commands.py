"""Tests per al pipeline portable (sense shell).

L'objectiu d'aquestes proves és garantir que:
1) Mai s'invoca `bash` ni `cmd.exe` — les comandes són sempre llistes
   d'argv preparades per passar a `subprocess.Popen(shell=False)`.
2) S'usa `sys.executable` (l'intèrpret actual), no `python` literal,
   per evitar dependre del PATH (escull típic a Windows).
3) Les flags i arguments es preserven a la cantonada esperada
   (`--year`, `--stability-from`, `--general-only`, `--weekdays-only`,
   `--by-professional`).

Si aquestes propietats es trenquen, el pipeline deixa de funcionar al
PC de la feina (Windows sense WSL) i fallen totes les accions de
"Generar" i "Exportar PDF"."""

import sys
from pathlib import Path

from src.services.planning_commands import (
    by_professional_pdf_steps,
    general_pdf_export_steps,
    generate_module_calendars_step,
    prepare_base_calendar_step,
    prepare_operational_constraints_step,
    prepare_pipeline_steps,
    weekday_planning_step,
)


def _is_python_invocation(argv: list[str]) -> bool:
    """Comprova que la comanda invoca Python via -m amb l'intèrpret actual."""
    return (
        isinstance(argv, list)
        and len(argv) >= 3
        and argv[0] == sys.executable
        and argv[1] == "-m"
    )


class TestPyHelperContract:
    def test_no_bash_in_any_step_builder(self):
        # Ningú no pot retornar res que comenci per 'bash', 'sh', 'cmd' o
        # tingui '&&' barrejat al string — totes són traces dels shell-wrappers
        # antics que feien fallar Windows natiu.
        argvs: list[list[str]] = [
            prepare_base_calendar_step(2026, Path("ph.csv"), Path("ov.csv")),
            generate_module_calendars_step(2026, Path("base.csv")),
            prepare_operational_constraints_step(Path("base.csv")),
            weekday_planning_step(2026, 1, 12),
            weekday_planning_step(2026, 1, 12, stability_from=Path("stab.csv")),
        ]
        argvs.extend(general_pdf_export_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [1]
        ))
        argvs.extend(general_pdf_export_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [1, 2, 3]
        ))
        argvs.extend(by_professional_pdf_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [3, 7]
        ))
        for argv in argvs:
            assert _is_python_invocation(argv), f"Argv no és Python via -m: {argv}"
            joined = " ".join(argv)
            for forbidden in ("bash", "&&", ";", "|"):
                # `bash` apareix legítimament en cap argument; els metacaràcters
                # de shell tampoc.
                assert forbidden not in joined.split(), (
                    f"Token de shell prohibit «{forbidden}» trobat: {argv}"
                )


class TestPrepareBaseCalendarStep:
    def test_argv_shape(self):
        argv = prepare_base_calendar_step(2026, Path("h.csv"), Path("o.csv"))
        assert _is_python_invocation(argv)
        assert argv[2] == "src.tools.prepare_base_calendar"
        assert "2026" in argv
        assert "h.csv" in argv
        assert "o.csv" in argv


class TestWeekdayPlanningStep:
    def test_without_stability(self):
        argv = weekday_planning_step(2026, 3, 9)
        assert _is_python_invocation(argv)
        assert argv[2] == "src.tools.generate_planning_part"
        assert argv[3] == "weekday"
        assert "--year" in argv and "2026" in argv
        assert "--start-month" in argv and "3" in argv
        assert "--end-month" in argv and "9" in argv
        assert "--stability-from" not in argv

    def test_with_stability(self):
        argv = weekday_planning_step(2026, 3, 9, stability_from=Path("prev.csv"))
        assert "--stability-from" in argv
        assert "prev.csv" in argv


class TestPreparePipelineSteps:
    def test_returns_three_steps(self):
        steps = prepare_pipeline_steps(
            2026, Path("h.csv"), Path("o.csv"), Path("b.csv")
        )
        assert len(steps) == 3
        modules = [s[2] for s in steps]
        assert modules == [
            "src.tools.prepare_base_calendar",
            "src.tools.generate_module_calendars",
            "src.tools.prepare_operational_constraints",
        ]


class TestGeneralPdfExportSteps:
    def test_single_month_uses_monthly_tool(self):
        steps = general_pdf_export_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [5],
        )
        assert len(steps) == 1
        assert steps[0][2] == "src.tools.export_monthly_pdfs"
        assert "--general-only" in steps[0]

    def test_multi_month_uses_year_tool_with_range(self):
        steps = general_pdf_export_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [3, 4, 5],
        )
        assert len(steps) == 1
        argv = steps[0]
        assert argv[2] == "src.tools.export_year_pdfs"
        assert "--start-month" in argv and "3" in argv
        assert "--end-month" in argv and "5" in argv

    def test_weekdays_only_flag(self):
        steps = general_pdf_export_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [1],
            weekdays_only=True,
        )
        assert "--weekdays-only" in steps[0]


class TestByProfessionalPdfSteps:
    def test_one_step_per_month(self):
        steps = by_professional_pdf_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [4, 7, 11],
        )
        assert len(steps) == 3
        for argv in steps:
            assert _is_python_invocation(argv)
            assert argv[2] == "src.tools.export_monthly_pdfs"
            assert "--by-professional" in argv

    def test_empty_months_returns_empty_list(self):
        # Cas de defensa: cap mes seleccionat → cap comanda (no crash).
        steps = by_professional_pdf_steps(
            Path("s.csv"), Path("p.csv"), Path("o"), 2026, [],
        )
        assert steps == []
