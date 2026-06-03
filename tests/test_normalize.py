"""Tests unitaris per les funcions de normalització."""

import pytest
from src.core.utils import normalize_slot
from src.solver import normalize_presentiality, normalize_work_mode, normalize_bool


class TestNormalizeSlot:
    def test_no_hardcoded_aliases(self):
        # normalize_slot només normalitza format (no remapeja noms del catàleg).
        assert normalize_slot("RM") == "RM"
        assert normalize_slot("3T") == "3T"
        assert normalize_slot("1,5T") == "1,5T"
        assert normalize_slot("TC3") == "TC3"

    def test_already_normalized_passes_through(self):
        assert normalize_slot("RM_HUB") == "RM_HUB"
        assert normalize_slot("TC_URG") == "TC_URG"
        assert normalize_slot("REVISA_RM") == "REVISA_RM"

    def test_strips_whitespace(self):
        assert normalize_slot("  RM_HUB  ") == "RM_HUB"

    def test_converts_to_uppercase(self):
        assert normalize_slot("tc_dir") == "TC_DIR"

    def test_replaces_spaces_with_underscore(self):
        assert normalize_slot("TC URG") == "TC_URG"

    def test_replaces_hyphens_with_underscore(self):
        assert normalize_slot("TC-URG") == "TC_URG"

    def test_handles_non_string_input(self):
        # Ha de gestionar inputs que no siguin str (conversió segura)
        assert normalize_slot(42) == "42"  # type: ignore


class TestNormalizePresentiality:
    def test_presencial_passes(self):
        assert normalize_presentiality("PRESENCIAL") == "PRESENCIAL"

    def test_no_presencial_passes(self):
        assert normalize_presentiality("NO_PRESENCIAL") == "NO_PRESENCIAL"

    def test_lowercase_presencial(self):
        assert normalize_presentiality("presencial") == "PRESENCIAL"

    def test_unknown_defaults_to_presencial(self):
        assert normalize_presentiality("TELETREBALL") == "PRESENCIAL"
        assert normalize_presentiality("") == "PRESENCIAL"

    def test_strips_whitespace(self):
        assert normalize_presentiality("  PRESENCIAL  ") == "PRESENCIAL"


class TestNormalizeWorkMode:
    def test_normal_passes(self):
        assert normalize_work_mode("NORMAL") == "NORMAL"

    def test_peonada_passes(self):
        assert normalize_work_mode("PEONADA") == "PEONADA"

    def test_lowercase(self):
        assert normalize_work_mode("peonada") == "PEONADA"

    def test_unknown_defaults_to_normal(self):
        assert normalize_work_mode("EXTRA") == "NORMAL"
        assert normalize_work_mode("") == "NORMAL"


class TestNormalizeBool:
    @pytest.mark.parametrize("value", [True, "1", "true", "True", "yes", "si", "sí", "y", "x"])
    def test_truthy_values(self, value):
        assert normalize_bool(value) is True

    @pytest.mark.parametrize("value", [False, "0", "false", "False", "no", "n", ""])
    def test_falsy_values(self, value):
        assert normalize_bool(value) is False
