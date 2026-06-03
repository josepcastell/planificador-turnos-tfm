"""Tests unitaris per als data loaders."""

import pandas as pd
import pytest

from src.core.data_loader import _validate_columns, _read_csv_if_exists


class TestValidateColumns:
    def test_passes_when_all_columns_present(self):
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        _validate_columns(df, {"a", "b"}, "test.csv")  # no ha de llançar

    def test_raises_on_missing_column(self):
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="b"):
            _validate_columns(df, {"a", "b"}, "test.csv")

    def test_error_message_includes_filename(self):
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="fitxer_prova.csv"):
            _validate_columns(df, {"a", "missing"}, "fitxer_prova.csv")

    def test_raises_with_all_missing_columns_listed(self):
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError) as exc_info:
            _validate_columns(df, {"b", "c"}, "test.csv")
        msg = str(exc_info.value)
        assert "b" in msg
        assert "c" in msg

    def test_no_error_on_extra_columns(self):
        df = pd.DataFrame({"a": [1], "b": [2], "extra": [3]})
        _validate_columns(df, {"a", "b"}, "test.csv")  # no ha de llançar


class TestReadCsvIfExists:
    def test_returns_empty_df_when_file_missing(self, tmp_path):
        result = _read_csv_if_exists(tmp_path / "nonexistent.csv")
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_returns_empty_df_when_file_empty(self, tmp_path):
        empty_file = tmp_path / "empty.csv"
        empty_file.write_text("")
        result = _read_csv_if_exists(empty_file)
        assert result.empty

    def test_reads_existing_csv(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2\n3,4\n")
        result = _read_csv_if_exists(csv_file)
        assert len(result) == 2
        assert list(result.columns) == ["a", "b"]
