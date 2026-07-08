"""Tests per al cas combinat «màquina doblada + vinculada».

Regla del domini (acordada amb la direcció del servei):

  Una màquina doblada té 2 posicions:
    - Posició 1: PRESENCIAL.
    - Posició 2: NO_PRESENCIAL.

  Si la màquina està vinculada (linked_to) a una altra:
    - El LINK aplica només a la posició 1 (PRES). El facultatiu que
      cobreix pos 1 de la doblada també ha de cobrir l'slot vinculat
      (mateix dia/franja).
    - La posició 2 (NP) NO està vinculada — un altre facultatiu la pot
      cobrir lliurement, sense obligació d'estar a l'slot vinculat.

Aquesta regla l'implementa `_representative_key` a constraints.py: per
a un grup d'slots amb el mateix slot_id, tria el PRESENCIAL de menor
posició com a representant. `_add_structural_coupling` només lliga el
representant amb el partner — pos 2 (NP) queda lliure."""

from dataclasses import dataclass

from ortools.sat.python import cp_model

from src.solver.constraints import (
    _add_coverage_constraints,
    _add_daily_compat_constraints,
    _add_structural_coupling,
    _representative_key,
)
from src.solver.normalize import _make_slot_key


@dataclass
class _Row:
    day: str
    franja: str
    slot_id: str
    presentiality: str
    work_mode: str = "NORMAL"
    position: int = 1


def _build_x(model, professionals, slot_rows):
    x = {}
    for p in professionals:
        for r in slot_rows:
            sk = _make_slot_key(r)
            x[p, sk] = model.NewBoolVar(
                f"x_{p}_{r.day}_{r.franja}_{r.slot_id}_{r.position}"
                .replace("-", "_")
            )
    return x


def _is_feasible(model: cp_model.CpModel) -> bool:
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


class TestRepresentativeKey:
    """L'algorisme de tria del representant ha de prioritzar PRES + pos baixa."""

    def test_doubled_picks_pres_position_1(self):
        # Doblat: pos 1 PRES, pos 2 NP. Representant ha de ser pos 1 PRES.
        sk_pos1 = ("2026-01-06", "MATI", "RM_A", "PRESENCIAL", "NORMAL", 1)
        sk_pos2 = ("2026-01-06", "MATI", "RM_A", "NO_PRESENCIAL", "NORMAL", 2)
        rep = _representative_key([sk_pos2, sk_pos1])  # ordre desordenat
        assert rep == sk_pos1

    def test_unique_pres_returns_it(self):
        sk = ("2026-01-06", "MATI", "TC_A", "PRESENCIAL", "NORMAL", 1)
        assert _representative_key([sk]) == sk

    def test_only_np_picks_lowest_position(self):
        # Cas degenerat: dos NP sense PRES. Tria el de posició més baixa.
        sk_pos1 = ("2026-01-06", "MATI", "X", "NO_PRESENCIAL", "NORMAL", 1)
        sk_pos2 = ("2026-01-06", "MATI", "X", "NO_PRESENCIAL", "NORMAL", 2)
        assert _representative_key([sk_pos2, sk_pos1]) == sk_pos1

    def test_empty_returns_none(self):
        assert _representative_key([]) is None


class TestStructuralCouplingDoubled:
    """Verifica que el LINK només forci la posició PRES de la doblada,
    deixant la posició NP lliure per a un altre facultatiu."""

    def _build(self, slot_links):
        # Setup:
        #   - RM_A doblat (pos 1 PRES, pos 2 NP) a MATI dia D.
        #   - RM_B no doblat (PRES pos 1) a MATI dia D.
        #   - Link: (RM_B, RM_A)
        # 3 facultatius: cal almenys 3 perquè cada slot (3) tingui un
        # facultatiu diferent (max 1 màquina/franja per persona).
        model = cp_model.CpModel()
        rows = [
            _Row("2026-01-06", "MATI", "RM_A", "PRESENCIAL", position=1),
            _Row("2026-01-06", "MATI", "RM_A", "NO_PRESENCIAL", position=2),
            _Row("2026-01-06", "MATI", "RM_B", "PRESENCIAL", position=1),
        ]
        professionals = ["ALICE", "BOB", "CHARLIE"]
        x = _build_x(model, professionals, rows)
        slot_keys = [_make_slot_key(r) for r in rows]
        keys_by_day = {"2026-01-06": slot_keys}
        # Cobertura: tot slot ha de tenir 1 facultatiu assignat
        _add_coverage_constraints(model, x, professionals, slot_keys)
        # Daily compat (màx 1 màquina per franja, vinculats col·lapsen)
        _add_daily_compat_constraints(
            model, x, professionals, rows, ["2026-01-06"],
            review_slots=set(),
            links_by_wf=({("", ""): slot_links} if slot_links else {}),
        )
        # Linking: només la pos PRES es lliga. Vinculació GLOBAL → clau ('', '').
        _add_structural_coupling(model, x, professionals, keys_by_day,
                                  links_by_wf=({("", ""): slot_links} if slot_links else {}))
        return model, x, rows

    def test_pres_pos1_coupled_with_partner(self):
        # ALICE a RM_A pos 1 PRES => ALICE a RM_B (forçat pel link).
        model, x, rows = self._build([("RM_B", "RM_A")])
        sk_hub_pos1 = _make_slot_key(rows[0])
        sk_dir = _make_slot_key(rows[2])
        model.Add(x[("ALICE", sk_hub_pos1)] == 1)
        # El link força: ALICE també està a RM_B.
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(x[("ALICE", sk_dir)]) == 1

    def test_np_pos2_not_coupled_with_partner(self):
        # BOB cobrint RM_A pos 2 NP NO ha d'estar obligat a RM_B.
        # La cobertura assigna RM_B a algú (ALICE), però BOB no.
        model, x, rows = self._build([("RM_B", "RM_A")])
        sk_hub_pos2 = _make_slot_key(rows[1])
        sk_dir = _make_slot_key(rows[2])
        # Forcem BOB a pos 2.
        model.Add(x[("BOB", sk_hub_pos2)] == 1)
        # Forcem ALICE a RM_B (perquè la cobertura es compleixi).
        model.Add(x[("ALICE", sk_dir)] == 1)
        # El link PRES també requereix Alice a RM_A pos 1 (PRES); ho farem
        # forçant explícitament perquè el solver no tingui altres opcions.
        sk_hub_pos1 = _make_slot_key(rows[0])
        model.Add(x[("ALICE", sk_hub_pos1)] == 1)
        # Aquesta configuració ha de ser FACTIBLE: BOB a pos 2 NP sense
        # haver d'estar a RM_B (no està lligat).
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        # Verifiquem que BOB no està a RM_B (no se li ha forçat).
        assert solver.Value(x[("BOB", sk_dir)]) == 0

    def test_without_link_no_coupling(self):
        # Cas de control: sense link, ningu no està obligat a res.
        model, x, rows = self._build([])  # cap link
        sk_hub_pos1 = _make_slot_key(rows[0])
        sk_dir = _make_slot_key(rows[2])
        # Forcem Alice a RM_A pos 1 i Bob (un altre) a RM_B.
        model.Add(x[("ALICE", sk_hub_pos1)] == 1)
        model.Add(x[("BOB", sk_dir)] == 1)
        # Ha de ser factible (la cobertura el cobreix).
        assert _is_feasible(model)
