"""Tests del comptatge a Metriques: les maquines VINCULADES han de
comptar com a 1 sola (a presencial, no-presencial, i total) — el mateix
criteri que segueix el solver i la UI del calendari.

`_collapse_linked` rep el calendari real (un row per slot assignat) i
treu, per a cada parella vinculada del cataleg, una de les dues files
quan el mateix facultatiu te els dos slots el mateix dia."""

from unittest.mock import patch

import pandas as pd

from src.ui.metrics_tab import _collapse_linked


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestCollapseLinkedTwoPresentials:
    """El cas que importa al ulluari: dues maquines presencials vinculades
    NO han de comptar com a 2 presencials, sino com 1."""

    def test_two_linked_presentials_collapse_to_one(self):
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 1
        # La fila que queda ha de ser PRESENCIAL (per definicio del helper)
        assert (out["presentiality"] == "PRESENCIAL").all()

    def test_two_pairs_same_day_collapse_to_two(self):
        # Si te 2 instancies de cada slot del parell (per posicio),
        # el resultat son 2 maquines col·lapsades, no 4.
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 2

    def test_different_days_not_collapsed(self):
        # Els parells nomes col·lapsen dins el mateix dia. Dos dies = 2 rows.
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-07", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 2

    def test_different_professionals_not_collapsed(self):
        # Els parells nomes col·lapsen per un mateix facultatiu.
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P2", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 2


class TestCollapseLinkedMixedPresence:
    """Casos amb presencialitat mixta dins el parell vinculat."""

    def test_pres_and_no_pres_keeps_pres(self):
        # Si un slot del parell es PRES i l'altre NO_PRES, el helper conserva
        # SEMPRE el PRES (per coherencia amb el solver).
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 1
        assert out["presentiality"].iloc[0] == "PRESENCIAL"

    def test_two_no_presentials_collapse_to_one_no_pres(self):
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "NO_PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 1
        assert out["presentiality"].iloc[0] == "NO_PRESENCIAL"


class TestCollapseLinkedUnpaired:
    """Casos sense parella completa: no s'ha de col·lapsar."""

    def test_only_one_slot_of_pair_no_collapse(self):
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 1

    def test_no_pairs_defined_returns_unchanged(self):
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[]):
            out = _collapse_linked(df)
        assert len(out) == 2

    def test_extra_unpaired_slot_preserved(self):
        # 2 RM_A + 1 RM_B: el parell (RM_B, RM_A) col·lapsa 1
        # vegada (n = min(2, 1) = 1) → es treu 1 row del costat `b` segons
        # l'ordre alfabetic. Total resultant: 2 rows (mai 4, mai 1).
        # Aqui l'important es la COMPTABILITZACIO, no quina label sobreviu.
        df = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "RM_B",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])
        with patch("src.ui.metrics_tab._slot_link_pairs", return_value=[("RM_B", "RM_A")]):
            out = _collapse_linked(df)
        assert len(out) == 2
        # 2 maquines presencials totals (no 3, no 1).
        assert (out["presentiality"] == "PRESENCIAL").sum() == 2


class TestPresencialCountEndToEnd:
    """Verifica que el comptador 'presential' del helper de metriques
    `_scoped_solver_metrics` reflecteix els parells col·lapsats."""

    def test_two_linked_pres_count_as_one_presential(self):
        from src.ui.metrics_tab import _scoped_solver_metrics

        m = _df([
            {"day": "2026-01-06", "slot_id": "RM_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])  # Aixo ja simula el resultat post-_collapse_linked: 1 fila despres del col·lapse.
        with patch(
            "src.ui.metrics_tab._capacity_by_prof", return_value={},
        ):
            sm = _scoped_solver_metrics(2026, [1], set(), m)
        p1 = sm[sm["professional"] == "P1"].iloc[0]
        assert int(p1["presential"]) == 1  # 1, no 2

    def test_unlinked_two_pres_count_as_two(self):
        # Si NO estan vinculades, han de comptar com a 2 (comprovacio de
        # control negativa).
        from src.ui.metrics_tab import _scoped_solver_metrics

        m = _df([
            {"day": "2026-01-06", "slot_id": "TC_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
            {"day": "2026-01-06", "slot_id": "MAMO_A",
             "professional": "P1", "presentiality": "PRESENCIAL", "work_mode": "NORMAL"},
        ])  # Sense parella vinculada al cataleg, ambdues entren al comptador.
        with patch(
            "src.ui.metrics_tab._capacity_by_prof", return_value={},
        ):
            sm = _scoped_solver_metrics(2026, [1], set(), m)
        p1 = sm[sm["professional"] == "P1"].iloc[0]
        assert int(p1["presential"]) == 2
