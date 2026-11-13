"""Roda d'assignació: activitats que es reparteixen per TORN ROTATORI.

L'usuari tria una activitat i (opcionalment) l'ordre de participants; cada
ocurrència (dia en què l'activitat existeix al calendari) va al següent de
la llista. L'índex del torn s'ancora a les ocurrències de TOT L'ANY, així
la roda continua entre mesos i regenerar dona sempre el mateix resultat.
Si al participant que li toca està absent aquell dia, o ja li toca una
altra roda aquell dia, se salta al següent (perd el torn). Abans no es
mirava la segona: dues rodes del mateix dia amb el mateix ordre volien
sempre la mateixa persona i el solver n'havia de trencar una.

Dos efectes al solver:
  · el torn és una preferència TOVA (data["wheel_preferences"] →
    total_wheel_pref_miss a core.py);
  · els INTEGRANTS són durs (data["wheel_members"]): els dies de la roda,
    ningú de fora la pot fer — si no hi ha cap integrant lliure, queda
    SENSE COBRIR.
Les preassignacions de l'usuari (canvis manuals, màquines fixes) prevalen
sobre tots dos (per (dia, slot))."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.services.table_io import read_table, save_table

WHEEL_PATH = Path("data/weekday/wheel_slots.csv")
# weekday_name buit = tots els dies; amb valor (MONDAY..FRIDAY), la roda
# només gira aquell dia de la setmana (amb la seva pròpia llista i torn).
# Una fila específica de dia PREVAL sobre la fila genèrica del mateix slot.
WHEEL_COLUMNS = ["slot_id", "weekday_name", "professionals"]


def load_wheel(path: Path = WHEEL_PATH) -> pd.DataFrame:
    df = read_table(Path(path), WHEEL_COLUMNS)
    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df["weekday_name"] = df["weekday_name"].fillna("").astype(str).str.strip().str.upper()
    df["professionals"] = df["professionals"].fillna("").astype(str).str.strip()
    return df[df["slot_id"] != ""].drop_duplicates(
        subset=["slot_id", "weekday_name"], keep="last"
    )


def save_wheel(df: pd.DataFrame, path: Path = WHEEL_PATH) -> None:
    out = df.copy()
    out["slot_id"] = out["slot_id"].fillna("").astype(str).str.strip().str.upper()
    if "weekday_name" not in out.columns:
        out["weekday_name"] = ""
    out["weekday_name"] = out["weekday_name"].fillna("").astype(str).str.strip().str.upper()
    out["professionals"] = out["professionals"].fillna("").astype(str).str.strip()
    out = out[out["slot_id"] != ""].drop_duplicates(
        subset=["slot_id", "weekday_name"], keep="last"
    )
    save_table(Path(path), out.sort_values(["slot_id", "weekday_name"]), WHEEL_COLUMNS)


def _regular_professionals(professionals_df: pd.DataFrame) -> list[str]:
    if professionals_df is None or professionals_df.empty:
        return []
    pid = professionals_df["professional_id"].fillna("").astype(str).str.strip().str.upper()
    fb = (
        pd.to_numeric(professionals_df.get("fallback", 0), errors="coerce")
        .fillna(0).astype(int)
        if "fallback" in professionals_df.columns
        else pd.Series(0, index=professionals_df.index)
    )
    return sorted({p for p, f in zip(pid, fb) if p and p != "NONE" and f == 0})


def _wd_of(day: str) -> str:
    from src.domain.constants import WEEKDAY_CODES
    try:
        return WEEKDAY_CODES[pd.Timestamp(day).weekday()]
    except (ValueError, TypeError):
        return ""


def _with_keys(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_slot"] = out["slot_id"].fillna("").astype(str).str.strip().str.upper()
    out["_day"] = out["day"].astype(str)
    return out


def _year_calendar(cal: pd.DataFrame, year_calendar_path) -> pd.DataFrame:
    """Ocurrències de TOT L'ANY (per ancorar l'índex del torn)."""
    ycal_path = Path(year_calendar_path)
    if ycal_path.exists() and ycal_path.stat().st_size > 0:
        try:
            return _with_keys(pd.read_csv(ycal_path, usecols=["day", "slot_id"]))
        except (OSError, ValueError, pd.errors.EmptyDataError, pd.errors.ParserError):
            pass
    return cal[["day", "slot_id", "_slot", "_day"]]


def _wheels_with_days(wheel: pd.DataFrame, ycal: pd.DataFrame, professionals_df):
    """[(slot_id, integrants en ordre, llista explícita?, dies de l'any en
    què gira)]. Sense llista vàlida, gira entre tots els facultatius
    regulars (i llavors no restringeix qui hi pot anar)."""
    valid = set(_regular_professionals(professionals_df))
    default_order = _regular_professionals(professionals_df)
    # Dies amb fila ESPECÍFICA per slot (la genèrica els ha de saltar).
    specific_days: dict[str, set[str]] = {}
    for w in wheel.itertuples(index=False):
        if w.weekday_name:
            specific_days.setdefault(w.slot_id, set()).add(w.weekday_name)
    out = []
    for w in wheel.itertuples(index=False):
        order = [
            p.strip().upper() for p in str(w.professionals or "").split(";")
            if p.strip() and p.strip().upper() in valid
        ]
        explicit = bool(order)
        order = order or default_order
        if not order:
            continue
        occ_days = sorted(ycal.loc[ycal["_slot"] == w.slot_id, "_day"].unique())
        if w.weekday_name:
            # Roda d'un dia concret: torn propi sobre les ocurrències
            # d'AQUELL dia de la setmana.
            occ_days = [d for d in occ_days if _wd_of(d) == w.weekday_name]
        else:
            # Roda genèrica: salta els dies coberts per una fila específica.
            spec = specific_days.get(w.slot_id, set())
            if spec:
                occ_days = [d for d in occ_days if _wd_of(d) not in spec]
        out.append((w.slot_id, order, explicit, occ_days))
    return out


def expand_wheel_preassignments(
    month_calendar_slots: pd.DataFrame,
    professionals_df: pd.DataFrame,
    full_blocked=None,
    franja_blocked=None,
    year_calendar_path: Path | str = "data/weekday/calendar_slots.csv",
    wheel_path: Path = WHEEL_PATH,
    slot_blocked=None,
) -> pd.DataFrame:
    """Files de preassignació (fixed=1, source='wheel') per al mes.
    `slot_blocked`: {(facultatiu, dia, ACTIVITAT)} que no la pot fer aquell
    dia (excepcions d'elegibilitat per dia): el torn passa al següent."""
    cols = ["professional_id", "day", "slot_id", "franja", "presentiality",
            "work_mode", "fixed", "source"]
    wheel = load_wheel(wheel_path)
    if (wheel.empty or month_calendar_slots is None
            or month_calendar_slots.empty):
        return pd.DataFrame(columns=cols)
    full_blocked = full_blocked or set()
    franja_blocked = franja_blocked or set()
    slot_blocked = slot_blocked or set()

    cal = _with_keys(month_calendar_slots)
    month_days = set(cal["_day"])
    ycal = _year_calendar(cal, year_calendar_path)

    rows: list[dict] = []
    # Qui ja té el torn d'una roda cada dia: (persona, franges, presencial
    # de dia). Una persona no pot fer dues màquines la mateixa franja ni
    # dues presencials el mateix dia: si una roda anterior ja l'ha triada,
    # aquesta passa al següent de la seva llista.
    taken: dict[str, list] = {}
    for sid, order, _explicit, occ_days in _wheels_with_days(wheel, ycal, professionals_df):
        for idx, day in enumerate(occ_days):
            if day not in month_days:
                continue
            day_rows = cal[(cal["_slot"] == sid) & (cal["_day"] == day)]
            if day_rows.empty:
                continue
            franges = {
                str(r.get("franja", "") or "").upper()
                for _, r in day_rows.iterrows()
            }
            pres_day = any(
                str(r.get("presentiality", "") or "").upper() == "PRESENCIAL"
                and str(r.get("franja", "") or "").upper() != "NIT"
                for _, r in day_rows.iterrows()
            )
            chosen = None
            for k in range(len(order)):
                cand = order[(idx + k) % len(order)]
                if (cand, day) in full_blocked:
                    continue
                if any((cand, day, fr) in franja_blocked for fr in franges):
                    continue
                if (cand, day, sid) in slot_blocked:
                    continue
                if any(
                    who == cand and (fr_other & franges or (pres_other and pres_day))
                    for who, fr_other, pres_other in taken.get(day, [])
                ):
                    continue
                chosen = cand
                break
            if chosen is None:
                continue  # tothom bloquejat: el solver tria entre els integrants
            taken.setdefault(day, []).append((chosen, franges, pres_day))
            seen_inst = set()
            for _, r in day_rows.iterrows():
                inst = (
                    str(r.get("franja", "") or "").upper(),
                    str(r.get("presentiality", "") or "").upper(),
                    str(r.get("work_mode", "") or "").upper(),
                )
                if inst in seen_inst:
                    continue  # posicions duplicades: només 1 per instància
                seen_inst.add(inst)
                rows.append({
                    "professional_id": chosen,
                    "day": day,
                    "slot_id": sid,
                    "franja": inst[0],
                    "presentiality": inst[1],
                    "work_mode": inst[2],
                    "fixed": 1,
                    "source": "wheel",
                })
    return pd.DataFrame(rows, columns=cols)


def wheel_members_by_day_slot(
    month_calendar_slots: pd.DataFrame,
    professionals_df: pd.DataFrame,
    year_calendar_path: Path | str = "data/weekday/calendar_slots.csv",
    wheel_path: Path = WHEEL_PATH,
) -> dict:
    """{(dia, slot_id): integrants} de les rodes amb llista d'integrants,
    per als dies del mes en què giren. Al solver és DUR: aquells dies,
    ningú de fora de la roda pot fer l'activitat."""
    wheel = load_wheel(wheel_path)
    if (wheel.empty or month_calendar_slots is None
            or month_calendar_slots.empty):
        return {}
    cal = _with_keys(month_calendar_slots)
    ycal = _year_calendar(cal, year_calendar_path)
    out: dict = {}
    for sid, order, explicit, occ_days in _wheels_with_days(wheel, ycal, professionals_df):
        if not explicit:
            continue
        slot_days = set(cal.loc[cal["_slot"] == sid, "_day"])
        for day in occ_days:
            if day in slot_days:
                out[(day, sid)] = frozenset(order)
    return out
