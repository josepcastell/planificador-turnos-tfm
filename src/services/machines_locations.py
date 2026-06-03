"""Llistes de Màquines i Llocs (catàleg base): permeten generar
automàticament les activitats del catàleg com a combinacions
{màquina}_{lloc}."""

from pathlib import Path

import pandas as pd


MACHINES_PATH = Path("data/maquines.csv")
LOCATIONS_PATH = Path("data/llocs.csv")


def _load_simple_list(path: Path) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        df = pd.read_csv(path)
    except Exception:
        return []
    if "nom" not in df.columns:
        return []
    values = (
        df["nom"].fillna("").astype(str).str.strip().str.upper().tolist()
    )
    seen: list[str] = []
    seen_set: set[str] = set()
    for v in values:
        if v and v not in seen_set:
            seen.append(v)
            seen_set.add(v)
    return seen


def _save_simple_list(path: Path, items: list[str]) -> None:
    clean: list[str] = []
    seen: set[str] = set()
    for v in items:
        norm = str(v or "").strip().upper()
        if norm and norm not in seen:
            clean.append(norm)
            seen.add(norm)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"nom": clean}).to_csv(path, index=False)


def load_machines() -> list[str]:
    return _load_simple_list(MACHINES_PATH)


def save_machines(items: list[str]) -> None:
    _save_simple_list(MACHINES_PATH, items)


def load_locations() -> list[str]:
    return _load_simple_list(LOCATIONS_PATH)


def save_locations(items: list[str]) -> None:
    _save_simple_list(LOCATIONS_PATH, items)


def combination_slot_id(machine: str, location: str) -> str:
    """Nom canònic d'una combinació: «{màquina}_{lloc}»."""
    return f"{str(machine).strip().upper()}_{str(location).strip().upper()}"


def generate_missing_combinations(
    catalog_df: pd.DataFrame,
    machines: list[str],
    locations: list[str],
) -> tuple[pd.DataFrame, int]:
    """Afegeix al catàleg les combinacions {màquina}_{lloc} que no hi siguin.
    Cada fila nova s'afegeix amb àrea = lloc i família = màquina; la resta
    d'atributs per defecte. Retorna (nou_catàleg, nombre_d_afegits)."""
    if catalog_df is None:
        catalog_df = pd.DataFrame()
    existing_ids: set[str] = set()
    if "slot_id" in catalog_df.columns and not catalog_df.empty:
        existing_ids = set(
            catalog_df["slot_id"].fillna("").astype(str).str.strip().str.upper()
        )

    new_rows: list[dict] = []
    for machine in machines:
        for location in locations:
            sid = combination_slot_id(machine, location)
            if sid and sid not in existing_ids:
                new_rows.append({
                    "slot_id": sid,
                    "weekday": True,
                    "weekend": False,
                    "linked_to": "",
                    "doubled": 0,
                    "review": 0,
                    "area": str(location).strip().upper(),
                    "metric_family": str(machine).strip().upper(),
                    "assignee": "",
                    "notes": "",
                })

    if not new_rows:
        return catalog_df, 0
    combined = pd.concat([catalog_df, pd.DataFrame(new_rows)], ignore_index=True)
    return combined, len(new_rows)
