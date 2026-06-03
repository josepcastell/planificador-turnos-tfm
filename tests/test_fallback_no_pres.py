"""Tests: si l'usuari marca un facultatiu (típicament el comodí TLD)
amb `presence_mode=NO_PRESENCIAL` a la pestanya Facultatius, el solver
no li assigna cap slot PRESENCIAL.

NOTA: aquesta restricció ja no s'imposa automàticament als fallback.
El comportament només s'aplica quan l'usuari ho ha posat explícitament
al CSV. Si la fila del comodí té `presence_mode` buit, pot cobrir tant
PRES com NO_PRES (encara que en la pràctica els regulars l'agafen abans
gràcies al penal `tld_usage` i a la jerarquia de trams)."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from src.solver.constraints import _add_presence_mode_constraints
from src.solver.normalize import _make_slot_key


@dataclass
class _Row:
    day: str
    franja: str
    slot_id: str
    presentiality: str
    work_mode: str = "NORMAL"
    position: int = 1


def _build_x(model, professionals, rows):
    x = {}
    for p in professionals:
        for r in rows:
            sk = _make_slot_key(r)
            x[p, sk] = model.NewBoolVar(
                f"x_{p}_{r.slot_id}_{r.presentiality}".replace("-", "_")
            )
    return x


class TestFallbackNoPres:
    def test_fallback_blocked_from_pres_slot(self):
        # Amb presence_mode=NO_PRESENCIAL, TLD no pot cobrir un slot PRES.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "TC_HUB", "PRESENCIAL")]
        x = _build_x(model, ["TLD", "ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        presence_mode = {"TLD": "NO_PRESENCIAL"}
        _add_presence_mode_constraints(model, x, slot_keys, presence_mode)
        # Cobertura: 1 facultatiu per slot.
        sk = slot_keys[0]
        model.Add(x[("TLD", sk)] + x[("ALICE", sk)] == 1)
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("TLD", sk)]) == 0
        assert solver.Value(x[("ALICE", sk)]) == 1

    def test_fallback_allowed_on_np_slot(self):
        # Sobre un slot NO_PRESENCIAL, TLD si que pot anar-hi.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "RM_HUB", "NO_PRESENCIAL")]
        x = _build_x(model, ["TLD"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        presence_mode = {"TLD": "NO_PRESENCIAL"}
        _add_presence_mode_constraints(model, x, slot_keys, presence_mode)
        sk = slot_keys[0]
        model.Add(x[("TLD", sk)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("TLD", sk)]) == 1

    def test_regular_can_do_pres(self):
        # Els regulars (sense presence_mode) poden fer PRES sense problema.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "TC_HUB", "PRESENCIAL")]
        x = _build_x(model, ["ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        presence_mode = {"TLD": "NO_PRESENCIAL"}  # nomes TLD restringit
        _add_presence_mode_constraints(model, x, slot_keys, presence_mode)
        sk = slot_keys[0]
        model.Add(x[("ALICE", sk)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("ALICE", sk)]) == 1


class TestPresenceModeReviewsExempt:
    """Les revisions queden fora de la restricció de presence_mode: són
    una categoria especial. Sense aquesta exempció, un facultatiu
    PRES-only amb una revisió NP (o viceversa) al catàleg quedaria
    infactible."""

    def test_pres_only_can_do_np_review(self):
        # ALICE té presence_mode=PRESENCIAL i el catàleg li assigna una
        # revisió NP (REVISIO_RM). Sense exempció: infactible. Amb
        # exempció: el solver pot assignar-li la revisió.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "REVISIO_RM", "NO_PRESENCIAL")]
        x = _build_x(model, ["ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        presence_mode = {"ALICE": "PRESENCIAL"}
        _add_presence_mode_constraints(
            model, x, slot_keys, presence_mode,
            review_slots={"REVISIO_RM"},
        )
        sk = slot_keys[0]
        model.Add(x[("ALICE", sk)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("ALICE", sk)]) == 1

    def test_np_only_can_do_pres_review(self):
        # Cas simètric: facultatiu NP-only + revisió PRES.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "REVISIO_RM", "PRESENCIAL")]
        x = _build_x(model, ["TLD"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        presence_mode = {"TLD": "NO_PRESENCIAL"}
        _add_presence_mode_constraints(
            model, x, slot_keys, presence_mode,
            review_slots={"REVISIO_RM"},
        )
        sk = slot_keys[0]
        model.Add(x[("TLD", sk)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("TLD", sk)]) == 1

    def test_non_review_still_restricted(self):
        # Si l'slot NO és revisió, segueix la restricció normal.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "REVISIO_RM", "NO_PRESENCIAL"),
            _Row("2026-01-06", "TARDA", "RM_HUB", "NO_PRESENCIAL"),
        ]
        x = _build_x(model, ["ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        presence_mode = {"ALICE": "PRESENCIAL"}
        _add_presence_mode_constraints(
            model, x, slot_keys, presence_mode,
            review_slots={"REVISIO_RM"},
        )
        sk_review, sk_normal = slot_keys
        # ALICE pot fer la revisió NP (exempció)…
        model.Add(x[("ALICE", sk_review)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        # …però no l'slot NP no-revisió.
        assert solver.Value(x[("ALICE", sk_normal)]) == 0

    def test_normalizes_review_slot_id(self):
        # El conjunt review_slots accepta strings amb espais; la funció
        # els normalitza (UPPER + strip) per fer match amb sk[2].
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "REVISIO_RM", "NO_PRESENCIAL")]
        x = _build_x(model, ["ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        presence_mode = {"ALICE": "PRESENCIAL"}
        _add_presence_mode_constraints(
            model, x, slot_keys, presence_mode,
            review_slots={"  revisio_rm  "},
        )
        sk = slot_keys[0]
        model.Add(x[("ALICE", sk)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("ALICE", sk)]) == 1


