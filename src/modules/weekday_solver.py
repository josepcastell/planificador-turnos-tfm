from pathlib import Path

from src.services.no_pres_weekdays import no_pres_weekday_days
from src.services.non_working_weekdays import (
    WEEKDAY_CODES_SET,
    non_working_weekdays_unavailability,
    reductions_from_non_working_weekdays,
)
from src.services.pres_weekdays import pres_weekday_days
from src.solver import build_and_solve_demo
import pandas as pd


def _fixed_assignment_preassignments(
    calendar_slots: pd.DataFrame,
    fixed_assignments: dict[str, str],
) -> pd.DataFrame:
    """Expand catalog-level fixed assignments into per-day preassignments.

    Per cada (slot_id → professional_id), genera una fila per cada fila de
    calendar_slots amb aquell slot_id, copiant-ne franja/presentiality/
    work_mode perquè el matching downstream sigui inambigu (sense NaN/None)."""
    cols = ["professional_id", "day", "slot_id", "franja", "presentiality", "work_mode", "fixed"]
    if not fixed_assignments or calendar_slots is None or calendar_slots.empty:
        return pd.DataFrame(columns=cols)
    slot_col = calendar_slots["slot_id"].fillna("").astype(str).str.strip().str.upper()
    rows = []
    for slot_id, professional_id in fixed_assignments.items():
        mask = slot_col == slot_id
        if not mask.any():
            continue
        for _, cal_row in calendar_slots.loc[mask].iterrows():
            rows.append({
                "professional_id": professional_id,
                "day": str(cal_row.get("day", "")),
                "slot_id": slot_id,
                "franja": str(cal_row.get("franja", "") or "").upper(),
                "presentiality": str(cal_row.get("presentiality", "") or "").upper(),
                "work_mode": str(cal_row.get("work_mode", "") or "").upper(),
                "fixed": 1,
            })
    return pd.DataFrame(rows, columns=cols)


def _split_review_fixed(
    fixed_assignments: dict[str, str], review_slots
) -> tuple[dict[str, str], dict[str, str]]:
    """Separa assignacions fixes de catàleg en (revisió, no-revisió).

    Les revisions amb assignee fix s'apliquen post-procés (fora del solver):
    així el solver no les veu i no esbiaixen els equilibris (presential_spread,
    quotes setmanals…). El solver les ignora completament; s'afegeixen
    directament al schedule final amb el facultatiu del catàleg si està
    disponible aquell dia."""
    review_upper = {str(s).strip().upper() for s in (review_slots or ())}
    review_fixed = {
        sk.upper(): pid.upper()
        for sk, pid in (fixed_assignments or {}).items()
        if str(sk).strip().upper() in review_upper
    }
    machine_fixed = {
        sk: pid for sk, pid in (fixed_assignments or {}).items()
        if str(sk).strip().upper() not in review_fixed
    }
    return review_fixed, machine_fixed


def _slot_linked_ids_for_solver(common: dict) -> set:
    """Conjunt d'slot_ids vinculats (tant primari com secundari)
    derivat dels TEMPLATES. Si no hi ha res als templates, cau al
    catàleg (legacy `slot_secondary_ids`)."""
    from src.services.slot_catalog import slot_linked_ids_from_templates
    templates_path = Path("data/weekday/weekly_slot_templates.csv")
    if templates_path.exists() and templates_path.stat().st_size > 0:
        try:
            templates_df = pd.read_csv(templates_path)
            ids = slot_linked_ids_from_templates(templates_df)
            if ids:
                return ids
        except Exception:
            pass
    return set(common.get("slot_secondary_ids", set()) or set())


def _slot_links_for_solver(weekday: dict, common: dict) -> list:
    """Retorna la llista de pairs vinculats. Prefereix els derivats del
    template setmanal (camp `linked_to` per (weekday_name, franja,
    slot_id)). Si no hi ha res al template, cau al camp del catàleg
    (legacy, slot_link_pairs del catàleg)."""
    from src.services.slot_catalog import slot_link_pairs_from_templates
    templates_path = Path("data/weekday/weekly_slot_templates.csv")
    if templates_path.exists() and templates_path.stat().st_size > 0:
        try:
            templates_df = pd.read_csv(templates_path)
            pairs = slot_link_pairs_from_templates(templates_df)
            if pairs:
                return pairs
        except Exception:
            pass
    return list(common.get("slot_links", []) or [])


def _fulltime_unavailable_days(unavailability: pd.DataFrame) -> set[tuple[str, str]]:
    """Set de (professional_id, day) que tenen una indisponibilitat 'dia sencer'
    (sense franja/slot/presentiality específica). Es fa servir per decidir si
    el facultatiu fix d'una revisió post-procés està disponible aquell dia."""
    if unavailability is None or unavailability.empty:
        return set()
    df = unavailability
    def _is_blank(col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series(True, index=df.index)
        s = df[col].fillna("").astype(str).str.strip().str.upper()
        return s.isin({"", "NAN", "NONE"})
    mask = _is_blank("franja") & _is_blank("slot_id") & _is_blank("presentiality") & _is_blank("work_mode")
    out: set[tuple[str, str]] = set()
    for _, row in df.loc[mask].iterrows():
        pid = str(row.get("professional_id", "") or "").strip().upper()
        day = str(row.get("day", "") or "").strip()
        if pid and day:
            out.add((pid, day))
    return out


def solve_weekday(common: dict, weekday: dict, guard_preassignments=None,
                  stability_assignments=None,
                  prior_presential_counts: dict[str, int] | None = None,
                  warm_start_assignments=None) -> dict:
    # Preassignacions de l'USUARI (introduïdes manualment a la pestanya
    # de restriccions). El solver ha de preservar la seva presencialitat
    # tal com l'usuari l'ha definit — el flip presencial NO pot tocar-les.
    user_preassignments = weekday["preassignments"].copy()
    preassignments = user_preassignments.copy()

    if guard_preassignments is not None and not guard_preassignments.empty:
        preassignments = pd.concat(
            [preassignments, guard_preassignments],
            ignore_index=True
        )

    review_set = common.get("review_slots") or set()
    review_fixed, machine_fixed = _split_review_fixed(
        common.get("slot_fixed_assignments") or {}, review_set,
    )

    # Calendari per al solver: SENSE les files de slots de revisió amb
    # assignee fix (s'afegeixen post-procés al schedule final).
    calendar_for_solver = weekday["calendar_slots"]
    if review_fixed and calendar_for_solver is not None and not calendar_for_solver.empty:
        cal_slot_col = calendar_for_solver["slot_id"].fillna("").astype(str).str.strip().str.upper()
        keep_mask = ~cal_slot_col.isin(review_fixed.keys())
        calendar_for_solver = calendar_for_solver.loc[keep_mask].copy()

    fixed = _fixed_assignment_preassignments(calendar_for_solver, machine_fixed)
    if not fixed.empty:
        preassignments = pd.concat([preassignments, fixed], ignore_index=True)

    unavailability = weekday["unavailability"].copy()
    extra_unav = non_working_weekdays_unavailability(
        common["professionals"], weekday["calendar_slots"],
    )
    if not extra_unav.empty:
        unavailability = pd.concat([unavailability, extra_unav], ignore_index=True)

    # Bloqueigs derivats de `allowed_areas` per facultatiu: si AP té
    # allowed_areas="HUB;DELTA", afegim allowed=0 a la taula
    # d'eligibility per a tots els slots fora d'aquestes àrees.
    # `allowed_areas` PREVAL sobre l'eligibility per defecte: si la
    # parella (prof, slot) està bloquejada per àrea, queda allowed=0
    # encara que l'eligibility de l'usuari digui el contrari.
    from src.services.allowed_areas import allowed_areas_eligibility_blocks
    extra_elig = allowed_areas_eligibility_blocks(common["professionals"])
    base_elig = common["eligibility"].copy() if common.get("eligibility") is not None else pd.DataFrame(
        columns=["professional_id", "slot_id", "allowed"]
    )
    if not extra_elig.empty:
        # extra_elig PRIMER → keep="first" manté allowed=0 sobre
        # els valors de base_elig per a les mateixes (prof, slot).
        merged = pd.concat([extra_elig, base_elig], ignore_index=True)
        merged = merged.drop_duplicates(
            subset=["professional_id", "slot_id"], keep="first"
        ).reset_index(drop=True)
        effective_eligibility = merged
    else:
        effective_eligibility = base_elig

    # `allowed_areas` és un límit FÍSIC (el facultatiu no es desplaça a
    # aquell lloc): a diferència de l'eligibility soft, és HARD. Passem
    # el conjunt (prof, slot_id) a bloquejar al solver.
    allowed_areas_hard_blocks = {
        (str(r.professional_id).strip().upper(), str(r.slot_id).strip().upper())
        for r in extra_elig.itertuples(index=False)
    } if not extra_elig.empty else set()

    # Reduccions: derivades de non_working_weekdays (MON-FRI).
    # Cada dia setmanal no laborable = 20% reducció sobre la setmana laboral.
    reductions = reductions_from_non_working_weekdays(
        common["professionals"], WEEKDAY_CODES_SET, days_in_week=5,
    )

    review_for_solver = {
        s for s in review_set if str(s).strip().upper() not in review_fixed
    }

    # Mapa de dies NP-only per facultatiu (per al penal tou
    # `_add_no_pres_weekday_soft`): expandeix els codis MON..SUN als
    # dies concrets del calendari.
    no_pres_weekday_map = no_pres_weekday_days(
        common["professionals"], weekday["calendar_slots"],
    )
    pres_weekday_map = pres_weekday_days(
        common["professionals"], weekday["calendar_slots"],
    )

    data = {
        "professionals": common["professionals"],
        "eligibility": effective_eligibility,
        "reductions": reductions,
        "calendar_slots": calendar_for_solver,
        "unavailability": unavailability,
        "preassignments": preassignments,
        "day_info": weekday["day_info"],
        "absences": common.get("absences", pd.DataFrame()),
        "comite": common.get("comite", pd.DataFrame()),
        "planning_rules": common.get("planning_rules"),
        # Slot links: ara venen del TEMPLATE (per (dia, franja) implícit).
        # Els del catàleg (legacy) NO s'usen. Si no hi ha templates,
        # caiem al common["slot_links"] del catàleg per compat.
        "slot_links": _slot_links_for_solver(weekday, common),
        # Slots a excloure de peonades (vinculats: tant primari com
        # secundari) — unió del catàleg (legacy) i del template (font
        # actual). El filtre s'aplica a `_add_peonada_monthly_cap`.
        "slot_secondary_ids": _slot_linked_ids_for_solver(common),
        # Bloqueigs HARD per allowed_areas (prof, slot_id).
        "allowed_areas_hard_blocks": allowed_areas_hard_blocks,
        # Warm-start opcional: calendari anterior per sembrar el solver
        # (hints, sense penalització) i millorar-lo en lloc de recomençar.
        "warm_start_assignments": warm_start_assignments,
        "review_slots": review_for_solver,
        "presential_tolerance": common.get("presential_tolerance", 0),
        "peonada_cap": common.get("peonada_cap", 3),
        "prior_presential_counts": prior_presential_counts or {},
        "prior_no_presential_counts": common.get("prior_no_presential_counts") or {},
        # Subset 'manual' (només les introduïdes per l'usuari) per al filtre
        # del flip al solver. Les autogenerades (guards, fix-catàleg) sí que
        # poden flipar.
        "user_preassignments": user_preassignments,
        "slot_fixed_assignments": machine_fixed,
        "no_pres_weekday_map": no_pres_weekday_map,
        "pres_weekday_map": pres_weekday_map,
    }

    result_text, schedule_rows, metrics_rows = build_and_solve_demo(
        data,
        stability_assignments=stability_assignments,
    )

    # Post-procés: afegir al schedule les revisions amb assignee fix. Si el
    # facultatiu té indisponibilitat de dia sencer (vacances/baixa/festiu
    # personal), es deixa sense assignar perquè l'usuari ho vegi.
    if review_fixed and weekday["calendar_slots"] is not None and not weekday["calendar_slots"].empty:
        blocked = _fulltime_unavailable_days(unavailability)
        cal_full = weekday["calendar_slots"]
        cal_slot_col = cal_full["slot_id"].fillna("").astype(str).str.strip().str.upper()
        for slot_id, pid in review_fixed.items():
            mask = cal_slot_col == slot_id
            for _, cal_row in cal_full.loc[mask].iterrows():
                day = str(cal_row.get("day", ""))
                prof = "" if (pid, day) in blocked else pid
                schedule_rows.append([
                    day,
                    str(cal_row.get("franja", "") or ""),
                    slot_id,
                    prof,
                    str(cal_row.get("presentiality", "") or ""),
                    str(cal_row.get("work_mode", "") or ""),
                    0,  # is_flipped: revisions fixes mai són flipades
                ])

    return {
        "ok": bool(schedule_rows),
        "text": result_text,
        "schedule": schedule_rows,
        "metrics": metrics_rows,
    }
