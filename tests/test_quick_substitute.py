"""Substitut determinista dels Ajustos ràpids (sense solver): cada
casella alliberada per una absència/guàrdia passa al candidat vàlid amb
menys càrrega mensual proporcional a la jornada; la guàrdia cobreix
també la postguàrdia."""

from datetime import date, timedelta

import pandas as pd
import pytest

from src.ui.quick_add_panels import _cover_professional_cells


def _sched(rows):
    return pd.DataFrame(
        rows,
        columns=["day", "franja", "slot_id", "professional",
                 "presentiality", "work_mode"],
    )


def _row(day, franja, slot, prof, pres="PRESENCIAL"):
    return {"day": day, "franja": franja, "slot_id": slot,
            "professional": prof, "presentiality": pres,
            "work_mode": "NORMAL"}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Fitxers de dades buits en un directori temporal (chdir-hi perquè
    eligibility/reductions es llegeixen de rutes relatives)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "reductions").mkdir(parents=True)
    absences = tmp_path / "absences.csv"
    guards = tmp_path / "guards.csv"
    professionals = tmp_path / "professionals.csv"
    pd.DataFrame(
        [{"professional_id": p, "name": "", "non_working_weekdays": "",
          "presence_mode": "", "fallback": 0}
         for p in ("P1", "P2", "P3")]
    ).to_csv(professionals, index=False)
    return absences, guards, professionals


class TestCoverCells:
    def test_least_loaded_candidate_takes_the_cell(self, paths):
        absences, guards, professionals = paths
        # P2 té 2 caselles al mes, P3 només 1 → el substitut ha de ser P3.
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-06", "MATI", "A", "P2"),
            _row("2026-01-07", "MATI", "A", "P2"),
            _row("2026-01-08", "MATI", "A", "P3"),
        ])
        mask = (df["day"] == "2026-01-05") & (df["professional"] == "P1")
        covered, holes, detail = _cover_professional_cells(
            df, mask, "P1", ["P1", "P2", "P3"],
            absences, guards, professionals,
        )
        assert (covered, holes) == (1, 0)
        assert df.at[0, "professional"] == "P3"
        assert "P3" in detail

    def test_capacity_proportional_choice(self, paths):
        absences, guards, professionals = paths
        # P2 amb 1 casella però jornada reduïda al 50% (càrrega 2.0);
        # P3 amb 1 casella a jornada plena (càrrega 1.0) → tria P3.
        pd.DataFrame([{
            "professional_id": "P2", "start_day": "2026-01-01",
            "end_day": "2026-12-31", "reduction_pct": 50, "notes": "",
        }]).to_csv("data/reductions/assignments.csv", index=False)
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-06", "MATI", "A", "P2"),
            _row("2026-01-07", "MATI", "A", "P3"),
        ])
        mask = (df["day"] == "2026-01-05") & (df["professional"] == "P1")
        _cover_professional_cells(
            df, mask, "P1", ["P1", "P2", "P3"], absences, guards, professionals,
        )
        assert df.at[0, "professional"] == "P3"

    def test_busy_same_franja_is_excluded(self, paths):
        absences, guards, professionals = paths
        # P3 (menys càrrega) ja té màquina aquella franja → ha d'anar a P2.
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-05", "MATI", "B", "P3"),
            _row("2026-01-06", "MATI", "A", "P2"),
            _row("2026-01-06", "TARDA", "A", "P2"),
        ])
        mask = (df["day"] == "2026-01-05") & (df["professional"] == "P1")
        _cover_professional_cells(
            df, mask, "P1", ["P1", "P2", "P3"], absences, guards, professionals,
        )
        assert df.at[0, "professional"] == "P2"

    def test_guard_frees_and_covers_postguard_day(self, paths):
        absences, guards, professionals = paths
        # Guàrdia de P1 el dilluns 5: tarda/nit del 5 + TOT el dimarts 6
        # (postguàrdia) han de quedar coberts per P2.
        g_day = date(2026, 1, 5)
        pd.DataFrame([{
            "day": g_day.isoformat(), "professional_id": "P1",
            "guard_kind": "guardia", "notes": "",
        }]).to_csv(guards, index=False)
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-05", "TARDA", "A", "P1"),
            _row("2026-01-06", "MATI", "A", "P1"),
            _row("2026-01-06", "TARDA", "B", "P1"),
        ])
        post = (g_day + timedelta(days=1)).isoformat()
        frU = df["franja"].str.upper()
        mask = (df["professional"] == "P1") & (
            ((df["day"] == g_day.isoformat()) & frU.isin({"TARDA", "NIT"}))
            | (df["day"] == post)
        )
        covered, holes, _ = _cover_professional_cells(
            df, mask, "P1", ["P1", "P2"], absences, guards, professionals,
        )
        # 3 caselles: tarda del 5 + matí i tarda del 6. El matí del 5 queda.
        assert (covered, holes) == (3, 0)
        assert df.at[0, "professional"] == "P1"
        assert set(df.loc[1:, "professional"]) == {"P2"}

    def test_guard_rows_in_schedule_are_never_reassigned(self, paths):
        # La fila GD del calendari NO se substitueix (les dades de guàrdies
        # seguirien dient P1 i la capçalera del PDF divergiria).
        absences, guards, professionals = paths
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-05", "NIT", "GD", "P1"),
        ])
        mask = df["professional"] == "P1"
        covered, holes, _ = _cover_professional_cells(
            df, mask, "P1", ["P1", "P2"], absences, guards, professionals,
        )
        assert df.at[1, "professional"] == "P1"  # GD intacta
        assert df.at[0, "professional"] == "P2"
        assert (covered, holes) == (1, 0)

    def test_fallback_professional_is_not_a_candidate(self, paths):
        absences, guards, professionals = paths
        pd.DataFrame(
            [{"professional_id": "P1", "fallback": 0, "non_working_weekdays": "",
              "presence_mode": "", "name": ""},
             {"professional_id": "TLD", "fallback": 1, "non_working_weekdays": "",
              "presence_mode": "", "name": ""},
             {"professional_id": "P2", "fallback": 0, "non_working_weekdays": "",
              "presence_mode": "", "name": ""}]
        ).to_csv(professionals, index=False)
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-06", "MATI", "A", "P2"),
        ])
        mask = (df["day"] == "2026-01-05") & (df["professional"] == "P1")
        _cover_professional_cells(
            df, mask, "P1", ["P1", "P2", "TLD"], absences, guards, professionals,
        )
        assert df.at[0, "professional"] == "P2"

    def test_no_candidate_leaves_hole(self, paths):
        absences, guards, professionals = paths
        # P2 absent el mateix dia; P3 ocupat → cap candidat, casella buida.
        pd.DataFrame([{
            "absence_type": "vacances", "professional_id": "P2",
            "start_day": "2026-01-05", "end_day": "2026-01-05", "notes": "",
        }]).to_csv(absences, index=False)
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-05", "MATI", "B", "P3"),
        ])
        mask = (df["day"] == "2026-01-05") & (df["professional"] == "P1")
        covered, holes, _ = _cover_professional_cells(
            df, mask, "P1", ["P1", "P2", "P3"], absences, guards, professionals,
        )
        assert (covered, holes) == (0, 1)
        assert df.at[0, "professional"] == ""

    def test_linked_block_same_substitute(self, paths):
        absences, guards, professionals = paths
        # P1 duia DUES màquines la mateixa franja (bloc vinculat): el
        # substitut ha de ser el MATEIX per a totes dues.
        df = _sched([
            _row("2026-01-05", "MATI", "A", "P1"),
            _row("2026-01-05", "MATI", "B", "P1"),
            _row("2026-01-06", "MATI", "A", "P2"),
        ])
        mask = (df["day"] == "2026-01-05") & (df["professional"] == "P1")
        covered, holes, _ = _cover_professional_cells(
            df, mask, "P1", ["P1", "P2", "P3"], absences, guards, professionals,
        )
        assert (covered, holes) == (2, 0)
        assert df.at[0, "professional"] == df.at[1, "professional"]
