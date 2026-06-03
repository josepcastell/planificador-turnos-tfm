from datetime import date

import pandas as pd

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS


def franja_sort_key(value: str) -> int:
    value = "" if pd.isna(value) else str(value).strip().upper()
    order = {
        "MATI": 10,
        "TARDA": 20,
        "NIT": 30,
        "": 90,
    }
    return order.get(value, 99)


def slot_sort_key(slot_id: str) -> tuple[int, str]:
    """Ordre estable sense dependre de noms concrets: slots de guàrdia
    (gestionats pel sistema) primer, després alfabètic pel slot_id."""
    slot = str(slot_id).strip().upper()
    group = 0 if slot in GUARDS_RESERVED_SLOT_IDS else 1
    return (group, slot)


def clean_display_value(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


# IMPORTANT — clau dels overrides:
# Els slot_id que el solver i el schedule.csv fan servir són SEMPRE
# normalitzats amb `normalize_slot` (majúscules + espais/guions → '_').
# El catàleg, en canvi, pot tenir slot_ids amb espais o guions
# escrits per la usuaria (p.ex. "REVISIO RM"). Si registrem els
# overrides sense aquesta normalització, `is_review_slot("REVISIO_RM")`
# busca "REVISIO_RM" al set però només hi té "REVISIO RM" → mai cap match.
# Per evitar-ho, els setters i les funcions de lectura passen TOTS pel
# mateix normalitzador.
from src.core.utils import normalize_slot as _norm_slot


# Override d'àrea per slot, registrat des del catàleg (no depèn del nom).
# Clau: slot_id normalitzat (majúscules + espais/guions → '_').
_SLOT_AREA_OVERRIDES: dict[str, str] = {}


def set_slot_area_overrides(mapping: dict | None) -> None:
    """Registra el mapa slot→àrea del catàleg. Crida-ho en carregar el
    catàleg (solver, UI i export PDF)."""
    _SLOT_AREA_OVERRIDES.clear()
    for k, v in (mapping or {}).items():
        _SLOT_AREA_OVERRIDES[_norm_slot(k)] = str(v).strip().upper()


# Override de família mètrica (TC/RM) per slot, des del catàleg.
_SLOT_METRIC_OVERRIDES: dict[str, str] = {}


def set_slot_metric_overrides(mapping: dict | None) -> None:
    """Registra el mapa slot→família mètrica (TC/RM) del catàleg."""
    _SLOT_METRIC_OVERRIDES.clear()
    for k, v in (mapping or {}).items():
        _SLOT_METRIC_OVERRIDES[_norm_slot(k)] = str(v).strip().upper()


# Conjunt de slots de revisió, registrat des del catàleg (no depèn del nom).
_SLOT_REVIEW_OVERRIDES: set[str] = set()


def set_slot_review_overrides(slot_ids) -> None:
    """Registra el conjunt de slots de revisió del catàleg."""
    _SLOT_REVIEW_OVERRIDES.clear()
    for s in (slot_ids or set()):
        _SLOT_REVIEW_OVERRIDES.add(_norm_slot(s))


def is_review_slot(slot_id: str) -> bool:
    """Slot de revisió SI I NOMÉS SI està marcat al catàleg amb
    `review=1` (registrat via `set_slot_review_overrides`). NO s'usa el
    nom de l'slot com a indicador (cap prefix). Aquesta és la decisió de
    l'usuari: el catàleg és l'única font de veritat per definir què és
    revisió. Si el catàleg no té cap slot marcat, no hi ha revisions."""
    return _norm_slot(slot_id) in _SLOT_REVIEW_OVERRIDES


def calendar_display_slot_area(slot_id: str) -> str:
    # Lookup amb la clau normalitzada (igual que `set_slot_area_overrides`).
    norm = _norm_slot(slot_id)
    override = _SLOT_AREA_OVERRIDES.get(norm)
    if override is not None:
        return override if override in {"DIR", "HUB", "DEL"} else "ALTRES"
    # Fallback per compatibilitat (sense catàleg registrat).
    if "DELTA" in norm:
        return "DEL"
    if "DIR" in norm:
        return "DIR"
    if "HUB" in norm:
        return "HUB"
    return "ALTRES"


def slot_comite_family(slot_id: str) -> str | None:
    """Família del slot per a comitès: 'HUB', 'DIR' o None. Es deriva de
    l'àrea del catàleg (DELTA i sense àrea → cap família de comitè)."""
    area = calendar_display_slot_area(slot_id)
    return area if area in {"DIR", "HUB"} else None


def calendar_display_area_class(area: str) -> str:
    area = clean_display_value(area).upper()
    if area == "DIR":
        return "schedule-area-dir"
    if area == "HUB":
        return "schedule-area-hub"
    if area == "DEL":
        return "schedule-area-del"
    return "schedule-area-other"


def calendar_display_slot_sort_key(slot_id: str) -> tuple[int, str]:
    slot = clean_display_value(slot_id).upper()
    area_order = {"DIR": 10, "HUB": 20, "DEL": 30, "ALTRES": 90}
    return (area_order.get(calendar_display_slot_area(slot), 90), slot)


def calendar_display_compact_slot_label(slot_id: str) -> str:
    """Etiqueta curta i genèrica: treu el sufix de família (_HUB/_DIR), que
    ja es mostra a part. Sense mapa hardcoded per slot."""
    slot = clean_display_value(slot_id).upper()
    for suffix in ("_HUB", "_DIR"):
        if slot.endswith(suffix) and len(slot) > len(suffix):
            slot = slot[: -len(suffix)]
            break
    return slot.replace("_", " ")


def calendar_display_franja_label(franja: str) -> str:
    value = clean_display_value(franja).upper()
    labels = {"MATI": "Matí", "TARDA": "Tarda", "NIT": "Nit", "12H": "12 h"}
    return labels.get(value, value.title())


def calendar_display_assignment_class(
    rows: list[dict[str, str]], slot_id: str, fallback_ids: set[str] | None = None
) -> str:
    presentialities = {clean_display_value(row.get("presentiality")).upper() for row in rows}
    work_modes = {clean_display_value(row.get("work_mode")).upper() for row in rows}
    professionals = {clean_display_value(row.get("professional")).upper() for row in rows}
    # TLD (comodí) i peonades es marquen en vermell perquè ressaltin: són els
    # candidats naturals a un canvi manual al visualitzador.
    if professionals & (fallback_ids or set()):
        return "tld"
    if "PEONADA" in work_modes:
        return "peonada"
    if "PRESENCIAL" in presentialities:
        return "presencial"
    return "default"


def calendar_display_professional_label(row) -> str:
    """Etiqueta del facultatiu per al render. Si l'assignació prové d'un
    flip NP→PRES (`is_flipped=1`), s'afegeix el prefix `T-` per indicar
    que el facultatiu informa de presència física a l'hospital (no
    necessàriament el dia de l'exploració). Accepta tant dicts com
    namedtuples (itertuples)."""
    if isinstance(row, dict):
        name = clean_display_value(row.get("professional"))
        flip_val = row.get("is_flipped", "")
    else:
        name = clean_display_value(getattr(row, "professional", ""))
        flip_val = getattr(row, "is_flipped", "")
    if not name:
        return name
    flip_str = str(flip_val if flip_val is not None else "").strip()
    is_flipped = flip_str in {"1", "1.0", "True", "true"}
    return f"T-{name}" if is_flipped else name


def calendar_display_day_status(day_key: str, current: date, non_working_days: set[str]) -> str:
    if current.weekday() >= 5:
        return "Cap de setmana"
    if day_key in non_working_days:
        return "No laborable"
    return ""


def slot_metric_family(slot_id: str, reporting_machine: str = "") -> str:
    """Família de mètrica (TC/RM/Altres). Surt de la columna del catàleg
    (override registrat); si l'slot no hi és, fallback a la convenció de
    nom (conté 'TC'/'RM')."""
    # Lookup amb la clau normalitzada (mateixa normalització que `set_*`).
    reporting = (
        "" if pd.isna(reporting_machine) else _norm_slot(reporting_machine)
    )
    slot = "" if pd.isna(slot_id) else _norm_slot(slot_id)
    metric_slot = reporting or slot

    override = _SLOT_METRIC_OVERRIDES.get(slot) or _SLOT_METRIC_OVERRIDES.get(metric_slot)
    if override is not None:
        return override if override in {"TC", "RM"} else "Altres"
    if "TC" in metric_slot:
        return "TC"
    if "RM" in metric_slot:
        return "RM"
    return "Altres"
