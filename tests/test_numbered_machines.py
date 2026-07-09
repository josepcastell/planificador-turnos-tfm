"""Numeració de màquines repetides al mateix lloc (ECO1, ECO2, RM1...)
i cobertura del cascade rename als fitxers de la roda i màquines fixes."""

import pandas as pd

from src.services.slot_catalog import numbered_machine_slot_name
from src.services.slot_rename import cascade_rename_slot_id_in_file


class TestNumberedMachineSlotName:
    def test_first_machine_keeps_plain_name(self):
        assert numbered_machine_slot_name([], "ECO", "ZONA_A") == ("ECO_ZONA_A", None)

    def test_second_machine_renames_first_and_numbers_both(self):
        name, rename = numbered_machine_slot_name(["ECO_ZONA_A"], "ECO", "ZONA_A")
        assert name == "ECO2_ZONA_A"
        assert rename == ("ECO_ZONA_A", "ECO1_ZONA_A")

    def test_third_machine_gets_next_number_without_rename(self):
        name, rename = numbered_machine_slot_name(
            ["ECO1_ZONA_A", "ECO2_ZONA_A"], "ECO", "ZONA_A",
        )
        assert name == "ECO3_ZONA_A"
        assert rename is None

    def test_same_family_other_area_does_not_collide(self):
        name, rename = numbered_machine_slot_name(
            ["ECO_ZONA_B"], "ECO", "ZONA_A",
        )
        assert name == "ECO_ZONA_A"
        assert rename is None

    def test_numbered_only_existing_continues_sequence(self):
        name, rename = numbered_machine_slot_name(["RM1_ZONA_C"], "RM", "ZONA_C")
        assert name == "RM2_ZONA_C"
        assert rename is None

    def test_gap_in_numbering_uses_max_plus_one(self):
        name, rename = numbered_machine_slot_name(
            ["RM1_ZONA_C", "RM3_ZONA_C"], "RM", "ZONA_C",
        )
        assert name == "RM4_ZONA_C"
        assert rename is None

    def test_case_and_whitespace_normalized(self):
        name, rename = numbered_machine_slot_name(
            [" eco_zona_a "], "eco", "zona_a",
        )
        assert name == "ECO2_ZONA_A"
        assert rename == ("ECO_ZONA_A", "ECO1_ZONA_A")

    def test_sequential_adds_never_regress_to_plain_name(self):
        # Regressió: després del primer rename, el nom pla quedava lliure
        # i la tercera màquina tornava a dir-se ECO_ZONA_A (i les següents
        # saltaven a 3, 4, 5 deixant la sèrie coixa).
        catalog: list[str] = []
        created = []
        for _ in range(5):
            name, rename = numbered_machine_slot_name(catalog, "ECO", "ZONA_A")
            if rename is not None:
                catalog.remove(rename[0])
                catalog.append(rename[1])
            catalog.append(name)
            created.append(name)
        assert created == [
            "ECO_ZONA_A", "ECO2_ZONA_A", "ECO3_ZONA_A", "ECO4_ZONA_A", "ECO5_ZONA_A",
        ]
        assert sorted(catalog) == [
            "ECO1_ZONA_A", "ECO2_ZONA_A", "ECO3_ZONA_A", "ECO4_ZONA_A", "ECO5_ZONA_A",
        ]

    def test_mixed_state_with_plain_leftover_self_heals(self):
        # Estat coix (fruit del bug): ECO1, ECO2, ECO (pla), ECO3. El pla
        # rep el primer número lliure (4) i la nova és la 5.
        name, rename = numbered_machine_slot_name(
            ["ECO1_ZONA_A", "ECO2_ZONA_A", "ECO_ZONA_A", "ECO3_ZONA_A"], "ECO", "ZONA_A",
        )
        assert rename == ("ECO_ZONA_A", "ECO4_ZONA_A")
        assert name == "ECO5_ZONA_A"


class TestMachineSeriesSlotIds:
    def test_digit_ending_family_does_not_contaminate(self):
        # Famílies TC3 i TC34 al mateix lloc: la sèrie es determina pels
        # CAMPS del catàleg, no pel nom — TC34_A no entra a la sèrie TC3.
        from src.services.slot_catalog import machine_series_slot_ids
        catalog = pd.DataFrame([
            {"slot_id": "TC3_A", "metric_family": "TC3", "area": "A"},
            {"slot_id": "TC34_A", "metric_family": "TC34", "area": "A"},
        ])
        assert machine_series_slot_ids(catalog, "TC3", "A") == ["TC3_A"]
        assert machine_series_slot_ids(catalog, "TC34", "A") == ["TC34_A"]

    def test_legacy_rows_without_fields_match_by_name(self):
        from src.services.slot_catalog import machine_series_slot_ids
        catalog = pd.DataFrame([
            {"slot_id": "ECO_ZONA_A", "metric_family": "", "area": ""},
            {"slot_id": "ALTRA_COSA", "metric_family": "", "area": ""},
        ])
        assert machine_series_slot_ids(catalog, "ECO", "ZONA_A") == ["ECO_ZONA_A"]


class TestCascadeRenameNewFiles:
    def test_renames_wheel_and_fixed_machines(self, tmp_path):
        wheel = tmp_path / "wheel_slots.csv"
        pd.DataFrame(
            [{"slot_id": "ECO_ZONA_A", "weekday_name": "", "professionals": "AA;BB"}]
        ).to_csv(wheel, index=False, encoding="utf-8-sig")
        fixed = tmp_path / "fixed_machines.csv"
        pd.DataFrame(
            [{"professional_id": "AA", "slot_id": "ECO_ZONA_A",
              "weekday_name": "MONDAY", "franja": "MATI"}]
        ).to_csv(fixed, index=False, encoding="utf-8-sig")

        assert cascade_rename_slot_id_in_file(wheel, "ECO_ZONA_A", "ECO1_ZONA_A") == 1
        assert cascade_rename_slot_id_in_file(fixed, "ECO_ZONA_A", "ECO1_ZONA_A") == 1
        assert pd.read_csv(wheel).iloc[0]["slot_id"] == "ECO1_ZONA_A"
        assert pd.read_csv(fixed).iloc[0]["slot_id"] == "ECO1_ZONA_A"

    def test_missing_file_is_noop(self, tmp_path):
        assert cascade_rename_slot_id_in_file(
            tmp_path / "inexistent.csv", "A", "B",
        ) == 0
