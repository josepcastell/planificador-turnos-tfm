"""Les vinculacions (punts de color de les franges) han de sobreviure als
canvis del catàleg d'activitats. Abans, desar el catàleg reescrivia el
fitxer de franges sense les columnes linked_to, doubled i l'alternança
setmanal (s'esborraven totes), i reanomenar una activitat no actualitzava
les vinculacions que hi apuntaven."""

import pandas as pd

from src.services.slot_catalog import load_slot_catalog, persist_slot_catalog_with_templates
from src.services.slot_rename import (
    cascade_rename_in_templates,
    cascade_rename_linked_to,
    cascade_rename_slot_id,
)

CATALOG = """slot_id,weekday,weekend,linked_to,doubled,review,always_presential,area,metric_family,assignee,notes
TC1_A,1,0,,0,0,0,A,TC,,
TIPUS UN_A,1,0,,0,0,0,A,TIPUS UN,,
TIPUS DOS_A,1,0,,0,0,0,A,TIPUS DOS,,
RM2_A,1,0,,0,0,0,A,RM,,
"""

TEMPLATES = """weekday_name,franja,slot_id,presentiality,work_mode,required_staff,is_active,doubled,linked_to,week_interval,week_offset
MONDAY,MATI,TIPUS DOS_A,PRESENCIAL,NORMAL,1,1,0,,1,0
MONDAY,MATI,TC1_A,PRESENCIAL,NORMAL,1,1,0,TIPUS UN_A,1,0
MONDAY,MATI,TIPUS UN_A,PRESENCIAL,NORMAL,1,1,0,TIPUS DOS_A,1,0
TUESDAY,TARDA,TIPUS DOS_A,PRESENCIAL,NORMAL,1,1,0,,1,0
TUESDAY,TARDA,RM2_A,PRESENCIAL,NORMAL,1,1,0,TIPUS DOS_A,2,1
"""


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "weekday").mkdir(parents=True)
    catalog = tmp_path / "data" / "slot_catalog.csv"
    templates = tmp_path / "data" / "weekday" / "weekly_slot_templates.csv"
    catalog.write_text(CATALOG, encoding="utf-8")
    templates.write_text(TEMPLATES, encoding="utf-8")
    return catalog, templates


def _links(templates):
    df = pd.read_csv(templates).fillna("")
    return sorted(
        (r.weekday_name, r.franja, r.slot_id, r.linked_to)
        for r in df.itertuples() if r.linked_to
    )


def test_saving_the_catalog_keeps_links_and_alternation(tmp_path, monkeypatch):
    catalog, templates = _setup(tmp_path, monkeypatch)
    before = _links(templates)
    persist_slot_catalog_with_templates(load_slot_catalog(catalog), catalog, templates, None)
    assert _links(templates) == before
    rm2 = pd.read_csv(templates).query("slot_id == 'RM2_A'").iloc[0]
    assert (rm2.week_interval, rm2.week_offset) == (2, 1)


def test_renaming_an_activity_moves_its_links(tmp_path, monkeypatch):
    # Mateixa seqüència que l'editor del catàleg quan es canvia un nom.
    catalog, templates = _setup(tmp_path, monkeypatch)
    for old, new in (("TIPUS UN_A", "TU_A"), ("TIPUS DOS_A", "TD_A")):
        existing = load_slot_catalog(catalog)
        existing.loc[existing["slot_id"].str.upper() == old, "slot_id"] = new
        existing = cascade_rename_linked_to(existing, old, new)
        cascade_rename_in_templates(templates, old, new)
        cascade_rename_slot_id(old, new, 2026)
        persist_slot_catalog_with_templates(existing, catalog, templates, None)
    assert _links(templates) == [
        ("MONDAY", "MATI", "TC1_A", "TU_A"),
        ("MONDAY", "MATI", "TU_A", "TD_A"),
        ("TUESDAY", "TARDA", "RM2_A", "TD_A"),
    ]
