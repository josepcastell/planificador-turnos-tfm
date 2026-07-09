from pathlib import Path

from src.services.no_pres_weekdays import no_pres_weekday_days
from src.services.non_working_weekdays import (
    WEEKDAY_CODES_SET,
    non_working_weekdays_unavailability,
    reductions_from_non_working_weekdays,
)
from src.services.pres_weekdays import pres_weekday_days
from src.solver import build_and_solve_demo
from src.domain.constants import WEEKDAY_CODES
import pandas as pd

_WEEKDAY_CODE_BY_IDX = {idx: code for idx, code in enumerate(WEEKDAY_CODES)}


def _blocked_for_fixed(unavailability_df, absences_df):
    """Retorna (full_blocked, franja_blocked): conjunts de (prof, dia) i
    (prof, dia, franja) on el facultatiu NO està disponible, perquè les
    màquines fixes s'hi SALTIN (l'absència/indisponibilitat preval).

    - Absències (start_day..end_day): bloquegen el dia sencer.
    - Indisponibilitats: dia sencer si no porten franja; per franja si en porten."""
    full = set()
    franja = set()
    if unavailability_df is not None and not getattr(unavailability_df, "empty", True):
        _cols = set(getattr(unavailability_df, "columns", []))
        for r in unavailability_df.itertuples(index=False):
            pid = str(getattr(r, "professional_id", "") or "").strip().upper()
            day = str(getattr(r, "day", "") or "").strip()
            if not pid or not day:
                continue
            fr = str(getattr(r, "franja", "") or "").strip().upper() if "franja" in _cols else ""
            if fr in ("NAN", "NONE", "*"):  # NaN/buit → bloqueig de dia sencer
                fr = ""
            if fr:
                franja.add((pid, day, fr))
            else:
                full.add((pid, day))
    if absences_df is not None and not getattr(absences_df, "empty", True):
        for r in absences_df.itertuples(index=False):
            pid = str(getattr(r, "professional_id", "") or "").strip().upper()
            sd = str(getattr(r, "start_day", "") or "").strip()
            ed = str(getattr(r, "end_day", "") or "").strip() or sd
            if not pid or not sd:
                continue
            try:
                for d in pd.date_range(sd, ed):
                    full.add((pid, d.strftime("%Y-%m-%d")))
            except Exception:
                full.add((pid, sd))
    return full, franja


def _fixed_assignment_preassignments(
    calendar_slots: pd.DataFrame,
    fixed_assignments: dict[str, str],
    full_blocked=None,
    franja_blocked=None,
) -> pd.DataFrame:
    """Expand catalog-level fixed assignments into per-day preassignments.

    Per cada (slot_id → professional_id), genera una fila per cada fila de
    calendar_slots amb aquell slot_id. Es SALTA els (prof, dia[, franja])
    bloquejats: l'absència/indisponibilitat preval sobre la màquina fixa."""
    cols = ["professional_id", "day", "slot_id", "franja", "presentiality", "work_mode", "fixed"]
    if not fixed_assignments or calendar_slots is None or calendar_slots.empty:
        return pd.DataFrame(columns=cols)
    full_blocked = full_blocked or set()
    franja_blocked = franja_blocked or set()
    slot_col = calendar_slots["slot_id"].fillna("").astype(str).str.strip().str.upper()
    rows = []
    for slot_id, professional_id in fixed_assignments.items():
        pid = str(professional_id or "").strip().upper()
        mask = slot_col == slot_id
        if not pid or not mask.any():
            continue
        for _, cal_row in calendar_slots.loc[mask].iterrows():
            day = str(cal_row.get("day", ""))
            fr = str(cal_row.get("franja", "") or "").upper()
            if (pid, day) in full_blocked or (pid, day, fr) in franja_blocked:
                continue  # absència/indisponibilitat → no es força la fixació
            rows.append({
                "professional_id": professional_id,
                "day": day,
                "slot_id": slot_id,
                "franja": fr,
                "presentiality": str(cal_row.get("presentiality", "") or "").upper(),
                "work_mode": str(cal_row.get("work_mode", "") or "").upper(),
                "fixed": 1,
            })
    return pd.DataFrame(rows, columns=cols)


def _granular_fixed_preassignments(
    calendar_slots: pd.DataFrame,
    fixed_machines_df: pd.DataFrame,
    full_blocked=None,
    franja_blocked=None,
) -> pd.DataFrame:
    """Expandeix màquines fixes GRANULARS (professional, slot, weekday_name,
    franja) a preassignacions per dia. `weekday_name`/`franja` buit o "*" =
    qualsevol. Es SALTA els (prof, dia[, franja]) bloquejats: l'absència preval."""
    cols = ["professional_id", "day", "slot_id", "franja", "presentiality", "work_mode", "fixed"]
    if (fixed_machines_df is None or fixed_machines_df.empty
            or calendar_slots is None or calendar_slots.empty):
        return pd.DataFrame(columns=cols)
    full_blocked = full_blocked or set()
    franja_blocked = franja_blocked or set()
    cal = calendar_slots.copy()
    cal["_slot"] = cal["slot_id"].fillna("").astype(str).str.strip().str.upper()
    cal["_franja"] = cal["franja"].fillna("").astype(str).str.strip().str.upper()
    cal["_wd"] = (
        pd.to_datetime(cal["day"], errors="coerce").dt.weekday
        .map(_WEEKDAY_CODE_BY_IDX).fillna("")
    )
    rows = []
    for r in fixed_machines_df.itertuples(index=False):
        prof = str(getattr(r, "professional_id", "") or "").strip().upper()
        slot = str(getattr(r, "slot_id", "") or "").strip().upper()
        wd = str(getattr(r, "weekday_name", "") or "").strip().upper()
        fr = str(getattr(r, "franja", "") or "").strip().upper()
        if not prof or not slot:
            continue
        mask = cal["_slot"] == slot
        if wd and wd != "*":
            mask = mask & (cal["_wd"] == wd)
        if fr and fr != "*":
            mask = mask & (cal["_franja"] == fr)
        for _, cr in cal.loc[mask].iterrows():
            day = str(cr.get("day", ""))
            cfr = str(cr.get("franja", "") or "").upper()
            if (prof, day) in full_blocked or (prof, day, cfr) in franja_blocked:
                continue  # absència/indisponibilitat → no es força la fixació
            rows.append({
                "professional_id": prof,
                "day": day,
                "slot_id": slot,
                "franja": cfr,
                "presentiality": str(cr.get("presentiality", "") or "").upper(),
                "work_mode": str(cr.get("work_mode", "") or "").upper(),
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
    """Slot_ids que formen part d'alguna vinculació (primari o secundari).
    UNIÓ de les dues fonts: els derivats dels TEMPLATES (secundària NP del
    doblat, per (weekday, franja, slot)) i els del CATÀLEG (blocs globals de
    màquines vinculades, camp `linked_to`)."""
    from src.core.utils import normalize_slot as _norm_slot
    from src.services.slot_catalog import slot_linked_ids_from_templates
    ids: set = set(common.get("slot_secondary_ids", set()) or set())
    templates_path = Path("data/weekday/weekly_slot_templates.csv")
    if templates_path.exists() and templates_path.stat().st_size > 0:
        try:
            templates_df = pd.read_csv(templates_path)
            ids |= slot_linked_ids_from_templates(templates_df)
        except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
            pass
    # normalize_slot: alinea amb les claus del solver (espais/guions → '_').
    return {_norm_slot(s) for s in ids}


def _links_by_wf_for_solver(weekday: dict, common: dict) -> dict:
    """Vinculacions PER (dia-setmana, franja) per al solver: dels TEMPLATES
    (`linked_to` per (weekday_name, franja, slot)) + les del CATÀLEG (legacy,
    globals → clau ('', '')). Permet que un grup estigui vinculat un dia/franja
    i no un altre. L'acoblament transitiu fa que la mateixa persona cobreixi
    tot el grup (fins a 5 màquines)."""
    from src.core.utils import normalize_slot as _norm_slot
    from src.services.slot_catalog import slot_link_pairs_by_weekday_franja
    out: dict = {}
    templates_path = Path("data/weekday/weekly_slot_templates.csv")
    if templates_path.exists() and templates_path.stat().st_size > 0:
        try:
            templates_df = pd.read_csv(templates_path)
            out = {
                k: [(_norm_slot(a), _norm_slot(b)) for a, b in v]
                for k, v in slot_link_pairs_by_weekday_franja(templates_df).items()
            }
        except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
            pass
    catalog_pairs = [
        (_norm_slot(p[0]), _norm_slot(p[1]))
        for p in (common.get("slot_links") or [])
    ]
    if catalog_pairs:
        out.setdefault(("", ""), []).extend(catalog_pairs)
    return out


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

    # Indisponibilitats (incloses non_working_weekdays). Es calculen ABANS de
    # les màquines fixes perquè aquestes s'hi puguin saltar: l'absència preval.
    unavailability = weekday["unavailability"].copy()
    extra_unav = non_working_weekdays_unavailability(
        common["professionals"], weekday["calendar_slots"],
    )
    if not extra_unav.empty:
        unavailability = pd.concat([unavailability, extra_unav], ignore_index=True)

    # Dies/franges bloquejats (absències + indisponibilitats): les màquines
    # fixes NO es forcen aquells dies/franges — l'absència/indisponibilitat preval.
    _full_blocked, _franja_blocked = _blocked_for_fixed(
        unavailability, common.get("absences"),
    )

    fixed = _fixed_assignment_preassignments(
        calendar_for_solver, machine_fixed, _full_blocked, _franja_blocked,
    )
    if not fixed.empty:
        preassignments = pd.concat([preassignments, fixed], ignore_index=True)

    # Màquines fixes GRANULARS (per dia de la setmana + franja), respectant
    # també absències/indisponibilitats.
    granular_fixed = _granular_fixed_preassignments(
        calendar_for_solver, weekday.get("fixed_machines"),
        _full_blocked, _franja_blocked,
    )
    if not granular_fixed.empty:
        preassignments = pd.concat([preassignments, granular_fixed], ignore_index=True)

    # Roda d'assignació (restricció TOVA): torns rotatoris per activitat.
    # NO es fixa res: el solver segueix el torn amb una penalització alta
    # si el trenca (mai fa el model infactible). Les preassignacions
    # existents (usuari / màquines fixes) prevalen: si ja hi ha una fila
    # per (dia, slot), la roda no hi opina.
    from src.services.wheel_assignments import expand_wheel_preassignments
    # A més d'absències, el torn SALTA qui ja està ocupat per una màquina
    # FIXA aquell dia/franja (si no, la preferència naixeria impossible i
    # el torn es perdria aleatòriament en lloc de passar al següent).
    _wheel_blocked = set(_franja_blocked or set())
    if not preassignments.empty:
        for _pr in preassignments.itertuples(index=False):
            _pfr = str(getattr(_pr, "franja", "") or "").strip().upper()
            _pid = str(_pr.professional_id).strip().upper()
            _pday = str(_pr.day)
            if _pfr:
                _wheel_blocked.add((_pid, _pday, _pfr))
            else:
                _wheel_blocked.add((_pid, _pday, "MATI"))
                _wheel_blocked.add((_pid, _pday, "TARDA"))
    wheel_rows = expand_wheel_preassignments(
        calendar_for_solver, common["professionals"],
        _full_blocked, _wheel_blocked,
    )
    if not wheel_rows.empty and not preassignments.empty:
        _taken = {
            (str(r.day), str(r.slot_id).strip().upper())
            for r in preassignments.itertuples(index=False)
        }
        wheel_rows = wheel_rows[
            ~wheel_rows.apply(
                lambda r: (str(r["day"]), str(r["slot_id"]).strip().upper()) in _taken,
                axis=1,
            )
        ]

    # Bloqueigs derivats de `allowed_areas` per facultatiu: si XX té
    # allowed_areas="ZONA_A;ZONA_B", afegim allowed=0 a la taula
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
    # el conjunt (prof, slot_id) a bloquejar al solver. El slot passa per
    # `normalize_slot` (espais/guions → '_'): les claus del solver (sk[2])
    # estan normalitzades així i sense això un slot amb espai al nom mai
    # es bloquejaria.
    from src.core.utils import normalize_slot as _norm_slot
    allowed_areas_hard_blocks = {
        (str(r.professional_id).strip().upper(), _norm_slot(r.slot_id))
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
        # Vinculacions PER (dia-setmana, franja) del TEMPLATE + catàleg legacy
        # (global, clau ('', '')). Un grup pot estar vinculat un dia i no un
        # altre.
        "links_by_wf": _links_by_wf_for_solver(weekday, common),
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
        # Acumulat d'ORDINÀRIES dels mesos anteriors de la tanda (per a
        # l'equitat acumulada del tram 4 a core.py).
        "prior_total_machine_counts": common.get("prior_total_machine_counts") or {},
        # Subset 'manual' (només les introduïdes per l'usuari) per al filtre
        # del flip al solver. Les autogenerades (guards, fix-catàleg) sí que
        # poden flipar.
        "user_preassignments": user_preassignments,
        "slot_fixed_assignments": machine_fixed,
        "no_pres_weekday_map": no_pres_weekday_map,
        "pres_weekday_map": pres_weekday_map,
        # Roda d'assignació: preferències TOVES (dia, slot, franja → prof).
        "wheel_preferences": wheel_rows,
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
