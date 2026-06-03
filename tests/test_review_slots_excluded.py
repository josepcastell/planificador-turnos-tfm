"""Tests per garantir que els slots de revisio queden AÏLLATS del solver:

  1. NO entren a `flippable_machine_keys` (no els podem flipar a PRES).
  2. NO entren a `machine_keys` ni `presential_machine_keys` (no compten
     al target setmanal de maquines ni de presencials).
  3. NO afecten les metriques (vegeu tests/test_metrics_tab.py — la
     funcio `is_review_slot` ja filtra a metrics_tab).

Si el solver acaba convertint un slot de revisio a PRES o el compta com a
maquina al weekly target, alguna d'aquestes assercions ha de fallar."""

from src.solver.constraints import _build_machine_term_specs


def _sk(day, franja, slot_id, presentiality="NO_PRESENCIAL", work_mode="NORMAL", position=1):
    return (day, franja, slot_id, presentiality, work_mode, position)


class TestReviewSlotsExcluded:
    def test_review_slot_not_in_flippable(self):
        # Un slot de revisio NO ha d'entrar a flippable_machine_keys
        # (la 5a entrada del tuple specs).
        review_sk = _sk("2026-01-06", "MATI", "REVISA_RM", "NO_PRESENCIAL")
        normal_sk = _sk("2026-01-06", "MATI", "RM_HUB", "NO_PRESENCIAL")
        keys_by_day = {"2026-01-06": [review_sk, normal_sk]}
        specs = _build_machine_term_specs(keys_by_day, review_slots={"REVISA_RM"})
        coupling, uncoupled, machine, presential, flippable = specs["2026-01-06"]
        assert review_sk not in flippable
        # El normal SI hi és (no és revisió ni guàrdia, és NORMAL NO_PRES).
        assert normal_sk in flippable

    def test_review_slot_not_in_machine_keys(self):
        # Tampoc al machine_keys: el target setmanal de màquines NO compta
        # les revisions com a màquines.
        review_sk = _sk("2026-01-06", "MATI", "REVISA_RM", "NO_PRESENCIAL")
        normal_sk = _sk("2026-01-06", "MATI", "RM_HUB", "PRESENCIAL")
        keys_by_day = {"2026-01-06": [review_sk, normal_sk]}
        specs = _build_machine_term_specs(keys_by_day, review_slots={"REVISA_RM"})
        coupling, uncoupled, machine, presential, flippable = specs["2026-01-06"]
        assert review_sk not in machine
        assert normal_sk in machine

    def test_review_slot_not_in_presential_keys(self):
        # Tampoc al presential_machine_keys: el target presencial NO inclou
        # revisions. (Encara que el template tingués un slot REV com a PRES,
        # cosa que no hauria de passar perquè els reviews son NP per defecte.)
        review_sk = _sk("2026-01-06", "MATI", "REVISA_RM", "PRESENCIAL")
        keys_by_day = {"2026-01-06": [review_sk]}
        specs = _build_machine_term_specs(keys_by_day, review_slots={"REVISA_RM"})
        coupling, uncoupled, machine, presential, flippable = specs["2026-01-06"]
        assert review_sk not in presential

    def test_review_slot_excluded_regardless_of_case(self):
        # `slot_id in review_slots` ha de funcionar amb el case d'sk[2].
        # Aquí review_slots i sk[2] son tots dos majuscules (com a la
        # producció després de la normalitzacio a build_weekday).
        review_sk = _sk("2026-01-06", "MATI", "REVISA_TC")
        keys_by_day = {"2026-01-06": [review_sk]}
        specs = _build_machine_term_specs(keys_by_day, review_slots={"REVISA_TC"})
        _coupling, _uncoupled, machine, presential, flippable = specs["2026-01-06"]
        assert not machine
        assert not presential
        assert not flippable


class TestIsReviewSlotCatalogOnly:
    """`is_review_slot` és True SI I NOMÉS SI el slot està al catàleg amb
    `review=1` (registrat via set_slot_review_overrides). NO s'usa cap
    prefix de nom: 'REVISA_*', 'REV_*', etc. no es detecten automàticament.
    L'usuari ha de marcar explícitament cada revisió al catàleg."""

    def teardown_method(self):
        # Reset overrides per no afectar altres tests.
        from src.domain.schedule_format import set_slot_review_overrides
        set_slot_review_overrides(set())

    def test_in_overrides_is_review(self):
        from src.domain.schedule_format import (
            is_review_slot, set_slot_review_overrides,
        )
        set_slot_review_overrides({"REVISA_TC", "REVISA_RM"})
        assert is_review_slot("REVISA_TC") is True
        assert is_review_slot("REVISA_RM") is True

    def test_not_in_overrides_not_review_even_with_rev_prefix(self):
        # REV_OLD comença per REV però NO està al catàleg → no és revisió.
        from src.domain.schedule_format import (
            is_review_slot, set_slot_review_overrides,
        )
        set_slot_review_overrides({"REVISA_TC"})
        assert is_review_slot("REV_OLD") is False
        assert is_review_slot("REVISA_RM") is False

    def test_empty_overrides_no_reviews(self):
        # Sense overrides al catàleg, RES és revisió (ni REV*).
        from src.domain.schedule_format import (
            is_review_slot, set_slot_review_overrides,
        )
        set_slot_review_overrides(set())
        assert is_review_slot("REVISA_RM") is False
        assert is_review_slot("REV_ANYTHING") is False
        assert is_review_slot("RM_HUB") is False

    def test_custom_name_marked_in_catalog_is_review(self):
        # El catàleg pot marcar com a revisió un nom qualsevol (no
        # necessàriament amb prefix REV).
        from src.domain.schedule_format import (
            is_review_slot, set_slot_review_overrides,
        )
        set_slot_review_overrides({"CONTROL_RM", "FOLLOWUP_TC"})
        assert is_review_slot("CONTROL_RM") is True
        assert is_review_slot("FOLLOWUP_TC") is True
        assert is_review_slot("RM_HUB") is False

    def test_spaces_and_dashes_normalized(self):
        # Bug real observat: el cataleg te 'REVISIO RM' (amb espai), el
        # schedule emet 'REVISIO_RM' (espai -> guio baix via normalize_slot).
        # Ambdues representacions han de coincidir al lookup.
        from src.domain.schedule_format import (
            is_review_slot, set_slot_review_overrides,
        )
        set_slot_review_overrides({"REVISIO RM", "REVISIO TC"})  # del cataleg
        # El schedule consulta amb el slot_id NORMALITZAT del calendari.
        assert is_review_slot("REVISIO_RM") is True
        assert is_review_slot("REVISIO_TC") is True
        # I tambe amb el format original (forma menys habitual pero suportada).
        assert is_review_slot("REVISIO RM") is True
        # Lower-case input tambe ha de funcionar (normalize_slot upper-case).
        assert is_review_slot("revisio rm") is True


class TestSoftObjectivesExcludeReview:
    """Defensa-en-profunditat: si un slot de revisió acaba al calendari
    operatiu amb presentiality=PRESENCIAL (cas patològic d'una config
    incorrecta), els objectius tous també l'han d'excloure perquè no
    quedi comptat com a presencial al balanç."""

    def test_count_balance_excludes_review_even_if_pres(self):
        from ortools.sat.python import cp_model
        from src.solver.objectives_balance import _add_count_balance

        # Slot de revisió amb presentiality=PRESENCIAL (cas patològic).
        review_sk = _sk("2026-01-06", "MATI", "REVISA_RM", "PRESENCIAL")
        # Slot normal PRES (control).
        normal_sk = _sk("2026-01-06", "MATI", "TC_HUB", "PRESENCIAL")
        model = cp_model.CpModel()
        x = {
            ("P1", review_sk): model.NewBoolVar("x_rev"),
            ("P1", normal_sk): model.NewBoolVar("x_norm"),
        }
        # Forcem que totes dues estiguin assignades a P1.
        model.Add(x[("P1", review_sk)] == 1)
        model.Add(x[("P1", normal_sk)] == 1)

        # Sense excloure revisions, count seria 2. Amb la defensa, count = 1.
        (_l1, presential_counts, *_rest) = _add_count_balance(
            model, x, active_professionals=["P1"], professionals=["P1"],
            slot_keys=[review_sk, normal_sk],
            average_capacity_pct={"P1": 100},
            review_slots={"REVISA_RM"},
        )
        solver = cp_model.CpSolver()
        assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        # El comptador de P1 ha de ser 1 (nomes el normal compta).
        assert solver.Value(presential_counts["P1"]) == 1
