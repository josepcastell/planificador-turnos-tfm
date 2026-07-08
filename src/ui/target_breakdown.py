"""Resum per facultatiu del calendari. Mostra a sota del render una
taula amb el nombre de PRES i NP_ord ordinàries de cada facultatiu
per ajudar a veure si el calendari està equilibrat."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.domain.month_scope import in_logical_months
from src.domain.schedule_format import is_review_slot
from src.services.professionals_info import (
    base_pid as _base_pid,
    fallback_professional_ids as _fallback_ids,
)
from src.services.slot_catalog import slot_secondary_ids


def _read_schedule_for_breakdown() -> tuple[pd.DataFrame, str]:
    """Llegeix l'únic calendari (`schedule_weekday.csv`)."""
    path = Path("outputs/schedule_weekday.csv")
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path), ""
    return pd.DataFrame(), ""


def _load_regulars_for_summary() -> list[str]:
    """Llista de facultatius REGULARS (no fallback / comodí, no NONE),
    en majúscules. S'usa perquè el resum mostri tots els facultatius
    encara que tinguin 0 assignacions al scope."""
    pp = Path("data/professionals.csv")
    if not pp.exists() or pp.stat().st_size == 0:
        return []
    try:
        df = pd.read_csv(pp)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return []
    if "professional_id" not in df.columns:
        return []
    pid = df["professional_id"].astype(str).str.strip().str.upper()
    fb = (
        pd.to_numeric(df.get("fallback", 0), errors="coerce").fillna(0).astype(int)
        if "fallback" in df.columns
        else pd.Series([0] * len(df))
    )
    mask = (pid != "") & (pid != "NONE") & (fb == 0)
    # Col·lapsa duplicats per base_pid (XX, XX_2 → XX).
    return sorted({_base_pid(p) for p in pid[mask]})


def render_target_breakdown_per_prof(
    year: int,
    months: list[int],
) -> None:
    """Render el resum global per facultatiu: una taula amb el nombre de
    PRES i NP_ord ordinàries de cada facultatiu al scope. Permet veure
    d'un cop d'ull si el calendari és equilibrat."""
    schedule, which = _read_schedule_for_breakdown()
    if schedule.empty or "day" not in schedule.columns:
        return

    schedule["day_dt"] = pd.to_datetime(schedule["day"], errors="coerce")
    schedule = schedule[in_logical_months(schedule["day_dt"], year, months)].copy()
    if schedule.empty:
        return

    # Filtres: només màquines ordinàries (sense revisions, guàrdies,
    # màquines secundàries) ni peonades. Els duplicats de facultatiu
    # (sufix _2, _3, ...) es comporten com el mateix a l'agregat.
    schedule["_sid"] = schedule["slot_id"].astype(str).str.strip().str.upper()
    schedule["_pid"] = (
        schedule["professional"].astype(str).str.strip().str.upper()
        .map(_base_pid)
    )
    schedule["_pres"] = schedule["presentiality"].astype(str).str.upper()
    schedule["_wm"] = schedule["work_mode"].astype(str).str.upper()
    schedule["_is_review"] = schedule["slot_id"].astype(str).map(is_review_slot)

    try:
        catalog = pd.read_csv("data/slot_catalog.csv")
        secondary = slot_secondary_ids(catalog)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        secondary = set()
    schedule["_is_secondary"] = schedule["_sid"].isin(secondary)
    schedule["_is_guard"] = schedule["_sid"].isin(GUARDS_RESERVED_SLOT_IDS)

    # Filtre del comodí: llegit de professionals.csv (fallback=1) via la
    # font única — mai un id hardcoded, que divergia de la resta de l'app.
    fb_set = {"", "NONE", "NAN"} | _fallback_ids()
    machine = schedule[
        ~schedule["_is_review"]
        & ~schedule["_is_secondary"]
        & ~schedule["_is_guard"]
        & ~schedule["_pid"].isin(fb_set)
    ].copy()
    if machine.empty:
        return

    # Comptadors per facultatiu (suma a tot el scope). Categories
    # mútuament exclusives:
    #   - PRES = NORMAL i PRESENCIAL
    #   - NP_ord = NORMAL i NO_PRESENCIAL
    #   - Peonades = work_mode == PEONADA (qualsevol presencialitat)
    is_peonada = machine["_wm"] == "PEONADA"
    machine["_pres_flag"] = (
        (machine["_pres"] == "PRESENCIAL") & ~is_peonada
    ).astype(int)
    machine["_np_ord_flag"] = (
        (machine["_pres"] == "NO_PRESENCIAL") & ~is_peonada
    ).astype(int)
    machine["_peo_flag"] = is_peonada.astype(int)

    # Target setmanal (5 dies efectius). S'usa només al caption com a
    # referència informativa.
    try:
        rules = pd.read_csv("data/planning_rules.csv")
        r5 = rules[rules["active_days"] == 5]
        target_pres_5 = int(r5["target_presential"].iloc[0]) if not r5.empty else 3
        target_mach_5 = int(r5["target_machines"].iloc[0]) if not r5.empty else 4
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        target_pres_5, target_mach_5 = 3, 4
    target_np_5 = max(0, target_mach_5 - target_pres_5)

    # Nombre de setmanes lògiques al scope: dies / 5 (aproximat).
    n_days = machine["day_dt"].dt.normalize().nunique()
    n_weeks = max(1, n_days // 5) if n_days > 0 else 1

    label = f"calendari {which}" if which else "calendari"
    st.markdown(f"**Comptadors per facultatiu — {label}**")

    per_prof = machine.groupby("_pid", as_index=False).agg(
        PRES=("_pres_flag", "sum"),
        NP_ord=("_np_ord_flag", "sum"),
        Peonades=("_peo_flag", "sum"),
    )
    # Inclou facultatius regulars sense cap assignació (0/0/0/0).
    regulars = _load_regulars_for_summary()
    if regulars:
        present = set(per_prof["_pid"].astype(str).str.upper())
        missing = [p for p in regulars if p not in present]
        if missing:
            per_prof = pd.concat(
                [
                    per_prof,
                    pd.DataFrame({
                        "_pid": missing,
                        "PRES": 0, "NP_ord": 0, "Peonades": 0,
                    }),
                ],
                ignore_index=True,
            )
    per_prof = per_prof.rename(columns={"_pid": "Facultatiu"})
    per_prof = per_prof.sort_values("Facultatiu").reset_index(drop=True)
    view_cols = ["Facultatiu", "PRES", "NP_ord", "Peonades"]
    # Alçada fixada a totes les files perquè la taula NO sigui scrollable
    # (es vegin tots els facultatius d'un cop).
    st.dataframe(
        per_prof[view_cols], hide_index=True, width="stretch",
        height=38 + 35 * (len(per_prof) + 1),
    )
    st.caption(
        f"Target per facultatiu regular i setmana completa (5 dies): "
        f"**{target_pres_5} PRES**, **{target_np_5} NP_ord**. "
        f"Scope: {n_weeks} setmana(es). "
        "Categories exclusives (PRES/NP_ord/Peonades). "
        "No compten revisions, màquines secundàries ni guàrdies."
    )
