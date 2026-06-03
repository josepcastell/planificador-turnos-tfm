"""Tests del servei slot_catalog."""

from pathlib import Path

import pandas as pd

from src.services.slot_catalog import (
    SLOT_CATALOG_COLUMNS,
    default_slot_catalog,
    fill_weekday_templates_with_defaults,
    fill_weekend_templates_with_defaults,
    load_slot_catalog,
    save_slot_catalog,
    seed_slot_catalog_if_missing,
    sync_weekday_templates_with_catalog,
    sync_weekend_templates_with_catalog,
    weekday_slot_ids,
    weekend_slot_ids,
)


def test_default_catalog_no_templates_uses_constants():
    df = default_slot_catalog()
    tc_dir = df[df["slot_id"] == "TC_DIR"].iloc[0]
    rm_3t = df[df["slot_id"] == "3T_DIR"].iloc[0]
    assert bool(tc_dir["weekday"]) is True
    assert bool(rm_3t["weekend"]) is True
    assert list(df.columns) == SLOT_CATALOG_COLUMNS


def test_default_catalog_preserves_existing_template_state():
    weekday = pd.DataFrame([{"slot_id": "TC_DIR"}, {"slot_id": "RM_HUB"}])
    weekend = pd.DataFrame([{"slot_id": "TC_RM_HUB"}])
    df = default_slot_catalog(weekday_templates_df=weekday, weekend_templates_df=weekend)

    # Slots present in templates → marked
    assert bool(df[df["slot_id"] == "TC_DIR"].iloc[0]["weekday"]) is True
    assert bool(df[df["slot_id"] == "TC_RM_HUB"].iloc[0]["weekend"]) is True
    # GD/POST_GUARDIA/REFUERZO are reserved for the Guards tab and excluded
    assert "GD" not in df["slot_id"].tolist()
    # New slot from templates is added
    assert "TC_RM_HUB" in df["slot_id"].tolist()


def test_load_handles_legacy_applies_to_column(tmp_path: Path):
    path = tmp_path / "catalog.csv"
    path.write_text(
        "slot_id,applies_to,notes\n"
        "TC_DIR,WEEKDAY,a\n"
        "RM_HUB,BOTH,b\n"
        "RM3T,WEEKEND,c\n",
        encoding="utf-8",
    )
    df = load_slot_catalog(path)
    tc = df[df["slot_id"] == "TC_DIR"].iloc[0]
    rm = df[df["slot_id"] == "RM_HUB"].iloc[0]
    assert bool(tc["weekday"]) is True and bool(tc["weekend"]) is False
    assert bool(rm["weekday"]) is True and bool(rm["weekend"]) is True


def test_save_then_load_roundtrip(tmp_path: Path):
    path = tmp_path / "catalog.csv"
    df = pd.DataFrame(
        [
            {"slot_id": "TC_DIR", "weekday": True, "weekend": False, "notes": ""},
            {"slot_id": "RM3T", "weekday": False, "weekend": True, "notes": "weekend only"},
        ]
    )
    save_slot_catalog(path, df)
    loaded = load_slot_catalog(path)
    assert loaded["slot_id"].tolist() == ["TC_DIR", "RM3T"]
    assert loaded["weekday"].astype(bool).tolist() == [True, False]
    assert loaded["weekend"].astype(bool).tolist() == [False, True]


def test_filters_by_scope():
    df = pd.DataFrame(
        [
            {"slot_id": "TC_DIR", "weekday": True, "weekend": False, "notes": ""},
            {"slot_id": "RM_HUB", "weekday": True, "weekend": True, "notes": ""},
            {"slot_id": "RM3T", "weekday": False, "weekend": True, "notes": ""},
        ]
    )
    assert weekday_slot_ids(df) == ["RM_HUB", "TC_DIR"]
    assert weekend_slot_ids(df) == ["RM3T", "RM_HUB"]


def test_seed_creates_file_when_missing(tmp_path: Path):
    path = tmp_path / "missing.csv"
    df = seed_slot_catalog_if_missing(path)
    assert path.exists()
    assert not df.empty


def test_seed_keeps_existing_file(tmp_path: Path):
    path = tmp_path / "catalog.csv"
    custom = pd.DataFrame(
        [{"slot_id": "CUSTOM", "weekday": True, "weekend": False, "notes": ""}]
    )
    save_slot_catalog(path, custom)

    loaded = seed_slot_catalog_if_missing(path)
    assert loaded["slot_id"].tolist() == ["CUSTOM"]


def test_sync_weekday_drops_unknown_slots():
    catalog = pd.DataFrame(
        [{"slot_id": "TC_DIR", "weekday": True, "weekend": False, "notes": ""}]
    )
    templates = pd.DataFrame(
        [
            {"weekday_name": "MONDAY", "franja": "MATI", "slot_id": "TC_DIR",
             "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
             "required_staff": 1, "is_active": 1},
            {"weekday_name": "TUESDAY", "franja": "MATI", "slot_id": "OBSOLETE",
             "presentiality": "PRESENCIAL", "work_mode": "NORMAL",
             "required_staff": 1, "is_active": 1},
        ]
    )
    out = sync_weekday_templates_with_catalog(catalog, templates)
    assert "OBSOLETE" not in set(out["slot_id"])
    assert "TC_DIR" in set(out["slot_id"])


def test_sync_weekday_does_not_add_default_for_new_slot():
    """sync is prune-only: adding a new catalog slot must NOT auto-fill the
    weekday templates. The user opts-in via the "Omplir per defecte" button."""
    catalog = pd.DataFrame(
        [{"slot_id": "NEW_SLOT", "weekday": True, "weekend": False, "notes": ""}]
    )
    templates = pd.DataFrame(columns=[
        "weekday_name", "franja", "slot_id", "presentiality", "work_mode",
        "required_staff", "is_active",
    ])
    out = sync_weekday_templates_with_catalog(catalog, templates)
    assert out.empty


def test_fill_weekday_templates_with_defaults_adds_monday_mati_row():
    catalog = pd.DataFrame(
        [{"slot_id": "NEW_SLOT", "weekday": True, "weekend": False, "notes": ""}]
    )
    templates = pd.DataFrame(columns=[
        "weekday_name", "franja", "slot_id", "presentiality", "work_mode",
        "required_staff", "is_active",
    ])
    out = fill_weekday_templates_with_defaults(catalog, templates)
    new = out[out["slot_id"] == "NEW_SLOT"].iloc[0]
    assert new["weekday_name"] == "MONDAY"
    assert new["franja"] == "MATI"
    assert new["presentiality"] == "PRESENCIAL"


def test_sync_weekend_does_not_add_default_for_new_slot():
    catalog = pd.DataFrame(
        [{"slot_id": "WK_NEW", "weekday": False, "weekend": True, "notes": ""}]
    )
    templates = pd.DataFrame(columns=[
        "weekday_name", "franja", "slot_id", "reporting_machine",
        "presentiality", "work_mode", "required_staff", "is_active",
    ])
    out = sync_weekend_templates_with_catalog(catalog, templates)
    assert out.empty


def test_fill_weekend_templates_with_defaults_adds_saturday_row():
    catalog = pd.DataFrame(
        [{"slot_id": "WK_NEW", "weekday": False, "weekend": True, "notes": ""}]
    )
    templates = pd.DataFrame(columns=[
        "weekday_name", "franja", "slot_id", "reporting_machine",
        "presentiality", "work_mode", "required_staff", "is_active",
    ])
    out = fill_weekend_templates_with_defaults(catalog, templates)
    new = out[out["slot_id"] == "WK_NEW"].iloc[0]
    assert new["weekday_name"] == "SATURDAY"
    assert new["franja"] == "12H"
    assert new["reporting_machine"] == "WK_NEW"
