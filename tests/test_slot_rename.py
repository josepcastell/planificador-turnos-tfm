"""Tests del cascade rename: quan es renomena un slot, totes les
referències que hi apuntaven s'actualitzen automaticament (linked_to
al cataleg, slot_id a la resta de fitxers)."""

import pandas as pd
import pytest

from src.services.slot_rename import (
    cascade_rename_linked_to,
    cascade_rename_slot_id,
    cascade_rename_slot_id_in_file,
)


class TestCascadeRenameLinkedTo:
    def test_updates_linked_to_in_other_rows(self):
        df = pd.DataFrame({
            "slot_id": ["A", "B", "C"],
            "linked_to": ["", "A", "A"],
        })
        cascade_rename_linked_to(df, "A", "ALPHA")
        assert df.loc[df["slot_id"] == "B", "linked_to"].iloc[0] == "ALPHA"
        assert df.loc[df["slot_id"] == "C", "linked_to"].iloc[0] == "ALPHA"

    def test_case_insensitive_match(self):
        df = pd.DataFrame({
            "slot_id": ["B"], "linked_to": ["  a  "],
        })
        cascade_rename_linked_to(df, "A", "ALPHA")
        assert df["linked_to"].iloc[0] == "ALPHA"

    def test_no_match_no_change(self):
        df = pd.DataFrame({"slot_id": ["B"], "linked_to": ["X"]})
        cascade_rename_linked_to(df, "A", "ALPHA")
        assert df["linked_to"].iloc[0] == "X"

    def test_same_name_noop(self):
        df = pd.DataFrame({"slot_id": ["B"], "linked_to": ["A"]})
        cascade_rename_linked_to(df, "A", "A")
        assert df["linked_to"].iloc[0] == "A"

    def test_empty_inputs(self):
        # No falla amb DataFrame buit, columna absent, noms buits.
        empty = pd.DataFrame()
        assert cascade_rename_linked_to(empty, "A", "B") is empty
        no_col = pd.DataFrame({"slot_id": ["A"]})
        cascade_rename_linked_to(no_col, "A", "B")
        df = pd.DataFrame({"slot_id": ["B"], "linked_to": ["A"]})
        cascade_rename_linked_to(df, "", "B")
        assert df["linked_to"].iloc[0] == "A"


class TestCascadeRenameSlotIdInFile:
    def test_updates_csv(self, tmp_path):
        p = tmp_path / "eligibility.csv"
        pd.DataFrame({
            "professional_id": ["P1", "P2", "P1"],
            "slot_id": ["TC_HUB", "TC_HUB", "RM_HUB"],
            "allowed": [1, 1, 1],
        }).to_csv(p, index=False)
        n = cascade_rename_slot_id_in_file(p, "TC_HUB", "TC4")
        assert n == 2
        result = pd.read_csv(p)
        assert sorted(result["slot_id"].tolist()) == ["RM_HUB", "TC4", "TC4"]

    def test_no_match_zero(self, tmp_path):
        p = tmp_path / "x.csv"
        pd.DataFrame({"slot_id": ["A", "B"]}).to_csv(p, index=False)
        assert cascade_rename_slot_id_in_file(p, "Z", "Y") == 0

    def test_missing_file_zero(self, tmp_path):
        assert cascade_rename_slot_id_in_file(
            tmp_path / "noexist.csv", "A", "B",
        ) == 0

    def test_empty_old_or_same_no_change(self, tmp_path):
        p = tmp_path / "x.csv"
        pd.DataFrame({"slot_id": ["A"]}).to_csv(p, index=False)
        assert cascade_rename_slot_id_in_file(p, "", "X") == 0
        assert cascade_rename_slot_id_in_file(p, "A", "A") == 0

    def test_custom_column(self, tmp_path):
        p = tmp_path / "cat.csv"
        pd.DataFrame({
            "slot_id": ["A", "B"],
            "linked_to": ["X", "Y"],
        }).to_csv(p, index=False)
        n = cascade_rename_slot_id_in_file(p, "X", "Z", column="linked_to")
        assert n == 1
        result = pd.read_csv(p)
        assert result["linked_to"].tolist() == ["Z", "Y"]


class TestCascadeRenameSlotIdMultiFile:
    @pytest.fixture
    def _make_data(self, tmp_path, monkeypatch):
        # Workspace temporal amb tots els CSV que el cascade toca.
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "metrics").mkdir(parents=True)
        (tmp_path / "data" / "weekday").mkdir(parents=True)
        pd.DataFrame({
            "professional_id": ["P1"], "slot_id": ["TC_HUB"], "allowed": [1],
        }).to_csv(tmp_path / "data" / "eligibility.csv", index=False)
        pd.DataFrame({
            "professional_id": ["P1"], "slot_id": ["TC_HUB"],
            "target_count": [3],
        }).to_csv(tmp_path / "data" / "metrics" / "machine_targets.csv",
                  index=False)
        pd.DataFrame({
            "professional_id": ["P1"], "day": ["2026-01-06"],
            "slot_id": ["TC_HUB"], "fixed": [1],
            "source": ["user"], "notes": [""],
        }).to_csv(tmp_path / "data" / "weekday" / "preassignments.csv",
                  index=False)
        pd.DataFrame({
            "day": ["2026-01-06"], "franja": ["MATI"],
            "slot_id": ["TC_HUB"], "presentiality": ["PRESENCIAL"],
            "work_mode": ["NORMAL"], "action": ["add"],
            "required_staff": [1], "notes": [""],
        }).to_csv(
            tmp_path / "data" / "weekday" / "template_overrides_2026.csv",
            index=False,
        )
        return tmp_path

    def test_cascades_to_all_files(self, _make_data):
        n = cascade_rename_slot_id("TC_HUB", "TC4", year=2026)
        assert n == 4  # 1 fila per fitxer
        # Tot els fitxers han d'estar actualitzats.
        for rel in (
            "data/eligibility.csv",
            "data/metrics/machine_targets.csv",
            "data/weekday/preassignments.csv",
            "data/weekday/template_overrides_2026.csv",
        ):
            assert (_make_data / rel).exists()
            df = pd.read_csv(_make_data / rel)
            assert "TC_HUB" not in df["slot_id"].astype(str).tolist()
            assert "TC4" in df["slot_id"].astype(str).tolist()
