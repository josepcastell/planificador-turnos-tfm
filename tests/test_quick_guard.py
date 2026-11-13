"""Ajust ràpid «Introduir guàrdia» (sense solver): el matí del dia de
guàrdia es queda tal com està; la tarda i la nit (qui fa guàrdia no les pot
fer) i tota la postguàrdia es cobreixen amb el company amb menys càrrega.
Abans el formulari petava (NameError) si la guàrdia tocava cap casella del
calendari."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.ui.quick_add_panels import _apply_guard

G_DAY = date(2026, 1, 7)  # dimecres
DAY, POST = "2026-01-07", "2026-01-08"


def _sched(rows):
    return pd.DataFrame(
        [{"day": d, "franja": f, "slot_id": s, "professional": p,
          "presentiality": pres, "work_mode": "NORMAL"}
         for d, f, s, p, pres in rows],
    )


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "reductions").mkdir(parents=True)
    absences = tmp_path / "absences.csv"
    guards = tmp_path / "guards.csv"
    professionals = tmp_path / "professionals.csv"
    pd.DataFrame(
        [{"professional_id": p, "name": "", "non_working_weekdays": "",
          "presence_mode": "", "fallback": 0} for p in ("P1", "P2", "P3")]
    ).to_csv(professionals, index=False)
    # La guàrdia ja és a les dades quan s'aplica (el formulari la desa abans).
    pd.DataFrame([{"day": DAY, "professional_id": "P1", "guard_kind": "guardia",
                   "notes": ""}]).to_csv(guards, index=False)
    return absences, guards, professionals


def _who(df, day, franja, slot):
    return df.loc[
        (df["day"] == day) & (df["franja"] == franja) & (df["slot_id"] == slot),
        "professional",
    ].item()


def test_morning_stays_afternoon_night_and_postguard_are_covered(paths):
    df = _sched([
        (DAY, "MATI", "RM_PRES", "P1", "PRESENCIAL"),
        (DAY, "TARDA", "TC_TARDA", "P1", "PRESENCIAL"),
        (DAY, "NIT", "RM_NIT", "P1", "NO_PRESENCIAL"),
        (DAY, "MATI", "RM_TELE", "P2", "NO_PRESENCIAL"),
        (POST, "MATI", "RM_PRES", "P1", "PRESENCIAL"),
        (POST, "TARDA", "TC_TARDA", "P1", "PRESENCIAL"),
    ])
    covered, holes, _detail = _apply_guard(df, "P1", G_DAY, ["P1", "P2", "P3"], *paths)

    # El matí no es toca (ni s'intercanvia per un de teletreball).
    assert _who(df, DAY, "MATI", "RM_PRES") == "P1"
    assert _who(df, DAY, "MATI", "RM_TELE") == "P2"
    # Tarda, nit i tota la postguàrdia passen a un company.
    for day, franja, slot in [
        (DAY, "TARDA", "TC_TARDA"), (DAY, "NIT", "RM_NIT"),
        (POST, "MATI", "RM_PRES"), (POST, "TARDA", "TC_TARDA"),
    ]:
        assert _who(df, day, franja, slot) not in ("P1", "")
    assert (covered, holes) == (4, 0)


def test_only_morning_on_guard_day_changes_nothing_that_day(paths):
    df = _sched([(DAY, "MATI", "RM_PRES", "P1", "PRESENCIAL")])
    assert _apply_guard(df, "P1", G_DAY, ["P1", "P2", "P3"], *paths) == (0, 0, "")
    assert _who(df, DAY, "MATI", "RM_PRES") == "P1"


def _guard_panel(absences: str, guards: str, professionals: str) -> None:
    from pathlib import Path

    from src.ui.quick_add_panels import _quick_add_guard
    _quick_add_guard(
        Path(absences), Path(guards), ["P1", "P2", "P3"], 2026, 1,
        Path(professionals), Path("pdf"), [1],
    )


def test_guard_form_applies_without_error(paths, monkeypatch):
    absences, guards, professionals = paths
    Path(guards).unlink()  # el formulari l'ha de crear
    Path("outputs").mkdir()
    _sched([
        (DAY, "MATI", "RM_PRES", "P1", "PRESENCIAL"),
        (DAY, "TARDA", "TC_TARDA", "P1", "PRESENCIAL"),
        (POST, "MATI", "RM_PRES", "P1", "PRESENCIAL"),
    ]).to_csv("outputs/schedule_weekday.csv", index=False)
    import src.ui.planning_calendar_tabs as tabs
    monkeypatch.setattr(tabs, "rerender_pdf_after_edit", lambda *a, **k: 0)

    at = AppTest.from_function(
        _guard_panel, args=(str(absences), str(guards), str(professionals)),
        default_timeout=30,
    ).run()
    at.date_input(key="qa_guard_day").set_value(G_DAY)
    at.selectbox(key="qa_guard_prof").set_value("P1")
    at.button[0].click().run()

    assert not at.exception
    out = pd.read_csv("outputs/schedule_weekday.csv")
    assert _who(out, DAY, "MATI", "RM_PRES") == "P1"
    assert _who(out, DAY, "TARDA", "TC_TARDA") != "P1"
    assert _who(out, POST, "MATI", "RM_PRES") != "P1"
    assert pd.read_csv(guards)["professional_id"].tolist() == ["P1"]
