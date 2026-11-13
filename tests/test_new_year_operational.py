"""La sessió conté tots els anys: en generar per primer cop un any nou, les
absències i guàrdies dels altres anys no hi han de fer res (abans el primer
trimestre del 2027 petava amb KeyError 'day' si només hi havia absències
del 2026, amb «La guardia cae en un día que no existe» si hi havia
guàrdies del 2026 i amb «Hay días de indisponibilidad que no existen» si
hi havia indisponibilitats manuals del 2026)."""

import pandas as pd

from src.tools.apply_absences_to_calendar import apply_absences_to_calendar
from src.tools.apply_guards_to_calendar import apply_guards_to_calendar
from src.tools.split_unavailability_layer import split_unavailability_layer


def _base_2027(tmp_path):
    path = tmp_path / "base_calendar_2027.csv"
    days = pd.date_range("2027-01-01", "2027-12-31", freq="D")
    pd.DataFrame({
        "day": days.strftime("%Y-%m-%d"),
        "is_working_day": (days.weekday < 5).astype(int),
    }).to_csv(path, index=False)
    return path


def test_absences_of_another_year_leave_an_empty_layer(tmp_path):
    absences = tmp_path / "absences.csv"
    pd.DataFrame([{
        "professional_id": "P1", "start_day": "2026-11-16",
        "end_day": "2026-11-20", "absence_type": "vacances",
    }]).to_csv(absences, index=False)
    out = tmp_path / "unavailability_from_absences_2027.csv"

    apply_absences_to_calendar(str(_base_2027(tmp_path)), str(absences), str(out))

    result = pd.read_csv(out)
    assert result.empty
    assert list(result.columns) == ["professional_id", "day", "reason", "source", "notes"]


def test_an_absence_across_new_year_keeps_only_this_year(tmp_path):
    absences = tmp_path / "absences.csv"
    pd.DataFrame([{
        "professional_id": "P1", "start_day": "2026-12-30",
        "end_day": "2027-01-02", "absence_type": "vacances",
    }]).to_csv(absences, index=False)
    out = tmp_path / "unavailability_from_absences_2027.csv"

    apply_absences_to_calendar(str(_base_2027(tmp_path)), str(absences), str(out))

    assert pd.read_csv(out)["day"].tolist() == ["2027-01-01", "2027-01-02"]


def test_guards_of_another_year_are_ignored_but_31_dec_frees_1_jan(tmp_path):
    guards = tmp_path / "guards.csv"
    pd.DataFrame([
        {"professional_id": "P1", "day": "2026-11-10", "guard_kind": "guardia"},
        {"professional_id": "P2", "day": "2026-12-31", "guard_kind": "guardia"},
        {"professional_id": "P3", "day": "2026-12-31", "guard_kind": "refuerzo"},
    ]).to_csv(guards, index=False)
    out = tmp_path / "guard_constraints_2027.csv"

    apply_guards_to_calendar(str(_base_2027(tmp_path)), str(guards), str(out))

    result = pd.read_csv(out)
    assert result[["professional_id", "day", "constraint_type"]].values.tolist() == [
        ["P2", "2027-01-01", "post_guard_free"],
    ]


def test_only_guards_of_another_year_leave_an_empty_layer(tmp_path):
    guards = tmp_path / "guards.csv"
    pd.DataFrame([
        {"professional_id": "P1", "day": "2026-11-10", "guard_kind": "refuerzo"},
    ]).to_csv(guards, index=False)
    out = tmp_path / "guard_constraints_2027.csv"

    apply_guards_to_calendar(str(_base_2027(tmp_path)), str(guards), str(out))

    result = pd.read_csv(out)
    assert result.empty
    assert "constraint_type" in result.columns


def test_unavailability_of_another_year_is_left_out(tmp_path):
    unav = tmp_path / "unavailability_2027.csv"
    pd.DataFrame([
        {"professional_id": "P1", "day": "2026-12-07", "reason": "",
         "source": "weekday_manual", "notes": ""},
        {"professional_id": "P2", "day": "2027-01-04", "reason": "",
         "source": "weekday_manual", "notes": ""},
    ]).to_csv(unav, index=False)
    out = tmp_path / "unavailability_weekday_2027.csv"

    split_unavailability_layer(str(unav), str(_base_2027(tmp_path)), str(out))

    assert pd.read_csv(out)[["professional_id", "day"]].values.tolist() == [
        ["P2", "2027-01-04"],
    ]


def test_a_missing_day_of_this_year_is_still_an_error(tmp_path):
    base = tmp_path / "base_calendar_2027.csv"
    pd.DataFrame({"day": ["2027-01-04"], "is_working_day": [1]}).to_csv(base, index=False)
    unav = tmp_path / "unavailability_2027.csv"
    pd.DataFrame([
        {"professional_id": "P1", "day": "2027-01-05", "reason": "",
         "source": "weekday_manual", "notes": ""},
    ]).to_csv(unav, index=False)

    import pytest
    with pytest.raises(ValueError, match="no existen en base_calendar"):
        split_unavailability_layer(str(unav), str(base), str(tmp_path / "out.csv"))
