"""Flip INVERS (PRESENCIAL→NO_PRESENCIAL) de les regles d'equilibri.

Simètric al flip NP→PRES que ja existia: permet BAIXAR el comptador
presencial de qui en té massa, però només fins al target (mai per sota).
"""

from ortools.sat.python import cp_model

from src.solver.constraints import (
    _add_flip_target_cap,
    _collect_machine_terms_for_day,
)

MON = "2026-01-05"


def _sk(slot, pres="PRESENCIAL", franja="MATI", mode="NORMAL", pos=1):
    return (MON, franja, slot, pres, mode, pos)


class TestNpFlipCounting:
    def test_np_flip_subtracts_from_presential_count(self):
        model = cp_model.CpModel()
        keys = [_sk("A"), _sk("B", franja="TARDA")]
        x = {("P1", k): model.NewBoolVar(f"x_{k[2]}") for k in keys}
        spec = ([], list(keys), list(keys), [])
        nf = model.NewBoolVar("npflip_A")
        model.Add(nf <= x[("P1", keys[0])])
        mt, pmt = _collect_machine_terms_for_day(
            model, x, "P1", MON, spec, "t",
            np_flip={("P1", keys[0]): nf},
        )
        for k in keys:
            model.Add(x[("P1", k)] == 1)
        model.Add(nf == 1)
        total = model.NewIntVar(0, 5, "tot_pres")
        model.Add(total == sum(pmt))
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        # 2 màquines presencials, una convertida a remota → 1 presencial.
        assert solver.Value(total) == 1
        # El recompte de MÀQUINES no canvia: segueix fent-ne dues.
        assert len(mt) == 2

    def test_without_np_flip_nothing_changes(self):
        model = cp_model.CpModel()
        keys = [_sk("A")]
        x = {("P1", keys[0]): model.NewBoolVar("x_A")}
        spec = ([], list(keys), list(keys), [])
        _mt, pmt = _collect_machine_terms_for_day(model, x, "P1", MON, spec, "t")
        model.Add(x[("P1", keys[0])] == 1)
        total = model.NewIntVar(0, 3, "tot_pres")
        model.Add(total == sum(pmt))
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        assert solver.Value(total) == 1


class TestAlwaysPresential:
    """Activitats marcades «Sempre presencial» al catàleg: el solver no
    les pot convertir en no-presencials (queden fora del flip PRES→NP)."""

    def test_flagged_slots_detected(self):
        import pandas as pd
        from src.services.slot_catalog import always_presential_slot_ids
        cat = pd.DataFrame([
            {"slot_id": "ECO_A", "always_presential": 1},
            {"slot_id": "TC_A", "always_presential": 0},
            {"slot_id": "RM_A", "always_presential": ""},
        ])
        assert always_presential_slot_ids(cat) == {"ECO_A"}

    def test_missing_column_is_empty(self):
        import pandas as pd
        from src.services.slot_catalog import always_presential_slot_ids
        assert always_presential_slot_ids(pd.DataFrame([{"slot_id": "A"}])) == set()
        assert always_presential_slot_ids(None) == set()

    def test_catalog_roundtrip_keeps_flag(self, tmp_path):
        import pandas as pd
        from src.services.slot_catalog import (
            always_presential_slot_ids, load_slot_catalog, save_slot_catalog,
        )
        p = tmp_path / "slot_catalog.csv"
        save_slot_catalog(p, pd.DataFrame([
            {"slot_id": "ECO_A", "weekday": True, "always_presential": 1},
            {"slot_id": "TC_A", "weekday": True, "always_presential": 0},
        ]))
        assert always_presential_slot_ids(load_slot_catalog(p)) == {"ECO_A"}

    def test_legacy_catalog_without_column_loads(self, tmp_path):
        # Catàleg d'una versió anterior: la columna no hi és i s'ha de
        # sintetitzar a 0 sense petar.
        import pandas as pd
        from src.services.slot_catalog import (
            always_presential_slot_ids, load_slot_catalog,
        )
        p = tmp_path / "slot_catalog.csv"
        pd.DataFrame([
            {"slot_id": "ECO_A", "weekday": 1, "weekend": 0, "linked_to": "",
             "doubled": 0, "review": 0, "area": "", "metric_family": "",
             "assignee": "", "notes": ""},
        ]).to_csv(p, index=False, encoding="utf-8-sig")
        cat = load_slot_catalog(p)
        assert "always_presential" in cat.columns
        assert always_presential_slot_ids(cat) == set()


class TestNpFlipCap:
    """El cap DUR: només es pot convertir a NP l'excés per sobre del
    target presencial del període (mai baixar-ne)."""

    def _build(self, n_pres, target):
        model = cp_model.CpModel()
        keys = [_sk(f"M{i}", franja=f"F{i}") for i in range(n_pres)]
        x = {("P1", k): model.NewBoolVar(f"x{i}") for i, k in enumerate(keys)}
        for k in keys:
            model.Add(x[("P1", k)] == 1)  # cobertura: totes assignades
        np_flip = {}
        for i, k in enumerate(keys):
            nf = model.NewBoolVar(f"nf{i}")
            model.Add(nf <= x[("P1", k)])
            np_flip[("P1", k)] = nf
        specs = {MON: ([], list(keys), list(keys), [])}
        _add_flip_target_cap(
            model, x, {}, ["P1"], [MON], ["W"], {MON: "W"}, {MON: 1},
            {"P1": set()}, {("P1", MON): 100}, specs,
            weekly_pres_targets={("P1", "W"): target}, np_flip=np_flip,
        )
        total = model.NewIntVar(0, n_pres, "tot_np")
        model.Add(total == sum(np_flip.values()))
        return model, total

    def _max(self, model, total):
        model.Maximize(total)
        solver = cp_model.CpSolver()
        assert solver.Solve(model) == cp_model.OPTIMAL
        return solver.Value(total)

    def test_only_the_excess_can_be_flipped(self):
        # 5 presencials amb target 3 → com a molt 2 conversions.
        assert self._max(*self._build(5, 3)) == 2

    def test_at_target_no_flip_allowed(self):
        assert self._max(*self._build(3, 3)) == 0

    def test_below_target_no_flip_allowed(self):
        assert self._max(*self._build(2, 3)) == 0

    def test_empty_np_flip_is_noop(self):
        model = cp_model.CpModel()
        keys = [_sk("A")]
        x = {("P1", keys[0]): model.NewBoolVar("x_A")}
        specs = {MON: ([], list(keys), list(keys), [])}
        _add_flip_target_cap(
            model, x, {}, ["P1"], [MON], ["W"], {MON: "W"}, {MON: 1},
            {"P1": set()}, {("P1", MON): 100}, specs,
            weekly_pres_targets={("P1", "W"): 0}, np_flip={},
        )
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
