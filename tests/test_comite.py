"""Tests del servei comite."""

from pathlib import Path

import pandas as pd

from src.services.comite import (
    COMITE_COLUMNS,
    load_comite_assignments,
    save_comite_assignments,
)
from src.solver.preprocessing import expand_comite_to_days


def _row(**kwargs) -> dict:
    base = {
        "professional_id": "AA",
        "comite_name": "",
        "comite_type": "ZONA_A",
        "specific_day": "",
        "weekday": "",
        "notes": "",
    }
    base.update(kwargs)
    return base


def test_save_filters_invalid_rows(tmp_path: Path):
    path = tmp_path / "comite.csv"
    df = pd.DataFrame([
        _row(professional_id="AA", comite_type="ZONA_A", specific_day="2026-04-15"),
        _row(professional_id="CC", comite_type="ZONA_B", weekday="TUESDAY"),
        _row(professional_id="ZZ", comite_type="ZONA_A", specific_day="2026-04-15"),
        # comite_type buit = invàlid (l'àrea és lliure: qualsevol valor no buit val).
        _row(professional_id="AA", comite_type="", specific_day="2026-04-15"),
        _row(professional_id="AA", comite_type="ZONA_A"),
    ])
    save_comite_assignments(path, df, valid_professionals={"AA", "CC"})
    loaded = load_comite_assignments(path)
    assert sorted(loaded["professional_id"].tolist()) == ["AA", "CC"]
    assert list(loaded.columns) == COMITE_COLUMNS


def test_specific_day_takes_precedence_over_weekday(tmp_path: Path):
    path = tmp_path / "comite.csv"
    df = pd.DataFrame([
        _row(professional_id="AA", comite_type="ZONA_A",
             specific_day="2026-04-15", weekday="TUESDAY"),
    ])
    save_comite_assignments(path, df, valid_professionals={"AA"})
    loaded = load_comite_assignments(path)
    row = loaded.iloc[0]
    assert pd.notna(row["specific_day"])
    assert row["weekday"] == ""


def test_expand_specific_day():
    df = pd.DataFrame([
        _row(professional_id="AA", comite_type="ZONA_A",
             specific_day=pd.Timestamp("2026-04-15")),
    ])
    out = expand_comite_to_days(df, unique_days=["2026-04-14", "2026-04-15", "2026-04-16"])
    assert out == [("AA", "2026-04-15", "ZONA_A")]


def test_expand_specific_day_outside_range_skips():
    df = pd.DataFrame([
        _row(professional_id="AA", comite_type="ZONA_A",
             specific_day=pd.Timestamp("2026-05-01")),
    ])
    out = expand_comite_to_days(df, unique_days=["2026-04-14", "2026-04-15"])
    assert out == []


def test_expand_recurrent_weekday():
    days = [f"2026-04-{d:02d}" for d in range(1, 31)]
    df = pd.DataFrame([
        _row(professional_id="CC", comite_type="ZONA_B",
             specific_day=pd.NaT, weekday="TUESDAY"),
    ])
    out = expand_comite_to_days(df, unique_days=days)
    days_with_comite = sorted(d for _, d, _ in out)
    assert days_with_comite == ["2026-04-07", "2026-04-14", "2026-04-21", "2026-04-28"]


def test_expand_dedupes():
    df = pd.DataFrame([
        _row(professional_id="AA", comite_type="ZONA_A",
             specific_day=pd.Timestamp("2026-04-15")),
        _row(professional_id="AA", comite_type="ZONA_A",
             specific_day=pd.Timestamp("2026-04-15")),
    ])
    out = expand_comite_to_days(df, unique_days=["2026-04-15"])
    assert len(out) == 1
