"""Cascade rename d'un slot_id a tots els fitxers de dades que el
referencien. Es crida des de l'editor de catàleg quan l'usuari canvia
el nom d'un slot existent perquè les seves característiques
(vinculacions, elegibilitats, targets, preassignacions, franges)
es mantinguin sense haver-les de reconfigurar.

Fitxers actualitzats:
  - data/slot_catalog.csv (columna linked_to)         ← AL DATAFRAME EN MEMÒRIA
  - data/eligibility.csv (columna slot_id)
  - data/weekday/preassignments.csv (columna slot_id)
  - data/weekday/template_overrides_{year}.csv (columna slot_id)
  - data/weekday/fixed_machines.csv (columna slot_id)
  - data/weekday/wheel_slots.csv (columna slot_id)
  - data/weekday/weekly_slot_templates.csv (columna slot_id)  ← JA ES FA A L'EDITOR

Limitacions conegudes:
  - data/derived/*.csv es regeneren al següent run de Generar, no cal cascada.
  - data/weekday/calendar_slots.csv és derivat dels templates; es regenera
    quan els templates canvien.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def cascade_rename_linked_to(
    catalog_df: pd.DataFrame, old_name: str, new_name: str,
) -> pd.DataFrame:
    """Actualitza la columna `linked_to` del cataleg en memoria perquè
    les altres files que apuntaven a `old_name` ara apuntin a
    `new_name`. Retorna el DataFrame modificat (in-place per a la
    columna; el caller pot ignorar el retorn)."""
    if catalog_df is None or catalog_df.empty:
        return catalog_df
    if "linked_to" not in catalog_df.columns:
        return catalog_df
    old = str(old_name).strip().upper()
    new = str(new_name).strip().upper()
    if not old or old == new:
        return catalog_df
    mask = (
        catalog_df["linked_to"].fillna("").astype(str).str.strip().str.upper()
        == old
    )
    if mask.any():
        catalog_df.loc[mask, "linked_to"] = new
    return catalog_df


def cascade_rename_slot_id_in_file(
    path: Path, old_name: str, new_name: str, column: str = "slot_id",
) -> int:
    """Reemplaça `old_name` per `new_name` a la columna `column` d'un
    CSV existent. No fa res si el fitxer no existeix o no té la
    columna. Retorna el nombre de files actualitzades (0 si cap)."""
    p = Path(path)
    if not p.exists():
        return 0
    try:
        df = pd.read_csv(p)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return 0
    if column not in df.columns or df.empty:
        return 0
    old = str(old_name).strip().upper()
    new = str(new_name).strip().upper()
    if not old or old == new:
        return 0
    mask = (
        df[column].fillna("").astype(str).str.strip().str.upper() == old
    )
    n = int(mask.sum())
    if n == 0:
        return 0
    df.loc[mask, column] = new
    df.to_csv(p, index=False)
    return n


def cascade_rename_slot_id(old_name: str, new_name: str, year: int) -> int:
    """Actualitza totes les referències a un slot_id renomenat als
    fitxers de dades. Retorna el total de files modificades.

    NO toca `data/slot_catalog.csv` ni `data/weekday/weekly_slot_templates.csv`:
    el catàleg el cascadem en memòria abans de persistir (vegeu
    `cascade_rename_linked_to`) i els templates ja s'actualitzen
    expressament al codi de l'editor."""
    total = 0
    files = [
        Path("data/eligibility.csv"),
        Path("data/weekday/preassignments.csv"),
        Path(f"data/weekday/template_overrides_{year}.csv"),
        # Màquines fixes i roda d'assignació: també referencien slot_id —
        # sense això, un canvi de nom hi deixaria referències mortes.
        Path("data/weekday/fixed_machines.csv"),
        Path("data/weekday/wheel_slots.csv"),
    ]
    for path in files:
        total += cascade_rename_slot_id_in_file(path, old_name, new_name)
    # L'activitat de les regles d'equilibri (mode «activitat») també és
    # un slot_id: si es renombra, l'equilibri deixaria de casar.
    total += cascade_rename_slot_id_in_file(
        Path("data/planning_rules.csv"), old_name, new_name,
        column="balance_activity",
    )
    return total
