"""PDF del calendari (i el seu render a l'app): la revisió surt en una fila
pròpia («Revisió») i no com una columna més de cada dia, i la llegenda és
una columna breu a la dreta amb les inicials i el nom dels facultatius."""

import fitz
import pandas as pd

from src.domain.schedule_format import set_slot_review_overrides
from src.tools.export_monthly_pdfs import build_general_calendar_pdf

DAYS = ["2026-12-01", "2026-12-02", "2026-12-03"]


def _pdf_text(tmp_path, monkeypatch) -> str:
    monkeypatch.chdir(tmp_path)  # sense calendari base ni guàrdies: només el PDF
    rows = []
    for d in DAYS:
        rows += [
            {"day": d, "franja": "MATI", "slot_id": "RM1", "professional": "AA",
             "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": d, "franja": "MATI", "slot_id": "TC1", "professional": "BB",
             "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": d, "franja": "MATI", "slot_id": "REVIEW", "professional": "CC",
             "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
        ]
    pd.DataFrame(rows).to_csv(tmp_path / "schedule.csv", index=False)
    pd.DataFrame({
        "professional_id": ["AA", "BB", "CC", "DD"],
        "name": ["Anna Prova", "Bernat Prova", "Carla Prova", "Dani Absent"],
    }).to_csv(tmp_path / "professionals.csv", index=False)
    set_slot_review_overrides({"REVIEW"})
    try:
        out = tmp_path / "cal.pdf"
        build_general_calendar_pdf(
            str(tmp_path / "schedule.csv"), str(tmp_path / "professionals.csv"),
            2026, 12, str(out), weekdays_only=True,
        )
    finally:
        set_slot_review_overrides(set())
    doc = fitz.open(out)
    assert doc.page_count == 1
    return doc[0].get_text()


def test_review_is_a_row_not_a_column(tmp_path, monkeypatch):
    text = _pdf_text(tmp_path, monkeypatch)
    assert "Revisió" in text
    assert "REVIEW" not in text  # ja no hi ha columna amb el nom de l'slot
    assert text.count("CC") >= len(DAYS)  # qui fa la revisió, cada dia


def test_short_legend_with_names_of_who_appears(tmp_path, monkeypatch):
    text = _pdf_text(tmp_path, monkeypatch)
    assert "Llegenda" in text and "Conveni" not in text  # sense el paràgraf llarg
    for name in ("Anna Prova", "Bernat Prova", "Carla Prova"):
        assert name in text
    assert "Dani Absent" not in text  # no surt al calendari d'aquest mes
