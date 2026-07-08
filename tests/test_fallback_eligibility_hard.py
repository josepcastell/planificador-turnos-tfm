"""Tests per a la restriccio DURA de l'elegibilitat del comodi (TLD).

Per defecte el comodi esta exempt de l'eligibility map (_add_eligibility_soft
salta el TLD). Aquesta nova funcio afegeix excepcions estrictes: si
l'usuari marca `(TLD, SLOT_X, allowed=0)`, el solver no pot assignar-li
SLOT_X (x[TLD, sk] forçat a 0).

Risc: pot infactibilitzar si cap altre facultatiu és elegible. L'usuari
ha de garantir-ne la cobertura."""

from dataclasses import dataclass

import pandas as pd
from ortools.sat.python import cp_model

from src.solver.constraints import _add_fallback_eligibility_hard
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
                f"x_{p}_{r.slot_id}_{r.day}".replace("-", "_")
            )
    return x


class TestFallbackEligibilityHard:
    def test_tld_forbidden_when_allowed_0(self):
        # Eligibility map diu (TLD, URG_B, allowed=0). El solver NO pot
        # assignar TLD a URG_B.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "URG_B", "PRESENCIAL")]
        x = _build_x(model, ["TLD", "ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        elig = pd.DataFrame({
            "professional_id": ["TLD"],
            "slot_id": ["URG_B"],
            "allowed": [0],
        })
        _add_fallback_eligibility_hard(
            model, x, fallback_professionals={"TLD"},
            slot_keys=slot_keys, eligibility_df=elig,
        )
        # Cobertura: 1 facultatiu per slot. ALICE l'ha de cobrir (TLD esta blocat).
        sk = slot_keys[0]
        model.Add(x[("TLD", sk)] + x[("ALICE", sk)] == 1)
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("TLD", sk)]) == 0
        assert solver.Value(x[("ALICE", sk)]) == 1

    def test_tld_allowed_when_allowed_1(self):
        # Eligibility map diu (TLD, URG_B, allowed=1). TLD pot fer-ho.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "URG_B", "PRESENCIAL")]
        x = _build_x(model, ["TLD"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        elig = pd.DataFrame({
            "professional_id": ["TLD"],
            "slot_id": ["URG_B"],
            "allowed": [1],
        })
        _add_fallback_eligibility_hard(
            model, x, fallback_professionals={"TLD"},
            slot_keys=slot_keys, eligibility_df=elig,
        )
        sk = slot_keys[0]
        model.Add(x[("TLD", sk)] == 1)  # Forcem assignacio
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("TLD", sk)]) == 1

    def test_tld_default_allowed_when_no_entry(self):
        # Sense entrada al map, default es allowed=1 (TLD pot fer-ho).
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL")]
        x = _build_x(model, ["TLD"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        elig = pd.DataFrame({
            "professional_id": ["TLD"],
            "slot_id": ["URG_B"],  # Entrada diferent
            "allowed": [0],
        })
        _add_fallback_eligibility_hard(
            model, x, fallback_professionals={"TLD"},
            slot_keys=slot_keys, eligibility_df=elig,
        )
        sk = slot_keys[0]
        model.Add(x[("TLD", sk)] == 1)  # Sense restriccio
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("TLD", sk)]) == 1

    def test_regular_not_affected(self):
        # Els regulars (no fallback) no son tocats per aquesta funcio.
        # ALICE pot assignar-se a URG_B encara que tingui allowed=0 al map
        # (la SOFT eligibility ho penalitza, pero no es DURA per a regulars).
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "URG_B", "PRESENCIAL")]
        x = _build_x(model, ["ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        elig = pd.DataFrame({
            "professional_id": ["ALICE"],
            "slot_id": ["URG_B"],
            "allowed": [0],  # ALICE no elegible (soft)
        })
        _add_fallback_eligibility_hard(
            model, x, fallback_professionals=set(),  # cap fallback
            slot_keys=slot_keys, eligibility_df=elig,
        )
        sk = slot_keys[0]
        model.Add(x[("ALICE", sk)] == 1)  # Forcem assignacio
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        # Factible: aquesta funcio nomes toca fallback, ALICE lliure.
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_no_fallback_no_op(self):
        # Sense facultatius fallback, la funcio es una NO-OP.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL")]
        x = _build_x(model, ["ALICE"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        elig = pd.DataFrame({
            "professional_id": ["TLD"], "slot_id": ["RM_A"], "allowed": [0],
        })
        _add_fallback_eligibility_hard(
            model, x, fallback_professionals=set(),
            slot_keys=slot_keys, eligibility_df=elig,
        )
        sk = slot_keys[0]
        model.Add(x[("ALICE", sk)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_empty_eligibility_no_op(self):
        # Map buit: cap restriccio.
        model = cp_model.CpModel()
        rows = [_Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL")]
        x = _build_x(model, ["TLD"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        _add_fallback_eligibility_hard(
            model, x, fallback_professionals={"TLD"},
            slot_keys=slot_keys, eligibility_df=pd.DataFrame(),
        )
        sk = slot_keys[0]
        model.Add(x[("TLD", sk)] == 1)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    def test_blocks_all_positions_of_same_slot_id(self):
        # Si una activitat doblada (slot_id repetit a posicions diferents)
        # esta marcada (TLD, allowed=0), TLD esta blocat a TOTES les posicions
        # — perque el map es per slot_id, no per slot_key.
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL", position=1),
            _Row("2026-01-06", "MATI", "RM_A", "NO_PRESENCIAL", position=2),
        ]
        x = _build_x(model, ["TLD", "ALICE", "BOB"], rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        elig = pd.DataFrame({
            "professional_id": ["TLD"],
            "slot_id": ["RM_A"],
            "allowed": [0],
        })
        _add_fallback_eligibility_hard(
            model, x, fallback_professionals={"TLD"},
            slot_keys=slot_keys, eligibility_df=elig,
        )
        # Cobertura: 1 facultatiu per slot.
        for sk in slot_keys:
            model.Add(sum(x[p, sk] for p in ["TLD", "ALICE", "BOB"]) == 1)
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        # TLD no pot estar a cap posicio de RM_A.
        for sk in slot_keys:
            assert solver.Value(x[("TLD", sk)]) == 0
