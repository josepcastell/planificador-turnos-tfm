"""Modes de les regles d'equilibri (none/presencial/total/personalitzat)
+ proposta amb acceptació (balance_proposal)."""

from dataclasses import dataclass

import pandas as pd
from ortools.sat.python import cp_model

from src.domain.planning_rules import PlanningRules
from src.services import balance_proposal as bp
from src.solver.constraints import _build_machine_term_specs
from src.solver.normalize import _make_slot_key
from src.solver.objectives_targets import _add_weekly_soft_terms, weekly_auto_targets

MON, TUE = "2026-01-05", "2026-01-06"


@dataclass(frozen=True)
class _Row:
    day: str
    franja: str
    slot_id: str
    presentiality: str
    work_mode: str = "NORMAL"
    position: int = 1


def _setup(rows, professionals):
    model = cp_model.CpModel()
    x = {}
    keys_by_day: dict = {}
    for r in rows:
        sk = _make_slot_key(r)
        keys_by_day.setdefault(r.day, []).append(sk)
        for p in professionals:
            x[p, sk] = model.NewBoolVar(
                f"x_{p}_{r.day}_{r.slot_id}_{r.position}".replace("-", "_")
            )
    return model, x, keys_by_day


def _solve(model, var):
    solver = cp_model.CpSolver()
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return solver.Value(var)


class TestRulesMode:
    def test_roundtrip_mode(self, tmp_path):
        p = tmp_path / "rules.csv"
        PlanningRules(mode="presencial").to_csv(p)
        assert PlanningRules.from_csv(p).mode == "presencial"

    def test_legacy_csv_without_mode_uses_default_total(self, tmp_path):
        p = tmp_path / "rules.csv"
        pd.DataFrame({
            "active_days": [5], "target_machines": [4], "target_presential": [2],
        }).to_csv(p, index=False)
        rules = PlanningRules.from_csv(p)
        assert rules.mode == "total"
        assert rules.target_machines[5] == 4

    def test_invalid_mode_falls_back(self, tmp_path):
        p = tmp_path / "rules.csv"
        pd.DataFrame({
            "active_days": [5], "target_machines": [0],
            "target_presential": [0], "mode": ["rareza"],
        }).to_csv(p, index=False)
        assert PlanningRules.from_csv(p).mode == "total"


class TestWeeklyAutoTargets:
    def test_apportion_sums_to_week_load(self):
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "MATI", "B", "NO_PRESENCIAL"),
            _Row(TUE, "MATI", "A", "PRESENCIAL"),
        ]
        _m, _x, keys_by_day = _setup(rows, ["P1", "P2"])
        specs = _build_machine_term_specs(keys_by_day, review_slots=set())
        common = dict(
            quota_hard_professionals=["P1", "P2"],
            unique_days=[MON, TUE],
            unique_weeks=["2026-W02"],
            week_map={MON: "2026-W02", TUE: "2026-W02"},
            working_map={MON: 1, TUE: 1},
            absent_days_by_prof={"P1": set(), "P2": set()},
            capacity_pct_by={(p, d): 100 for p in ["P1", "P2"] for d in [MON, TUE]},
            machine_specs=specs,
        )
        t_pres = weekly_auto_targets("presencial", **common)
        t_tot = weekly_auto_targets("total", **common)
        assert sum(t_pres.values()) == 2   # 2 màquines PRES a la setmana
        assert sum(t_tot.values()) == 3    # 3 màquines en total
        # Absència tota la setmana → capacitat 0 → fora del repartiment.
        common["absent_days_by_prof"] = {"P1": set(), "P2": {MON, TUE}}
        t2 = weekly_auto_targets("total", **common)
        assert t2 == {("P1", "2026-W02"): 3}


class TestWeeklySoftTermsModes:
    def _terms(self, mode, rows, assignments):
        model, x, keys_by_day = _setup(rows, ["P1"])
        for (p, r), val in assignments.items():
            model.Add(x[p, _make_slot_key(r)] == val)
        rules = PlanningRules(
            target_machines={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            target_presential={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            mode=mode,
        )
        res = _add_weekly_soft_terms(
            model, x, ["P1"], [MON], ["W"], {MON: "W"}, {MON: 1},
            {"P1": set()}, keys_by_day, {("P1", MON): 100}, set(),
            planning_rules=rules,
        )
        return model, res

    def test_mode_none_all_terms_zero(self):
        rows = [_Row(MON, "MATI", "A", "PRESENCIAL")]
        model, (ps, po, ns, no) = self._terms("none", rows, {("P1", rows[0]): 1})
        for v in (ps, po, ns, no):
            assert _solve(model, v) == 0

    def test_mode_presencial_does_not_touch_np(self):
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "B", "NO_PRESENCIAL"),
        ]
        # P1 cobreix la PRES (target auto = 1) i també l'NP: cap penalització
        # NP en mode presencial (l'NP queda lliure).
        model, (ps, po, ns, no) = self._terms(
            "presencial", rows,
            {("P1", rows[0]): 1, ("P1", rows[1]): 1},
        )
        assert _solve(model, ps) == 0
        assert _solve(model, po) == 0
        assert _solve(model, ns) == 0
        assert _solve(model, no) == 0

    def test_mode_total_penalizes_deviation_from_auto_target(self):
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "B", "NO_PRESENCIAL"),
        ]
        # target auto total per P1 = 2; si només en cobreix 1 → shortfall 1.
        model, (ps, _po, _ns, _no) = self._terms(
            "total", rows, {("P1", rows[0]): 1, ("P1", rows[1]): 0},
        )
        assert _solve(model, ps) == 1


class TestBalanceProposal:
    def _write(self, tmp_path, monkeypatch, base_prof, prop_prof):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "outputs").mkdir()
        cols = ["day", "franja", "slot_id", "presentiality", "work_mode", "professional"]
        pd.DataFrame([
            {"day": MON, "franja": "MATI", "slot_id": "A",
             "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
             "professional": base_prof},
        ], columns=cols).to_csv(bp.SCHEDULE_PATH, index=False)
        pd.DataFrame([
            {"day": MON, "franja": "MATI", "slot_id": "A",
             "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
             "professional": prop_prof},
        ], columns=cols).to_csv(bp.PROPOSAL_PATH, index=False)

    def test_diff_apply_and_discard(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, "P1", "P2")
        assert bp.proposal_exists()
        diff = bp.load_proposal_diff()
        assert len(diff) == 1
        assert diff.iloc[0]["de"] == "P1" and diff.iloc[0]["a"] == "P2"
        n = bp.apply_proposal()
        assert n == 1
        assert not bp.PROPOSAL_PATH.exists()
        final = pd.read_csv(bp.SCHEDULE_PATH)
        assert final.iloc[0]["professional"] == "P2"

    def test_no_changes_diff_empty_and_discard(self, tmp_path, monkeypatch):
        self._write(tmp_path, monkeypatch, "P1", "P1")
        assert bp.load_proposal_diff().empty
        bp.discard_proposal()
        assert not bp.proposal_exists()
        assert pd.read_csv(bp.SCHEDULE_PATH).iloc[0]["professional"] == "P1"


MON2 = "2026-01-12"  # dilluns de la setmana següent (W03)


class TestMonthlyModes:
    """Modes mensuals: la càrrega del MES es reparteix sense objectiu
    setmanal; «activitat» equilibra només les instàncies d'una activitat."""

    def _terms(self, mode, rows, assignments, professionals=("P1", "P2"),
               balance_activity="", eligibility_df=None, absents=None):
        profs = list(professionals)
        model, x, keys_by_day = _setup(rows, profs)
        for (p, r), val in assignments.items():
            model.Add(x[p, _make_slot_key(r)] == val)
        rules = PlanningRules(mode=mode, balance_activity=balance_activity)
        days = sorted({r.day for r in rows})
        absent = {p: set() for p in profs}
        absent.update(absents or {})
        res = _add_weekly_soft_terms(
            model, x, profs, days, ["2026-W02", "2026-W03"],
            {MON: "2026-W02", TUE: "2026-W02", MON2: "2026-W03"},
            {d: 1 for d in days},
            absent, keys_by_day,
            {(p, d): 100 for p in profs for d in days}, set(),
            planning_rules=rules, eligibility_df=eligibility_df,
        )
        return model, res

    def test_mensual_total_ignores_weekly_imbalance(self):
        # 2 màquines a W02 i 2 a W03. P1 fa tota la W02, P2 tota la W03:
        # per setmanes seria desequilibrat, però el MES queda 2-2 → 0.
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "B", "NO_PRESENCIAL"),
            _Row(MON2, "MATI", "A", "PRESENCIAL"),
            _Row(MON2, "TARDA", "B", "NO_PRESENCIAL"),
        ]
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[1]): 1,
            ("P1", rows[2]): 0, ("P1", rows[3]): 0,
            ("P2", rows[0]): 0, ("P2", rows[1]): 0,
            ("P2", rows[2]): 1, ("P2", rows[3]): 1,
        }
        model, (ps, po, ns, no) = self._terms("mensual_total", rows, asg)
        for v in (ps, po, ns, no):
            assert _solve(model, v) == 0

    def test_mensual_total_penalizes_monthly_deviation(self):
        # 4 màquines al mes, targets 2-2. P1 en fa 3 i P2 en fa 1 →
        # shortfall 1 (P2) + overage 1 (P1).
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "B", "NO_PRESENCIAL"),
            _Row(MON2, "MATI", "A", "PRESENCIAL"),
            _Row(MON2, "TARDA", "B", "NO_PRESENCIAL"),
        ]
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[1]): 1, ("P1", rows[2]): 1,
            ("P1", rows[3]): 0,
            ("P2", rows[0]): 0, ("P2", rows[1]): 0, ("P2", rows[2]): 0,
            ("P2", rows[3]): 1,
        }
        model, (ps, po, _ns, _no) = self._terms("mensual_total", rows, asg)
        assert _solve(model, ps) == 1
        assert _solve(model, po) == 1

    def test_mensual_presencial_counts_only_pres(self):
        # 2 PRES + 2 NP al mes. P1 fa les 2 PRES i P2 les 2 NP:
        # targets PRES 1-1 → shortfall 1 + overage 1; NP no es toca.
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "B", "NO_PRESENCIAL"),
            _Row(MON2, "MATI", "A", "PRESENCIAL"),
            _Row(MON2, "TARDA", "B", "NO_PRESENCIAL"),
        ]
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[2]): 1,
            ("P1", rows[1]): 0, ("P1", rows[3]): 0,
            ("P2", rows[0]): 0, ("P2", rows[2]): 0,
            ("P2", rows[1]): 1, ("P2", rows[3]): 1,
        }
        model, (ps, po, ns, no) = self._terms("mensual_presencial", rows, asg)
        assert _solve(model, ps) == 1
        assert _solve(model, po) == 1
        assert _solve(model, ns) == 0
        assert _solve(model, no) == 0

    def test_activitat_balances_selected_slot_only(self):
        # PRIMARI — activitat A: 2 instàncies (targets 1-1). P1 les fa
        # totes dues → short 1 + over 1 al parell PRES (tram 1).
        # SECUNDARI — la resta (les 2 B, targets 1-1): P2 les fa totes
        # dues → short 1 + over 1 al parell NP (tram 2).
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "B", "NO_PRESENCIAL"),
            _Row(MON2, "MATI", "A", "PRESENCIAL"),
            _Row(MON2, "TARDA", "B", "NO_PRESENCIAL"),
        ]
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[2]): 1,
            ("P1", rows[1]): 0, ("P1", rows[3]): 0,
            ("P2", rows[0]): 0, ("P2", rows[2]): 0,
            ("P2", rows[1]): 1, ("P2", rows[3]): 1,
        }
        model, (ps, po, ns, no) = self._terms(
            "activitat", rows, asg, balance_activity="A",
        )
        assert _solve(model, ps) == 1
        assert _solve(model, po) == 1
        assert _solve(model, ns) == 1
        assert _solve(model, no) == 1

    def test_activitat_all_balanced_no_penalty(self):
        # A 1-1 i B 1-1 entre P1 i P2 → cap penalització en cap parell.
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "B", "NO_PRESENCIAL"),
            _Row(MON2, "MATI", "A", "PRESENCIAL"),
            _Row(MON2, "TARDA", "B", "NO_PRESENCIAL"),
        ]
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[2]): 0,
            ("P1", rows[1]): 0, ("P1", rows[3]): 1,
            ("P2", rows[0]): 0, ("P2", rows[2]): 1,
            ("P2", rows[1]): 1, ("P2", rows[3]): 0,
        }
        model, (ps, po, ns, no) = self._terms(
            "activitat", rows, asg, balance_activity="A",
        )
        for v in (ps, po, ns, no):
            assert _solve(model, v) == 0

    def test_activitat_eligibility_excludes_denied(self):
        # P2 té allowed=0 per A → tot el target va a P1 (2). P1 fa les 2 → 0.
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON2, "MATI", "A", "PRESENCIAL"),
        ]
        elig = pd.DataFrame(
            [{"professional_id": "P2", "slot_id": "A", "allowed": 0}]
        )
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[1]): 1,
            ("P2", rows[0]): 0, ("P2", rows[1]): 0,
        }
        model, (ps, po, _ns, _no) = self._terms(
            "activitat", rows, asg, balance_activity="A", eligibility_df=elig,
        )
        assert _solve(model, ps) == 0
        assert _solve(model, po) == 0

    def test_activitat_normalizes_raw_catalog_id(self):
        # El catàleg pot dur guions/espais («ECO-DOPPLER»); les claus del
        # solver estan normalitzades («ECO_DOPPLER»). Sense normalitzar,
        # el criteri primari quedaria silenciosament inert (regressió A1).
        rows = [
            _Row(MON, "MATI", "ECO_DOPPLER", "PRESENCIAL"),
            _Row(MON2, "MATI", "ECO_DOPPLER", "PRESENCIAL"),
        ]
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[1]): 1,
            ("P2", rows[0]): 0, ("P2", rows[1]): 0,
        }
        model, (ps, po, _ns, _no) = self._terms(
            "activitat", rows, asg, balance_activity="ECO-DOPPLER",
        )
        assert _solve(model, ps) == 1
        assert _solve(model, po) == 1

    def test_activitat_capacity_counts_only_activity_days(self):
        # L'activitat només existeix el MON; P2 hi és absent (però present
        # el MON2). El target primari ha d'anar TOT a P1 — sense el fix,
        # P2 rebria target impossible i penalitzaria permanentment (M1).
        rows = [
            _Row(MON, "MATI", "A", "PRESENCIAL"),
            _Row(MON, "TARDA", "A", "PRESENCIAL", position=2),
            _Row(MON2, "MATI", "B", "PRESENCIAL"),
        ]
        asg = {
            ("P1", rows[0]): 1, ("P1", rows[1]): 1, ("P1", rows[2]): 0,
            ("P2", rows[2]): 1,
        }
        model, (ps, po, _ns, _no) = self._terms(
            "activitat", rows, asg, balance_activity="A",
            absents={"P2": {MON}},
        )
        assert _solve(model, ps) == 0
        assert _solve(model, po) == 0

    def test_activitat_without_selection_is_inert(self):
        rows = [_Row(MON, "MATI", "A", "PRESENCIAL")]
        model, (ps, po, ns, no) = self._terms(
            "activitat", rows, {("P1", rows[0]): 1}, balance_activity="",
        )
        for v in (ps, po, ns, no):
            assert _solve(model, v) == 0

    def test_roundtrip_new_modes_and_activity(self, tmp_path):
        p = tmp_path / "rules.csv"
        PlanningRules(mode="mensual_presencial").to_csv(p)
        assert PlanningRules.from_csv(p).mode == "mensual_presencial"
        PlanningRules(mode="mensual_total").to_csv(p)
        assert PlanningRules.from_csv(p).mode == "mensual_total"
        PlanningRules(mode="activitat", balance_activity="ECO_ZONA_A").to_csv(p)
        loaded = PlanningRules.from_csv(p)
        assert loaded.mode == "activitat"
        assert loaded.balance_activity == "ECO_ZONA_A"
        # CSV antic sense columna → activitat buida.
        pd.DataFrame({
            "active_days": [5], "target_machines": [4],
            "target_presential": [2],
        }).to_csv(p, index=False)
        assert PlanningRules.from_csv(p).balance_activity == ""
