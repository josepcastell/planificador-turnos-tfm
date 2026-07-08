"""Tests per a la migracio del flag legacy `doubled` a 2 files al template.

Regla nova:
  - Una activitat doblada s'expressa com a DUES files independents al
    template (1 PRES + 1 NP), cada una editable/eliminable per separat.
  - Si llegim un CSV legacy amb files doubled=1 i presentiality=PRESENCIAL,
    s'afegeix la sibling NO_PRESENCIAL en memoria automaticament.

Aquesta migracio s'aplica a:
  - `src/services/planner_inputs.py` (load del template per a la UI).
  - `src/tools/build_weekday_calendar_from_templates.py` (generador del
    calendari operatiu del solver).

Aquests tests verifiquen que la migracio:
  - Afegeix la sibling NP quan el legacy te doubled=1 PRES.
  - No afecta files no-doblades (doubled=0).
  - No genera duplicats si la sibling NP ja existeix.
  - Posa doubled=0 a totes les files despres."""

import pandas as pd


def _migrate(templates_df: pd.DataFrame) -> pd.DataFrame:
    """Reprodueix la logica de migracio que aplica planner_inputs i el
    generador. Aqui la copiem inline per testejar-la aïllada."""
    df = templates_df.copy()
    df["doubled"] = (
        pd.to_numeric(df["doubled"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    )
    legacy_pres_doubled = (
        (df["doubled"] == 1)
        & (df["presentiality"].astype(str).str.upper() == "PRESENCIAL")
    )
    if legacy_pres_doubled.any():
        siblings = df.loc[legacy_pres_doubled].copy()
        siblings["presentiality"] = "NO_PRESENCIAL"
        siblings["doubled"] = 0
        df = pd.concat([df, siblings], ignore_index=True)
        df = df.drop_duplicates(
            subset=["weekday_name", "franja", "slot_id", "presentiality", "work_mode"],
            keep="last",
        ).reset_index(drop=True)
    df["doubled"] = 0
    return df


class TestDoubledMigration:
    def test_pres_doubled_splits_into_two_rows(self):
        df = pd.DataFrame([{
            "weekday_name": "MONDAY",
            "franja": "MATI",
            "slot_id": "RM_A",
            "presentiality": "PRESENCIAL",
            "work_mode": "NORMAL",
            "doubled": 1,
        }])
        out = _migrate(df)
        # Resultat: 2 files (1 PRES + 1 NP), ambdues amb doubled=0.
        assert len(out) == 2
        pres_rows = out[out["presentiality"] == "PRESENCIAL"]
        np_rows = out[out["presentiality"] == "NO_PRESENCIAL"]
        assert len(pres_rows) == 1
        assert len(np_rows) == 1
        assert (out["doubled"] == 0).all()

    def test_non_doubled_row_unchanged(self):
        df = pd.DataFrame([{
            "weekday_name": "MONDAY",
            "franja": "MATI",
            "slot_id": "TC_A",
            "presentiality": "PRESENCIAL",
            "work_mode": "NORMAL",
            "doubled": 0,
        }])
        out = _migrate(df)
        assert len(out) == 1
        assert out["doubled"].iloc[0] == 0
        assert out["presentiality"].iloc[0] == "PRESENCIAL"

    def test_existing_sibling_not_duplicated(self):
        # El template ja te 2 files (PRES doubled + NP no doblada).
        # Despres de la migracio, hauria de tenir nomes 2 files
        # (no afegir-ne una tercera duplicada).
        df = pd.DataFrame([
            {
                "weekday_name": "MONDAY", "franja": "MATI",
                "slot_id": "RM_A", "presentiality": "PRESENCIAL",
                "work_mode": "NORMAL", "doubled": 1,
            },
            {
                "weekday_name": "MONDAY", "franja": "MATI",
                "slot_id": "RM_A", "presentiality": "NO_PRESENCIAL",
                "work_mode": "NORMAL", "doubled": 0,
            },
        ])
        out = _migrate(df)
        assert len(out) == 2

    def test_np_doubled_left_unchanged(self):
        # doubled=1 amb NO_PRESENCIAL no s'expandeix automaticament
        # (la regla aplica nomes a PRES, perque pos 2 sempre es NP per spec).
        df = pd.DataFrame([{
            "weekday_name": "MONDAY", "franja": "MATI",
            "slot_id": "X", "presentiality": "NO_PRESENCIAL",
            "work_mode": "NORMAL", "doubled": 1,
        }])
        out = _migrate(df)
        # Una sola fila, amb doubled=0.
        assert len(out) == 1
        assert out["doubled"].iloc[0] == 0
        assert out["presentiality"].iloc[0] == "NO_PRESENCIAL"

    def test_multiple_pres_doubled_independent(self):
        # 2 PRES doublats a slots diferents -> 4 files (2 PRES + 2 NP).
        df = pd.DataFrame([
            {
                "weekday_name": "MONDAY", "franja": "MATI",
                "slot_id": "RM_A", "presentiality": "PRESENCIAL",
                "work_mode": "NORMAL", "doubled": 1,
            },
            {
                "weekday_name": "TUESDAY", "franja": "TARDA",
                "slot_id": "TC_B", "presentiality": "PRESENCIAL",
                "work_mode": "NORMAL", "doubled": 1,
            },
        ])
        out = _migrate(df)
        assert len(out) == 4
        assert (out["doubled"] == 0).all()
        assert (out["presentiality"] == "PRESENCIAL").sum() == 2
        assert (out["presentiality"] == "NO_PRESENCIAL").sum() == 2

    def test_empty_template_returns_empty(self):
        df = pd.DataFrame(columns=[
            "weekday_name", "franja", "slot_id",
            "presentiality", "work_mode", "doubled",
        ])
        out = _migrate(df)
        assert out.empty
