"""Tests per als helpers de sticky drafts (table_state).

Cas critic: `_content_match` i el seu us dins `table_draft`. Quan el
draft (despres d'una edicio per `CheckboxColumn`) conte bool i el source
df re-llegit de disc conte int, el contingut es semanticament el mateix
pero el hash de panda canvia. Hem de detectar aixo i NO resetejar el
draft, per no fer perdre els `edited_rows` pendents del `data_editor`
(simptoma: «cal clicar dos cops la seguent casella»)."""

import pandas as pd

from src.ui.table_state import _content_match, _normalize_cell


class TestNormalizeCell:
    def test_bool_to_int_string(self):
        s = pd.Series([True, False, True])
        out = _normalize_cell(s)
        assert list(out) == ["1", "0", "1"]

    def test_int_to_string(self):
        s = pd.Series([1, 0, 1])
        out = _normalize_cell(s)
        assert list(out) == ["1", "0", "1"]

    def test_float_whole_to_int_string(self):
        s = pd.Series([1.0, 0.0, 2.0])
        out = _normalize_cell(s)
        assert list(out) == ["1", "0", "2"]

    def test_text_passes_through(self):
        s = pd.Series(["RM_A", "TC_B", ""])
        out = _normalize_cell(s)
        assert list(out) == ["RM_A", "TC_B", ""]

    def test_na_becomes_empty_string(self):
        s = pd.Series(["A", None, "B"])
        out = _normalize_cell(s)
        assert list(out) == ["A", "", "B"]


class TestContentMatch:
    def test_bool_matches_int(self):
        # El cas central: el draft (post-edit) te bool, el source (de disc)
        # te int. Han de coincidir per evitar el reset que descarta els
        # pending edits.
        draft = pd.DataFrame({
            "slot_id": ["A", "B", "C"],
            "allowed": [True, False, True],
        })
        source = pd.DataFrame({
            "slot_id": ["A", "B", "C"],
            "allowed": [1, 0, 1],
        })
        assert _content_match(draft, source, ["slot_id", "allowed"]) is True

    def test_different_content_no_match(self):
        a = pd.DataFrame({"slot_id": ["A", "B"], "allowed": [1, 1]})
        b = pd.DataFrame({"slot_id": ["A", "B"], "allowed": [1, 0]})
        assert _content_match(a, b, ["slot_id", "allowed"]) is False

    def test_different_row_count_no_match(self):
        a = pd.DataFrame({"slot_id": ["A"], "allowed": [1]})
        b = pd.DataFrame({"slot_id": ["A", "B"], "allowed": [1, 1]})
        assert _content_match(a, b, ["slot_id", "allowed"]) is False

    def test_different_text_no_match(self):
        a = pd.DataFrame({"slot_id": ["A"], "name": ["alpha"]})
        b = pd.DataFrame({"slot_id": ["A"], "name": ["beta"]})
        assert _content_match(a, b, ["slot_id", "name"]) is False

    def test_index_difference_ignored(self):
        # Els indexs no han de fer fallar la comparacio (un draft podria
        # tenir indexs no consecutius si ve d'un filtre/drop).
        a = pd.DataFrame({"slot_id": ["A", "B"], "allowed": [1, 0]}, index=[5, 9])
        b = pd.DataFrame({"slot_id": ["A", "B"], "allowed": [1, 0]}, index=[0, 1])
        assert _content_match(a, b, ["slot_id", "allowed"]) is True

    def test_mixed_text_and_bool(self):
        # Combina dues columnes: una de text, una de bool/int. Ambdues
        # han de matchejar per que el resultat global sigui True.
        a = pd.DataFrame({
            "slot_id": ["X", "Y"],
            "allowed": [True, False],
        })
        b = pd.DataFrame({
            "slot_id": ["X", "Y"],
            "allowed": [1, 0],
        })
        assert _content_match(a, b, ["slot_id", "allowed"]) is True

    def test_empty_frames_match(self):
        a = pd.DataFrame({"slot_id": [], "allowed": []})
        b = pd.DataFrame({"slot_id": [], "allowed": []})
        assert _content_match(a, b, ["slot_id", "allowed"]) is True
