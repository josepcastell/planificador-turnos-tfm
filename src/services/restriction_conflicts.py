"""Detecció de conflictes entre les restriccions opcionals (pestanya
Restriccions) i el calendari INICIAL (`outputs/schedule_weekday.csv`).

Cada detector compara una restricció concreta amb l'schedule inicial i
retorna una llista de missatges human-readable. Si la llista no és buida,
la UI mostra una notificació a l'expander corresponent perquè l'usuari
sàpiga que aquesta restricció trencarà el calendari inicial (l'haurà de
**Regenerar** per veure el resultat amb la restricció aplicada).

L'objectiu és informatiu: cap d'aquestes funcions modifica res. La
detecció és aproximada — el solver acabarà decidint què canvia
realment quan es regenera."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.utils import normalize_slot
from src.domain.constants import WEEKDAY_CODES


def load_initial_schedule(
    path: Path | None = None,
) -> pd.DataFrame:
    """Llegeix el calendari INICIAL del disc. Retorna DataFrame buit si
    no existeix encara. Columnes esperades: day, franja, slot_id,
    professional, presentiality, work_mode."""
    p = Path(path) if path is not None else Path("outputs/schedule_weekday.csv")
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def _norm_pid(value: object) -> str:
    return str(value or "").strip().upper()


def detect_absences_conflicts(
    initial: pd.DataFrame, absences: pd.DataFrame,
) -> list[str]:
    """Per cada absència (prof, start..end), retorna missatges si el
    facultatiu té alguna assignació a l'inicial dins el rang."""
    if initial.empty or absences is None or absences.empty:
        return []
    if not {"professional_id", "start_day", "end_day"}.issubset(absences.columns):
        return []
    if not {"professional", "day"}.issubset(initial.columns):
        return []
    init = initial.copy()
    init["_pid"] = init["professional"].map(_norm_pid)
    init["_day"] = pd.to_datetime(init["day"], errors="coerce")
    msgs = []
    for row in absences.itertuples(index=False):
        pid = _norm_pid(getattr(row, "professional_id", ""))
        start = pd.to_datetime(getattr(row, "start_day", None), errors="coerce")
        end = pd.to_datetime(getattr(row, "end_day", None), errors="coerce")
        if not pid or pd.isna(start) or pd.isna(end):
            continue
        mask = (init["_pid"] == pid) & (init["_day"] >= start) & (init["_day"] <= end)
        if not mask.any():
            continue
        days = sorted(init.loc[mask, "_day"].dt.strftime("%Y-%m-%d").unique())
        slots = init.loc[mask, "slot_id"].astype(str).unique() if "slot_id" in init.columns else []
        sample = ", ".join(days[:3]) + (f" (+{len(days)-3} més)" if len(days) > 3 else "")
        slots_text = f" [{', '.join(sorted(set(slots)))}]" if len(slots) else ""
        msgs.append(f"**{pid}** té {len(days)} assignacions a l'inicial dins l'absència: {sample}{slots_text}")
    return msgs


def detect_eligibility_conflicts(
    initial: pd.DataFrame, eligibility: pd.DataFrame,
) -> list[str]:
    """Per cada (prof, slot) marcat allowed=0, comprova si l'inicial té
    aquesta assignació."""
    if initial.empty or eligibility is None or eligibility.empty:
        return []
    if not {"professional_id", "slot_id", "allowed"}.issubset(eligibility.columns):
        return []
    if not {"professional", "slot_id"}.issubset(initial.columns):
        return []
    blocked = eligibility[
        pd.to_numeric(eligibility["allowed"], errors="coerce").fillna(1).astype(int) == 0
    ]
    if blocked.empty:
        return []
    init = initial.copy()
    init["_pid"] = init["professional"].map(_norm_pid)
    init["_sid"] = init["slot_id"].astype(str).map(normalize_slot)
    msgs = []
    for row in blocked.itertuples(index=False):
        pid = _norm_pid(getattr(row, "professional_id", ""))
        sid = normalize_slot(getattr(row, "slot_id", ""))
        if not pid or not sid:
            continue
        mask = (init["_pid"] == pid) & (init["_sid"] == sid)
        n = int(mask.sum())
        if n > 0:
            msgs.append(
                f"**{pid}** té {n} assignacions de **{sid}** a l'inicial, però l'has marcat com no elegible."
            )
    return msgs


def detect_no_pres_weekday_conflicts(
    initial: pd.DataFrame, professionals: pd.DataFrame,
) -> list[str]:
    """Per cada facultatiu amb dies NP-only, comprova si l'inicial el té
    fent PRES en aquells dies."""
    if initial.empty or professionals is None or professionals.empty:
        return []
    if "no_pres_weekdays" not in professionals.columns:
        return []
    if not {"professional", "day", "presentiality"}.issubset(initial.columns):
        return []
    init = initial.copy()
    init["_pid"] = init["professional"].map(_norm_pid)
    init["_day"] = pd.to_datetime(init["day"], errors="coerce")
    init["_wkd"] = init["_day"].dt.weekday.map(
        lambda i: WEEKDAY_CODES[i] if pd.notna(i) and 0 <= int(i) < 7 else ""
    )
    init["_pres"] = init["presentiality"].astype(str).str.upper().eq("PRESENCIAL")
    msgs = []
    for row in professionals.itertuples(index=False):
        pid = _norm_pid(getattr(row, "professional_id", ""))
        codes = {
            c.strip().upper()
            for c in str(getattr(row, "no_pres_weekdays", "") or "").split(";")
            if c.strip()
        }
        if not pid or not codes:
            continue
        mask = (init["_pid"] == pid) & init["_wkd"].isin(codes) & init["_pres"]
        n = int(mask.sum())
        if n > 0:
            sample_days = sorted(init.loc[mask, "_day"].dt.strftime("%Y-%m-%d").unique())[:3]
            extra = "" if len(sample_days) < 3 else " (+ més)"
            msgs.append(
                f"**{pid}** té {n} PRES a l'inicial en dies marcats NP-only "
                f"({', '.join(sorted(codes))}): {', '.join(sample_days)}{extra}"
            )
    return msgs


def detect_pres_weekday_conflicts(
    initial: pd.DataFrame, professionals: pd.DataFrame,
) -> list[str]:
    """Mirror de no_pres: facultatiu amb PRES-only té NP a l'inicial?"""
    if initial.empty or professionals is None or professionals.empty:
        return []
    if "pres_weekdays" not in professionals.columns:
        return []
    if not {"professional", "day", "presentiality"}.issubset(initial.columns):
        return []
    init = initial.copy()
    init["_pid"] = init["professional"].map(_norm_pid)
    init["_day"] = pd.to_datetime(init["day"], errors="coerce")
    init["_wkd"] = init["_day"].dt.weekday.map(
        lambda i: WEEKDAY_CODES[i] if pd.notna(i) and 0 <= int(i) < 7 else ""
    )
    init["_np"] = init["presentiality"].astype(str).str.upper().eq("NO_PRESENCIAL")
    msgs = []
    for row in professionals.itertuples(index=False):
        pid = _norm_pid(getattr(row, "professional_id", ""))
        codes = {
            c.strip().upper()
            for c in str(getattr(row, "pres_weekdays", "") or "").split(";")
            if c.strip()
        }
        if not pid or not codes:
            continue
        mask = (init["_pid"] == pid) & init["_wkd"].isin(codes) & init["_np"]
        n = int(mask.sum())
        if n > 0:
            sample_days = sorted(init.loc[mask, "_day"].dt.strftime("%Y-%m-%d").unique())[:3]
            extra = "" if len(sample_days) < 3 else " (+ més)"
            msgs.append(
                f"**{pid}** té {n} NP a l'inicial en dies marcats PRES-only "
                f"({', '.join(sorted(codes))}): {', '.join(sample_days)}{extra}"
            )
    return msgs


def detect_fixed_machines_conflicts(
    initial: pd.DataFrame, catalog: pd.DataFrame,
) -> list[str]:
    """Per cada slot amb assignee fix al catàleg, comprova si l'inicial
    té un facultatiu DIFERENT al slot."""
    if initial.empty or catalog is None or catalog.empty:
        return []
    if "assignee" not in catalog.columns or "slot_id" not in catalog.columns:
        return []
    if not {"professional", "slot_id"}.issubset(initial.columns):
        return []
    fixed = catalog[
        catalog["assignee"].fillna("").astype(str).str.strip() != ""
    ]
    if fixed.empty:
        return []
    init = initial.copy()
    init["_pid"] = init["professional"].map(_norm_pid)
    init["_sid"] = init["slot_id"].astype(str).map(normalize_slot)
    msgs = []
    for row in fixed.itertuples(index=False):
        sid = normalize_slot(getattr(row, "slot_id", ""))
        assignee = _norm_pid(getattr(row, "assignee", ""))
        if not sid or not assignee:
            continue
        mask = init["_sid"] == sid
        if not mask.any():
            continue
        others = sorted(
            set(init.loc[mask, "_pid"]) - {assignee, "", "NONE", "NAN"}
        )
        if others:
            msgs.append(
                f"L'activitat **{sid}** està fixada a **{assignee}** però "
                f"l'inicial l'assigna a {', '.join(others)}."
            )
    return msgs


def detect_guards_conflicts(
    initial: pd.DataFrame, guards: pd.DataFrame,
) -> list[str]:
    """Per cada guàrdia (prof, day), comprova si l'inicial té el prof
    amb PRES aquell mateix dia (conflicte amb postguàrdia)."""
    if initial.empty or guards is None or guards.empty:
        return []
    if not {"professional_id", "day"}.issubset(guards.columns):
        return []
    if not {"professional", "day"}.issubset(initial.columns):
        return []
    init = initial.copy()
    init["_pid"] = init["professional"].map(_norm_pid)
    init["_day"] = pd.to_datetime(init["day"], errors="coerce").dt.strftime("%Y-%m-%d")
    msgs = []
    for row in guards.itertuples(index=False):
        pid = _norm_pid(getattr(row, "professional_id", ""))
        day = str(getattr(row, "day", "")).strip()
        if not pid or not day:
            continue
        mask = (init["_pid"] == pid) & (init["_day"] == day)
        if mask.any():
            n = int(mask.sum())
            msgs.append(
                f"**{pid}** té guàrdia el {day} però l'inicial li assigna "
                f"{n} slot(s) aquell dia."
            )
    return msgs
