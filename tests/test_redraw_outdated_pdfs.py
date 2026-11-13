"""Després d'actualitzar el programa amb un disseny de PDF nou, els PDF ja
generats (més antics que el codi que els dibuixa) es tornen a dibuixar
sols, un sol cop; els que ja són nous no es toquen."""

import os
import time

from streamlit.testing.v1 import AppTest

import src.ui.planning_calendar_tabs as tabs


def _script(base: str) -> None:
    from pathlib import Path
    import src.ui.planning_calendar_tabs as t
    b = Path(base)
    t._redraw_outdated_pdfs(b / "schedule.csv", b / "professionals.csv", b, 2026, [11, 12])


def test_only_old_pdfs_are_redrawn_once(tmp_path, monkeypatch):
    (tmp_path / "schedule.csv").write_text("day\n")
    pdf_dir = tmp_path / "entre_setmana"
    pdf_dir.mkdir()
    old = pdf_dir / "general_calendar_2026_11.pdf"
    new = pdf_dir / "general_calendar_2026_12.pdf"
    old.write_bytes(b"%PDF")
    new.write_bytes(b"%PDF")
    os.utime(old, (946684800, 946684800))  # any 2000: anterior al codi
    future = time.time() + 3600
    os.utime(new, (future, future))
    calls = []
    monkeypatch.setattr(
        tabs, "export_general_weekday_pdf",
        lambda schedule, professionals, out_dir, year, months, container=None: calls.append(months),
    )
    at = AppTest.from_function(_script, args=(str(tmp_path),), default_timeout=30).run()
    assert not at.exception
    at.run()  # un altre clic: no es torna a intentar
    assert calls == [[11]]
