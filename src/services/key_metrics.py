"""Quadre de mètriques CLAU per facultatiu (pestanya Mètriques).

Compta com el solver: un bloc de màquines vinculades (aquell dia de la
setmana i franja, a Franges de treball, o la vinculació global del
catàleg) és UNA sola feina, presencial si algun membre ho és. Les
revisions es compten a part (una per dia) i les guàrdies no hi entren.
Una DOBLE FEINA és un dia en què el facultatiu té més d'una feina a la
mateixa franja, o més d'una presencial entre matí i tarda (els mateixos
límits que el solver relaxa quan falta gent)."""
from __future__ import annotations

import pandas as pd

from src.domain.constants import (
    GUARDS_RESERVED_SLOT_IDS,
    UNCOVERED_PROFESSIONAL,
    WEEKDAY_CODES,
)
from src.domain.schedule_format import is_review_slot

KEY_METRICS_COLUMNS = [
    "professional", "presencials", "no_presencials", "peonades",
    "revisions", "dobles_feines",
]
_NOT_PEOPLE = {"", "NONE", "NAN", UNCOVERED_PROFESSIONAL}


def _unit_of(templates_df, catalog_pairs):
    """slot → representant del seu bloc vinculat en un (dia-setmana, franja)."""
    from src.services.slot_catalog import (
        _groups_from_pairs,
        slot_link_pairs_by_weekday_franja,
    )
    by_wf = (
        slot_link_pairs_by_weekday_franja(templates_df)
        if templates_df is not None and not templates_df.empty else {}
    )
    cache: dict = {}

    def unit(weekday: str, franja: str, slot: str) -> str:
        key = (weekday, franja)
        if key not in cache:
            members: dict = {}
            pairs = list(by_wf.get(key, [])) + list(catalog_pairs or [])
            for group in _groups_from_pairs(pairs):
                rep = min(group)
                for s in group:
                    members[s] = rep
            cache[key] = members
        return cache[key].get(slot, slot)

    return unit


def key_metrics(
    schedule: pd.DataFrame,
    templates_df: pd.DataFrame | None = None,
    catalog_pairs=(),
    exclude=(),
) -> tuple[pd.DataFrame, int]:
    """(taula per facultatiu amb KEY_METRICS_COLUMNS, caselles SENSE COBRIR).
    `exclude`: facultatius que no surten a la taula (p. ex. el comodí)."""
    empty = pd.DataFrame(columns=KEY_METRICS_COLUMNS)
    if schedule is None or schedule.empty:
        return empty, 0
    df = schedule.copy()
    for col in ("franja", "presentiality", "work_mode"):
        if col not in df.columns:
            df[col] = ""
    df["day"] = df["day"].astype(str).str[:10]
    df["slot"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df["prof"] = df["professional"].fillna("").astype(str).str.strip().str.upper()
    for col in ("franja", "presentiality", "work_mode"):
        df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
    uncovered = int((df["prof"] == UNCOVERED_PROFESSIONAL).sum())

    skip = _NOT_PEOPLE | {str(p).strip().upper() for p in exclude}
    people = df[~df["prof"].isin(skip) & ~df["slot"].isin(GUARDS_RESERVED_SLOT_IDS)]
    if people.empty:
        return empty, uncovered
    is_review = people["slot"].map(is_review_slot)
    revisions = people[is_review].groupby("prof")["day"].nunique()

    work = people[~is_review].copy()
    unit = _unit_of(templates_df, catalog_pairs)
    weekdays = pd.to_datetime(work["day"], errors="coerce").dt.weekday
    work["unit"] = [
        unit(WEEKDAY_CODES[int(w)] if pd.notna(w) else "", f, s)
        for w, f, s in zip(weekdays, work["franja"], work["slot"])
    ]
    work["pres"] = work["presentiality"] == "PRESENCIAL"
    work["peo"] = work["work_mode"] == "PEONADA"
    units = (
        work.groupby(["prof", "day", "franja", "unit"], as_index=False)
        .agg(pres=("pres", "any"), peo=("peo", "any"))
    )
    units["ord_pres"] = units["pres"] & ~units["peo"]
    units["ord_np"] = ~units["pres"] & ~units["peo"]
    per = units.groupby("prof").agg(
        presencials=("ord_pres", "sum"),
        no_presencials=("ord_np", "sum"),
        peonades=("peo", "sum"),
    )
    busy_franja = units.groupby(["prof", "day", "franja"]).size()
    double_days = {k[:2] for k, n in busy_franja.items() if n > 1}
    day_pres = units[units["pres"] & (units["franja"] != "NIT")].groupby(["prof", "day"]).size()
    double_days |= {k for k, n in day_pres.items() if n > 1}
    doubles = pd.Series([p for p, _d in double_days], dtype=object).value_counts()

    profs = sorted(set(per.index) | set(revisions.index))
    out = pd.DataFrame({"professional": profs})
    out["presencials"] = out["professional"].map(per["presencials"]).fillna(0).astype(int)
    out["no_presencials"] = out["professional"].map(per["no_presencials"]).fillna(0).astype(int)
    out["peonades"] = out["professional"].map(per["peonades"]).fillna(0).astype(int)
    out["revisions"] = out["professional"].map(revisions).fillna(0).astype(int)
    out["dobles_feines"] = out["professional"].map(doubles).fillna(0).astype(int)
    return out[KEY_METRICS_COLUMNS], uncovered
