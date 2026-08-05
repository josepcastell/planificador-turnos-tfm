"""CP-SAT model orchestrator: glues preprocessing, constraints, objectives, extract."""

import datetime as _dt
import os

from ortools.sat.python import cp_model
import pandas as pd


def _solver_int_env(name: str, default: int) -> int:
    """Llegeix un enter d'una variable d'entorn; fallback al per defecte si
    no hi és o no és vàlida (>0)."""
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default

from src.core.utils import normalize_slot
from src.domain.constants import (
    GUARDS_RESERVED_SLOT_IDS,
    QUOTA_EXEMPT_PROFESSIONALS,
    SOLVER_WEIGHTS,
)
from src.solver.constraints import (
    _add_conditional_doubling_constraints,
    _add_coverage_constraints,
    _add_daily_compat_constraints,
    _add_fallback_eligibility_hard,
    _add_flip_target_cap,
    _add_presence_mode_constraints,
    _add_preassignment_constraints,
    _add_review_continuity,
    _add_structural_coupling,
    _add_unavailability_constraints,
    _build_decision_variables,
    _build_machine_term_specs,
)
from src.solver.extract import _extract_solution
from src.solver.normalize import _make_slot_key, _normalize_slots_df, _norm_set
from src.solver.objectives import (
    _add_comite_preferred_machine_terms,
    _add_eligibility_soft,
    _add_fallback_usage_penalty,
    _add_guard_morning_telework_terms,
    _add_facultatiu_targets,
    _add_no_pres_weekday_soft,
    _add_peonada_monthly_cap,
    _add_pres_weekday_soft,
    _add_presentiality_balance,
    _add_review_balance,
    _add_stability_terms,
    _add_tc_rm_balance,
    _add_ordinary_machine_balance,
    _add_weekly_soft_terms,
)
from src.solver.preprocessing import (
    _add_missing_slots_from_preassignments,
    _prepare_reductions_df,
    _stability_by_slot,
    _validate_preassignments,
    expand_comite_to_days,
)


def _compute_capacity_pct(reductions_df, professionals, unique_days):
    """Percentatge de jornada per (facultatiu, dia) i la mitjana per
    facultatiu, derivats de les reduccions de jornada. Sense reduccions,
    tothom queda al 100%."""
    capacity_pct_by: dict[tuple[str, str], int] = {}
    if not reductions_df.empty:
        day_timestamps = {d: pd.Timestamp(d) for d in unique_days}
        reductions_by_prof: dict[str, list] = {}
        for r in reductions_df.itertuples(index=False):
            reductions_by_prof.setdefault(r.professional_id, []).append(r)
        for p in professionals:
            prof_reds = reductions_by_prof.get(p, [])
            for d in unique_days:
                if not prof_reds:
                    capacity_pct_by[(p, d)] = 100
                    continue
                day_dt = day_timestamps[d]
                reduction = 0
                for r in prof_reds:
                    if r.start_day <= day_dt <= r.end_day:
                        rp = int(r.reduction_pct)
                        if rp > reduction:
                            reduction = rp
                capacity_pct_by[(p, d)] = max(0, 100 - reduction)
    else:
        for p in professionals:
            for d in unique_days:
                capacity_pct_by[(p, d)] = 100
    average_capacity_pct = {
        p: (sum(capacity_pct_by[(p, d)] for d in unique_days) // len(unique_days)
            if unique_days else 100)
        for p in professionals
    }
    return capacity_pct_by, average_capacity_pct


# Reasons d'indisponibilitat que NO redueixen la quota SETMANAL ni la
# capacitat d'equitat (es coordinen amb la jornada o, en el cas del dia de
# GUÀRDIA, al matí hi ha l'objectiu tou de teletreball que pot no complir-se,
# així que no es descompta). La POSTGUÀRDIA NO hi és: és un dia buit del tot
# (ni PRES ni NP) i per tant compta com a absència real.
_QUOTA_NEUTRAL_REASONS = {
    "non_working_weekday", "guardia_day_tarda",
}


def _classify_unavailable_days(unavailability_df, professionals):
    """Classifica les indisponibilitats per facultatiu:

    - `absent_days_by_prof`: dies NO disponibles (cap activitat) que rebaixen
      tant la QUOTA SETMANAL com la CAPACITAT EFECTIVA d'equitat. Inclou
      absències reals, reforços I POSTGUÀRDIES (la postguàrdia és un dia buit:
      ni PRES ni NP). EXCLOU els quota-neutral (`non_working_weekday`,
      coordinat amb la jornada; `guardia_day_tarda`, el dia de guàrdia, que al
      matí té l'objectiu tou de teletreball que pot no complir-se).
    - `guard_prof_days`: (prof, dia) amb guàrdia, per a l'objectiu tou de
      teletreball al matí."""
    absent: dict[str, set] = {p: set() for p in professionals}
    guard_prof_days: set[tuple[str, str]] = set()
    if unavailability_df is None or unavailability_df.empty:
        return absent, guard_prof_days
    has_reason = "reason" in unavailability_df.columns
    for row in unavailability_df.itertuples(index=False):
        pid = row.professional_id
        if pid not in absent:
            continue
        day = str(row.day)
        reason = str(getattr(row, "reason", "") or "") if has_reason else ""
        if reason == "guardia_day_tarda":
            guard_prof_days.add((pid, day))
        if reason in _QUOTA_NEUTRAL_REASONS:
            continue
        # Bloqueig PARCIAL (només una franja): l'altra franja del dia segueix
        # sent assignable i ha de seguir comptant a quota/capacitat. Només
        # els bloquejos de DIA SENCER (franja buida) són absències reals.
        franja_val = str(getattr(row, "franja", "") or "").strip().upper()
        if franja_val not in {"", "NAN", "NONE"}:
            continue
        absent[pid].add(day)  # absència / postguàrdia → dia sencer no disponible
    return absent, guard_prof_days


def _compute_effective_capacity_pct(professionals, unique_days, working_map,
                                    capacity_pct_by, absent_days_by_prof):
    """% de capacitat EFECTIVA per facultatiu per a l'equitat: mitjana de la
    jornada (`capacity_pct`) sobre TOTS els dies laborables del mes, comptant
    0 els dies no disponibles (absències + reforços + postguàrdies). El
    denominador és el nombre total de dies laborables, perquè un facultatiu
    absent/de postguàrdia surti amb capacitat proporcionalment menor i, per
    tant, un target d'equitat més baix."""
    n_working = sum(1 for d in unique_days if working_map.get(d, 1) == 1) or 1
    return {
        p: sum(
            capacity_pct_by[(p, d)]
            for d in unique_days
            if working_map.get(d, 1) == 1 and d not in absent_days_by_prof[p]
        ) // n_working
        for p in professionals
    }


def _solve_tiers(model, solver, tier_terms, x, total_budget,
                 tier_budget_frac, tier_slack, log):
    """Resol el model de forma LEXICOGRÀFICA, tram a tram: minimitza cada
    tram, registra els seus termes, bloqueja el seu valor (≤ millor +
    slack) i passa al següent amb warm-start de la solució anterior.
    Retorna l'status del darrer Solve (o None si no hi ha cap tram)."""
    status = None
    n_tiers = len(tier_terms)
    log("\n" + "=" * 60)
    log("SOLVER tier-by-tier breakdown")
    log("=" * 60)
    for i, (tier_name, terms) in enumerate(tier_terms):
        expr = sum(var * w for var, w in terms)
        model.Minimize(expr)
        solver.parameters.max_time_in_seconds = max(
            5.0, total_budget * tier_budget_frac[i]
        )
        status = solver.Solve(model)
        log(f"\n[Tram {i+1}: {tier_name}]  status={solver.StatusName(status)}  "
            f"obj={solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'N/A'}")
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            for _v, _w in terms:
                try:
                    _name = _v.Name() if hasattr(_v, "Name") else str(_v)
                    log(f"  · {_name} = {solver.Value(_v)}  (pes {_w:,})")
                except Exception:
                    pass
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        if i < n_tiers - 1:
            tier_value = sum(w * solver.Value(var) for var, w in terms)
            model.Add(expr <= tier_value + tier_slack)
            model.ClearHints()
            for _key, _var in x.items():
                model.AddHint(_var, solver.Value(_var))
    return status


def _log_per_professional_summary(log, solver, real_professionals,
                                  presential_counts, peonada_vars, x,
                                  slot_keys, review_slots):
    """Escriu al log el resum PRES / NORMAL / Peonades / Ordinàries / Total
    per facultatiu, al final del darrer tram resolt."""
    log("\n" + "=" * 60)
    log("RESUM per facultatiu (al final del darrer tram)")
    log("=" * 60)
    log(f"{'Facultatiu':<12}{'PRES':>6}{'NORMAL':>8}{'Peo':>6}"
        f"{'ORD':>6}{'Total':>7}")
    review_norm = _norm_set(review_slots)
    for p in real_professionals:
        pres = solver.Value(presential_counts[p]) if p in presential_counts else 0
        peo = sum(solver.Value(pn) for (pp, _sk), pn in peonada_vars.items() if pp == p)
        total = sum(solver.Value(x[p, sk]) for sk in slot_keys)
        # ORD = total assignacions − peonades − revisions − guàrdies
        rev = sum(
            solver.Value(x[p, sk]) for sk in slot_keys
            if str(sk[2]).strip().upper() in review_norm
        )
        guard = sum(
            solver.Value(x[p, sk]) for sk in slot_keys
            if str(sk[2]).strip().upper() in GUARDS_RESERVED_SLOT_IDS
        )
        ordin = total - peo - rev - guard
        normal = ordin - pres  # NO_PRES NORMAL (excloent peonades)
        log(f"{p:<12}{pres:>6}{normal:>8}{peo:>6}{ordin:>6}{total:>7}")


def _availability_problem_report(
    keys_by_day, professionals, unavailability_df,
) -> str:
    """Quan el model és INFEASIBLE, la causa més habitual és un (dia,
    franja) on la cobertura DURA demana més facultatius que els que
    queden disponibles un cop aplicades les absències, guàrdies i
    indisponibilitats (també dures). Compara demanda (instàncies de
    màquina) amb oferta OPTIMISTA (facultatius sense bloqueig del dia o
    de la franja sencera): si demanda > oferta el problema és segur, i
    s'assenyala amb dia, franja i els noms dels no disponibles."""
    # Bloquejos per (professional, dia): {"ALL"} = dia sencer; o franges.
    blocked: dict = {}
    if unavailability_df is not None and not unavailability_df.empty:
        has_franja = "franja" in unavailability_df.columns
        has_pres = "presentiality" in unavailability_df.columns
        for row in unavailability_df.itertuples(index=False):
            pres = str(getattr(row, "presentiality", "") or "").strip().upper() if has_pres else ""
            if pres and pres not in ("", "NAN", "NONE"):
                continue  # bloqueig parcial per presencialitat: oferta optimista
            pid = str(getattr(row, "professional_id", "") or "").strip().upper()
            day = str(getattr(row, "day", "") or "").strip()
            fr = str(getattr(row, "franja", "") or "").strip().upper() if has_franja else ""
            if fr in ("NAN", "NONE"):
                fr = ""
            blocked.setdefault((pid, day), set()).add(fr or "ALL")

    reals = [
        str(p).strip().upper() for p in professionals
        if str(p).strip().upper() not in ("NONE", "")
    ]
    lines = []
    for day in sorted(keys_by_day):
        by_franja: dict = {}
        for sk in keys_by_day[day]:
            by_franja.setdefault(str(sk[1]).strip().upper(), []).append(sk)
        for fr, keys in sorted(by_franja.items()):
            fora = [
                p for p in reals
                if blocked.get((p, day), set()) & {"ALL", fr}
            ]
            supply = len(reals) - len(fora)
            if len(keys) > supply:
                # «fins a N»: les vinculades/doblades poden compartir
                # persona, així que N és una cota superior de la demanda.
                lines.append(
                    f"  · {day} ({fr.title()}): calen fins a {len(keys)} "
                    f"facultatius i només {supply} de disponibles"
                    + (f" (no disponibles: {', '.join(sorted(fora))})" if fora else "")
                )
            if len(lines) >= 8:
                break
        if len(lines) >= 8:
            break
    if not lines:
        return ""
    return (
        "PROBLEMA LOCALITZAT — dies amb més màquines que facultatius "
        "disponibles (absències/guàrdies/indisponibilitats):\n"
        + "\n".join(lines)
        + "\nSolucions: treure màquines d'aquests dies (franges o "
        "puntuals), revisar les absències/guàrdies del dia, o afegir-hi "
        "facultatius."
    )


def _infeasibility_message(solver, assume_names, keys_by_day=None,
                           professionals=None, unavailability_df=None) -> str:
    """Missatge explicatiu quan el model és infactible: assenyala les
    restriccions dures fràgils (H5/H7) implicades i, si la causa és un
    dèficit de disponibilitat (absències/guàrdies/festius vs cobertura),
    diu EXACTAMENT quins dies i franges fallen i qui no hi és."""
    parts = []
    core_idx = solver.SufficientAssumptionsForInfeasibility()
    culpables = [assume_names.get(i) for i in core_idx if i in assume_names]
    if culpables:
        parts.append(
            "Model infactible. Restricció(ns) dura(es) implicada(es): "
            + "; ".join(culpables)
            + ". Reviseu si hi ha parells vinculats o revisions que "
            "xoquen amb indisponibilitats."
        )
    else:
        parts.append(
            "Model infactible per una restricció DURA: cobertura de les "
            "franges, absències/guàrdies/indisponibilitats, mode de "
            "presència d'algun facultatiu, o el comodí amb allowed=0."
        )
    if keys_by_day is not None and professionals is not None:
        report = _availability_problem_report(
            keys_by_day, professionals, unavailability_df,
        )
        if report:
            parts.append(report)
    return "\n".join(parts)


def build_and_solve_demo(data: dict, stability_assignments=None):
    # ── Prepare inputs ────────────────────────────────────────────────────────
    professionals_df = data["professionals"].copy()
    slots_df = _normalize_slots_df(data["calendar_slots"].copy())
    unavailability_df = data["unavailability"].copy()
    preassignments_df = data["preassignments"].copy()
    eligibility_df = data["eligibility"].copy()
    day_info_df = data["day_info"].copy()
    reductions_df = data.get("reductions", pd.DataFrame()).copy()

    eligibility_df["slot_id"] = eligibility_df["slot_id"].apply(normalize_slot)
    if not preassignments_df.empty and "slot_id" in preassignments_df.columns:
        preassignments_df["slot_id"] = preassignments_df["slot_id"].apply(normalize_slot)
    slots_df = _add_missing_slots_from_preassignments(slots_df, preassignments_df)

    professionals = professionals_df["professional_id"].astype(str).tolist()
    real_professionals = [p for p in professionals if p != "NONE"]
    fallback_professionals = set()
    presence_mode_by_prof = {}
    if "fallback" in professionals_df.columns:
        for row in professionals_df.itertuples(index=False):
            try:
                if int(getattr(row, "fallback", 0) or 0) == 1:
                    fallback_professionals.add(str(row.professional_id))
            except (TypeError, ValueError):
                pass
    if "presence_mode" in professionals_df.columns:
        for row in professionals_df.itertuples(index=False):
            mode = str(getattr(row, "presence_mode", "") or "").strip().upper()
            if mode in {"PRESENCIAL", "NO_PRESENCIAL"}:
                presence_mode_by_prof[str(row.professional_id)] = mode
    # NOTA: la restricció «el comodí (fallback/TLD) només fa
    # NO_PRESENCIAL» NO s'imposa automàticament. Si l'usuari la vol,
    # cal posar explicitament `presence_mode=NO_PRESENCIAL` a la fila
    # del comodí a la pestanya Facultatius. Així el solver l'aplica via
    # _add_presence_mode_constraints (linia mes avall). Sense aquesta
    # marca explícita, el TLD pot cobrir slots PRES si cal — el penal
    # de TLD_USAGE i la prioritat tier-1 ja fan que els regulars
    # l'agafin abans excepte com a últim recurs.
    reductions_df = _prepare_reductions_df(reductions_df, professionals)
    unique_days = sorted(slots_df["day"].astype(str).unique())

    capacity_pct_by, average_capacity_pct = _compute_capacity_pct(
        reductions_df, professionals, unique_days
    )

    slot_rows = list(slots_df.itertuples(index=False))
    slot_keys = [_make_slot_key(row) for row in slot_rows]
    keys_by_day: dict[str, list] = {}
    for sk in slot_keys:
        keys_by_day.setdefault(sk[0], []).append(sk)
    _validate_preassignments(preassignments_df, professionals, slot_keys,
                             unavailability_df=unavailability_df)
    stable_assignment_by_slot = _stability_by_slot(stability_assignments, professionals, slot_keys)

    working_map = {str(row.day): int(row.is_working_day) for row in day_info_df.itertuples(index=False)}

    # `absent_days_by_prof` (vegeu `_classify_unavailable_days`) recull els
    # dies NO disponibles que rebaixen la quota setmanal I la capacitat
    # efectiva d'equitat: absències reals, reforços i POSTGUÀRDIES (dia buit
    # del tot). El bloqueig dur dels slots es fa a part via
    # _add_unavailability_constraints. Queden QUOTA-NEUTRAL (hard-blocked però
    # SENSE rebaixar quota):
    #   - "non_working_weekday": off-day recurrent (es coordina amb la
    #     reducció de jornada en lloc d'acumular-s'hi).
    #   - "guardia_day_tarda": el dia de guàrdia (bloqueja TARDA i NIT)
    #     compta com a dia laborable; al MATÍ el facultatiu hi fa teletreball
    #     (NP) preferentment (objectiu tou que pot no complir-se).
    # A més, recollim els (prof, dia) de guàrdia per a l'objectiu tou de
    # teletreball al matí.
    absent_days_by_prof, guard_prof_days = _classify_unavailable_days(
        unavailability_df, professionals
    )

    active_professionals = (
        [p for p in real_professionals
         if len(absent_days_by_prof[p]) < len(unique_days) and average_capacity_pct.get(p, 100) > 0]
        or [p for p in real_professionals if average_capacity_pct.get(p, 100) > 0]
        or real_professionals[:]
    )

    # Capacitat EFECTIVA per a l'equitat: proporcional als dies REALMENT
    # disponibles = jornada × dies laborables PRESENTS, descomptant absències,
    # reforços I POSTGUÀRDIES. Així qui fa guàrdies (→ més postguàrdies) rep un
    # target de màquines/presencials proporcionalment menor. El dia de guàrdia
    # en si NO es descompta (objectiu tou de teletreball al matí).
    # `average_capacity_pct` (només jornada) no ho captava.
    effective_capacity_pct = _compute_effective_capacity_pct(
        professionals, unique_days, working_map, capacity_pct_by,
        absent_days_by_prof,
    )

    # Slots de revisió: ÚNICAMENT del catàleg (data["review_slots"], marcats
    # com a `review=1` a l'editor d'activitats). NO s'identifiquen pel nom
    # ni per cap prefix; el catàleg és l'única font de veritat. Si el catàleg
    # no té cap revisió marcada, `review_slots` queda buit i el solver no
    # tracta cap slot com a revisió.
    # IMPORTANT: comparem amb `normalize_slot` (espais/guions → '_'). El
    # catàleg pot tenir slot_ids amb espais (p.ex. "REVISIO RM") però el
    # solver normalitza sk[2] a "REVISIO_RM" via _normalize_slots_df. Sense
    # aquesta normalització al lookup, la restricció dura d'equitat de
    # revisions no l'aplicava i el repartiment quedava desbalancejat.
    from src.core.utils import normalize_slot as _norm_slot_for_cfg
    _review_cfg = {_norm_slot_for_cfg(s) for s in (data.get("review_slots") or set())}
    review_slots = {sk[2] for sk in slot_keys if _norm_slot_for_cfg(sk[2]) in _review_cfg}

    week_map = {}
    for day in unique_days:
        y, w, _ = _dt.date.fromisoformat(day).isocalendar()
        week_map[day] = (y, w)
    unique_weeks = sorted(set(week_map.values()))
    # Els facultatius "fallback" (TLD/telediagnòstic) absorbeixen l'excedent
    # sense quota ni penalització: no entren al càlcul de targets/overage.
    quota_hard_professionals = [
        p for p in professionals
        if p not in QUOTA_EXEMPT_PROFESSIONALS and p not in fallback_professionals
    ]

    # ── Build model ───────────────────────────────────────────────────────────
    model = cp_model.CpModel()
    x = _build_decision_variables(model, professionals, slot_keys)

    # "NONE" és un facultatiu virtual (placeholder), mai assignable a cap slot.
    if "NONE" in professionals:
        for sk in slot_keys:
            model.Add(x["NONE", sk] == 0)
    for p in real_professionals:
        if average_capacity_pct.get(p, 100) <= 0:
            for sk in slot_keys:
                model.Add(x[p, sk] == 0)

    # Vinculacions PER (dia-setmana, franja) — l'acoblament dur i el terme
    # setmanal les apliquen només on toca (un dia sí, un altre no).
    links_by_wf = data.get("links_by_wf") or {}
    # Unió global de parelles (per a les equitats MENSUALS 477/608/627, on el
    # col·lapse de vinculats es manté global — imprecisió menor acceptada).
    slot_links = sorted({pair for pairs in links_by_wf.values() for pair in pairs})
    # secondary_slot_ids NOMÉS s'usa per a l'exclusió de peonades: al
    # recompte setmanal els slots vinculats es gestionen PER (dia, franja)
    # dins _build_machine_term_specs (un filtre global els faria invisibles
    # els dies que el vincle NO aplica → sobrecàrrega no comptada).
    secondary_slot_ids = set(data.get("slot_secondary_ids") or set())
    machine_specs = _build_machine_term_specs(
        keys_by_day, review_slots, links_by_wf=links_by_wf,
    )

    # Flip presencial: el solver pot convertir un slot NO_PRESENCIAL ordinari
    # (NORMAL) en PRESENCIAL al schedule final per acostar-se al target
    # presencial del facultatiu. No el poden flipar els de presence_mode=
    # NO_PRESENCIAL (p. ex. el comodí TLD). Tampoc els slots **fixats
    # manualment per l'usuari** a la pestanya de restriccions (preassignments
    # introduïdes per l'usuari amb fixed=1) — aquests són decisions explícites
    # i s'han de preservar tal com s'han introduït. Les preassignacions
    # AUTOGENERADES (guàrdies, slots fix del catàleg) SÍ que poden flipar:
    # el solver pot decidir-ho per ajustar el target.
    from src.solver.preprocessing import _matching_preassignment_keys
    user_preassignments_df = data.get("user_preassignments")
    if user_preassignments_df is None:
        user_preassignments_df = preassignments_df  # compatibilitat enrere
    fixed_slot_keys: set = set()
    if (user_preassignments_df is not None
            and not user_preassignments_df.empty
            and "fixed" in user_preassignments_df.columns):
        for r in user_preassignments_df.itertuples(index=False):
            try:
                is_fixed = int(getattr(r, "fixed", 0) or 0) == 1
            except (TypeError, ValueError):
                is_fixed = False
            if not is_fixed:
                continue
            for sk in _matching_preassignment_keys(r, slot_keys):
                fixed_slot_keys.add(sk)
    # sorted: l'ordre d'iteració del set depèn del hash del procés i faria
    # el model no reproduïble entre execucions.
    flippable_keys = sorted(
        sk for sk in {sk for sp in machine_specs.values() for sk in sp[3]}
        if sk not in fixed_slot_keys
    )
    pres_flip: dict = {}
    for p in professionals:
        if p == "NONE" or presence_mode_by_prof.get(p) == "NO_PRESENCIAL":
            continue
        for sk in flippable_keys:
            if (p, sk) in x:
                day, franja, slot_id, presentiality, work_mode, position = sk
                name = (
                    f"flip_{p}_{day}_{franja}_{slot_id}_{presentiality}_{work_mode}_{position}"
                    .replace("-", "_").replace(" ", "_")
                )
                fv = model.NewBoolVar(name)
                model.Add(fv <= x[p, sk])
                pres_flip[(p, sk)] = fv

    # ── Doblat condicional per facultatiu ────────────────────────────
    # Indexa quins slot_ids estan marcats com a "doblat" per cada
    # facultatiu (`professionals.csv:doubled_machines`). Per a aquests
    # slots, la posició 2 (afegida a `build_weekday_calendar_from_*`)
    # és opcional al solver i només es manté assignada si almenys un
    # facultatiu marcat hi és present.
    marked_profs_by_slot_id: dict[str, set[str]] = {}
    prof_df = data.get("professionals")
    if isinstance(prof_df, pd.DataFrame) and "doubled_machines" in prof_df.columns:
        for r in prof_df.itertuples(index=False):
            pid = str(getattr(r, "professional_id", "") or "").strip().upper()
            value = str(getattr(r, "doubled_machines", "") or "").strip()
            if not pid or pid == "NONE" or not value:
                continue
            for item in value.split(";"):
                # normalize_slot: les claus del solver (sk[2]) passen per
                # _normalize_slots_df (espais/guions → '_'); sense la mateixa
                # normalització aquí, un slot amb espai mai casaria i la
                # posició 2 esdevindria cobertura dura obligatòria.
                sid = normalize_slot(item)
                if sid and sid not in {"NAN", "NONE"}:
                    marked_profs_by_slot_id.setdefault(sid, set()).add(pid)
    # Identifica pos2 condicionals: per a cada (day, franja, slot_id)
    # on slot_id ∈ marked, agafem les claus amb position>=2 i
    # presentiality=PRESENCIAL.
    conditional_pos2_keys: set = set()
    if marked_profs_by_slot_id:
        from collections import defaultdict
        groups: dict[tuple, list] = defaultdict(list)
        for sk in slot_keys:
            sid = str(sk[2]).strip().upper()
            if sid in marked_profs_by_slot_id and str(sk[3]).upper() == "PRESENCIAL":
                groups[(sk[0], sk[1], sk[2])].append(sk)
        for keys in groups.values():
            # Ordena per position; la primera (min position) queda
            # obligatòria, la resta són opcionals.
            keys_sorted = sorted(keys, key=lambda k: int(k[5]))
            for k in keys_sorted[1:]:
                conditional_pos2_keys.add(k)

    # ── Hard constraints ──────────────────────────────────────────────────────
    # INVENTARI CANÒNIC (dur vs tou) — si toques una restricció, actualitza'l:
    #
    # DURES (mai es violen; si xoquen entre elles → INFEASIBLE amb avís):
    #   1. Cobertura: cada màquina/franja té exactament el personal requerit.
    #   2. Indisponibilitats = ABSÈNCIES + GUÀRDIES (tarda/nit/postguàrdia)
    #      + indisponibilitats manuals (x==0).
    #   3. FESTIUS: estructural — els dies no laborables no entren al model.
    #   4. Compatibilitat diària (1 persona ≤ 1 màquina per franja, tret de
    #      vinculades/doblades) + doblatge condicional.
    #   5. Acoblament de blocs vinculats (H5, amb assumption de diagnòstic).
    #   6. Continuïtat de revisions en festius (H7, amb assumption).
    #   7. Mode de presència del facultatiu (NP-only / PRES-only).
    #   8. Comodí amb allowed=0 explícit.
    #   9. Caps durs comptables (mai infactibilitzen): flips NP→PRES i
    #      peonades/mes.
    #
    # TOVES (per pes, de més a menys — vegeu SOLVER_WEIGHTS):
    #   40M màquines fixes + canvis manuals · 10M elegibilitat (inclou
    #   «no va a aquell lloc»: allowed=0 a les activitats del lloc) ·
    #   8M dies NP/PRES per facultatiu · 6M targets de les REGLES
    #   D'EQUILIBRI · 5M estabilitat · 5M roda d'assignació · 500k target
    #   NP (tram 2) · trams 3-4 equitat (PRES i ordinàries) · 100k TLD ·
    #   50k comitè-màquina mateixa àrea · 40k teletreball matí de guàrdia ·
    #   20k repartiment de revisions · 10k balanç TC/RM.
    _add_coverage_constraints(
        model, x, professionals, slot_keys,
        unlimited_professionals=fallback_professionals,
        optional_slot_keys=conditional_pos2_keys,
    )
    _add_conditional_doubling_constraints(
        model, x, professionals, slot_keys,
        marked_profs_by_slot_id=marked_profs_by_slot_id,
        conditional_pos2_keys=conditional_pos2_keys,
    )
    _add_daily_compat_constraints(model, x, professionals, slot_rows, unique_days, review_slots,
                                  links_by_wf=links_by_wf,
                                  unlimited_professionals=fallback_professionals,
                                  pres_flip=pres_flip)
    _add_unavailability_constraints(model, x, slot_keys, unavailability_df, keys_by_day=keys_by_day)
    # NOTA: la restricció «llocs on treballa cada facultatiu»
    # (allowed_areas) s'ha eliminat — era redundant amb l'ELEGIBILITAT
    # (de fet es traduïa a files allowed=0 de la mateixa taula). Qui
    # vulgui limitar algú a un lloc concret, ho fa des d'Elegibilitat.
    total_eligibility_penalty = _add_eligibility_soft(
        model, x, professionals, slot_keys, eligibility_df,
        fallback_professionals=fallback_professionals,
    )
    # Soft: dies de la setmana exclusivament NO_PRES per facultatiu.
    # `no_pres_weekday_map` ja ve resolt en {prof: {day_str, ...}} (els
    # codis MON..FRI ja s'han expandit a dies concrets del calendari).
    # Penalitza els PRES en aquells dies; revisions excloses.
    no_pres_weekday_map = data.get("no_pres_weekday_map") or {}
    total_no_pres_weekday_violation = _add_no_pres_weekday_soft(
        model, x, slot_keys, no_pres_weekday_map, review_slots=review_slots,
    )
    # Soft simètric: dies de la setmana exclusivament PRES per facultatiu.
    # Penalitza NP en aquells dies; revisions excloses.
    pres_weekday_map = data.get("pres_weekday_map") or {}
    total_pres_weekday_violation = _add_pres_weekday_soft(
        model, x, slot_keys, pres_weekday_map, review_slots=review_slots,
    )
    # Restricció DURA: TLD respecta `allowed=0` del mapa d'elegibilitat.
    # Per defecte el comodí està exempt (universal); aquí l'usuari pot
    # marcar slots concrets on TLD NO ha d'anar (p.ex. un slot concret). Risc:
    # pot infactibilitzar si cap regular és elegible per a aquell slot.
    _add_fallback_eligibility_hard(
        model, x, fallback_professionals, slot_keys, eligibility_df,
    )
    # NOTA: el bloqueig DUR de TLD a revisions s'ha eliminat. Si l'usuari
    # vol que el comodí NO faci una revisió concreta, ha de posar
    # `allowed=0` a l'editor d'Elegibilitat (Restriccions). El comportament
    # per defecte d'aquesta restricció ja era equivalent a `allowed=0`
    # en tots els slots de revisió.
    _add_presence_mode_constraints(
        model, x, slot_keys, presence_mode_by_prof,
        review_slots=review_slots,
    )
    # Diagnòstic d'infeasibility: marquem les dures "fràgils" (poden xocar
    # amb la indisponibilitat) amb assumption literals. Si el model resulta
    # INFEASIBLE, CP-SAT ens dirà QUINA d'aquestes la fa infactible, en
    # comptes d'un "INFEASIBLE" sec. El cost de reificar és menyspreable.
    assume_h5 = model.NewBoolVar("assume_H5_acoblament_vinculat")
    assume_h7 = model.NewBoolVar("assume_H7_continuitat_revisio")
    _assume_names = {
        assume_h5.Index(): "H5 (acoblament de parells vinculats)",
        assume_h7.Index(): "H7 (continuïtat de revisió en festius)",
    }
    from src.solver.preprocessing import _build_unavailability_index
    unav_index = _build_unavailability_index(unavailability_df)
    _add_structural_coupling(model, x, professionals, keys_by_day, links_by_wf=links_by_wf,
                             enforce_lit=assume_h5)
    # Preassignacions fixes: TOVES amb pes màxim (H6 ha deixat de ser
    # una dura amb assumption — un xoc de fixos ja no infactibilitza).
    total_fixed_assignment_miss = _add_preassignment_constraints(
        model, x, preassignments_df, slot_keys,
    )
    _add_review_continuity(model, x, professionals, keys_by_day, slot_rows, working_map,
                           review_slots, unav_index=unav_index, enforce_lit=assume_h7)
    model.AddAssumptions([assume_h5, assume_h7])
    comite_entries = expand_comite_to_days(
        data.get("comite", pd.DataFrame()),
        unique_days,
    )
    planning_rules = data.get("planning_rules")
    # Mode de les regles d'equilibri: el cap dur dels flips segueix el mateix
    # criteri que els termes tous (personalitzat → taula; presencial →
    # targets setmanals automàtics; mensual_presencial → target MENSUAL
    # automàtic amb un únic període «MES»; total/none/mensual_total/
    # activitat → 0 flips més enllà de l'over_fixed — no fixen cap PRES).
    _rules_mode = (getattr(planning_rules, "mode", "personalitzat")
                   or "personalitzat") if planning_rules is not None else "personalitzat"
    _weekly_pres_targets = None
    _flip_periods, _flip_period_map = unique_weeks, week_map
    if _rules_mode == "presencial":
        from src.solver.objectives_targets import weekly_auto_targets
        _weekly_pres_targets = weekly_auto_targets(
            "presencial", quota_hard_professionals, unique_days, unique_weeks,
            week_map, working_map, absent_days_by_prof, capacity_pct_by,
            machine_specs,
        )
    elif _rules_mode == "mensual_presencial":
        # Sense això els flips NP→PRES quedarien prohibits del tot i el
        # target presencial mensual no tindria el seu mecanisme de
        # compensació (com sí que el té el mode setmanal «presencial»).
        from src.solver.objectives_targets import monthly_auto_targets
        _monthly_t = monthly_auto_targets(
            "presencial", quota_hard_professionals, unique_days,
            working_map, absent_days_by_prof, capacity_pct_by, machine_specs,
        )
        _flip_periods = ["MES"]
        _flip_period_map = {d: "MES" for d in unique_days}
        _weekly_pres_targets = {(p, "MES"): t for p, t in _monthly_t.items()}
    elif _rules_mode != "personalitzat":
        _weekly_pres_targets = {}

    # ── Flip INVERS (PRES→NP) ────────────────────────────────────────────
    # Simètric al pres_flip: un PRESENCIAL ordinari pot deixar de comptar
    # com a presencial (es fa en remot) per BAIXAR fins al target de qui
    # en té massa. Només es crea quan el mode d'equilibri fixa un target
    # presencial real — als modes total/none/mensual_total/activitat el
    # target és 0 com a sentinella de «cap objectiu presencial» i una
    # baixada lliure no tindria sentit. Exclou els slots FIXATS per
    # l'usuari, les peonades i qui té presence_mode=PRESENCIAL.
    #
    # DECISIÓ: el flip NP NO relaxa la compatibilitat diària (màx. 1
    # presencial/dia). Una màquina presencial feta en remot segueix
    # ocupant el dia del facultatiu; així el flip només canvia com
    # COMPTA a les regles d'equilibri, mai quantes màquines pot dur.
    # El cap d'`_add_flip_target_cap` ja el fa auto-limitat: només es
    # pot convertir l'excés per sobre del target, mai gratuïtament.
    np_flip: dict = {}
    if _rules_mode in ("presencial", "mensual_presencial", "personalitzat"):
        # Activitats marcades al catàleg com a OBLIGATÒRIAMENT PRESENCIALS:
        # mai es converteixen en remotes (l'usuari ho ha dit explícitament).
        _always_pres = {
            str(s).strip().upper()
            for s in (data.get("always_presential_slots") or set())
        }
        np_flippable_keys = sorted(
            sk for sk in {sk for sp in machine_specs.values() for sk in sp[2]}
            if sk not in fixed_slot_keys and str(sk[4]).upper() == "NORMAL"
            and str(sk[2]).strip().upper() not in _always_pres
        )
        for p in professionals:
            if p == "NONE" or presence_mode_by_prof.get(p) == "PRESENCIAL":
                continue
            for sk in np_flippable_keys:
                if (p, sk) in x:
                    day, franja, slot_id, presentiality, work_mode, position = sk
                    name = (
                        f"npflip_{p}_{day}_{franja}_{slot_id}_{presentiality}"
                        f"_{work_mode}_{position}"
                        .replace("-", "_").replace(" ", "_")
                    )
                    nv = model.NewBoolVar(name)
                    model.Add(nv <= x[p, sk])
                    np_flip[(p, sk)] = nv

    _add_flip_target_cap(
        model, x, pres_flip, quota_hard_professionals, unique_days,
        _flip_periods, _flip_period_map, working_map, absent_days_by_prof,
        capacity_pct_by, machine_specs, planning_rules=planning_rules,
        weekly_pres_targets=_weekly_pres_targets, np_flip=np_flip,
    )
    presential_tolerance = max(0, int(data.get("presential_tolerance", 0) or 0))

    # ── Roda d'assignació (TOVA): penalitza trencar el torn ────────────────
    _wheel_df = data.get("wheel_preferences")
    _wheel_miss_exprs = []
    if _wheel_df is not None and not getattr(_wheel_df, "empty", True):
        from src.solver.preprocessing import _matching_preassignment_keys
        # Normalització simètrica: la clau d'x usa l'id RAW del CSV.
        _prof_by_norm = {str(p).strip().upper(): p for p in professionals}
        for _wr in _wheel_df.itertuples(index=False):
            _wp = _prof_by_norm.get(
                str(getattr(_wr, "professional_id", "") or "").strip().upper()
            )
            if _wp is None:
                continue
            for _sk in _matching_preassignment_keys(_wr, slot_keys):
                if (_wp, _sk) in x:
                    _wheel_miss_exprs.append(1 - x[_wp, _sk])
    total_wheel_pref_miss = model.NewIntVar(
        0, max(1, len(_wheel_miss_exprs)), "total_wheel_pref_miss"
    )
    model.Add(
        total_wheel_pref_miss
        == (sum(_wheel_miss_exprs) if _wheel_miss_exprs else 0)
    )

    # ── Soft objectives ───────────────────────────────────────────────────────
    # MODEL DE PEONADES (cap-only): el solver crea `pn[p, sk]` per cada
    # NO_PRES no-revisió i facultatiu, amb una restricció DURA
    # `sum(pn) ≤ cap_mensual(p)`. NO hi ha penalització mínima: les
    # peonades emergeixen NATURALMENT al tier NP per absorbir l'excedent
    # de NO_PRES sobre el target setmanal (si no n'hi ha, peonades = 0).
    # Cap individual: round(peonada_cap_full_time * jornada / 100).
    # Comodí exempt; revisions excloses del conjunt elegible.
    peonada_cap_full_time = max(0, int(data.get("peonada_cap", 3) or 0))
    peonada_vars, total_peonada_shortfall = _add_peonada_monthly_cap(
        model, x, professionals, slot_keys, average_capacity_pct,
        fallback_professionals=fallback_professionals,
        cap_per_month_full_time=peonada_cap_full_time,
        review_slots=review_slots,
        secondary_slot_ids=secondary_slot_ids,
    )
    # Mútuament exclusius: si un slot NP es flipa a PRES via pres_flip,
    # NO pot ser alhora PEONADA (semànticament incoherent: una peonada
    # és NP extra; un slot flipat ja compta com a PRES). Si totes dues
    # vars existeixen per la mateixa (p, sk), prohibim que siguin 1
    # alhora.
    for (p, sk), pn_var in peonada_vars.items():
        fv = pres_flip.get((p, sk))
        if fv is not None:
            model.Add(pn_var + fv <= 1)
    (total_weekly_presential_shortfall, total_weekly_presential_overage,
     total_weekly_np_shortfall, total_weekly_np_overage) = _add_weekly_soft_terms(
        model, x, quota_hard_professionals, unique_days, unique_weeks,
        week_map, working_map, absent_days_by_prof, keys_by_day, capacity_pct_by, review_slots,
        planning_rules=planning_rules, machine_specs=machine_specs, pres_flip=pres_flip,
        presential_tolerance=presential_tolerance,
        peonada_vars=peonada_vars, eligibility_df=eligibility_df,
        np_flip=np_flip,
    )
    # Excloem del balanç de presencialitats els facultatius que mai poden
    # fer presencials: presence_mode=NO_PRESENCIAL (p.ex. comodí TLD) i
    # fallback. Si els incloguéssim, el seu count seria sempre 0 i el seu
    # target proporcional faria que el solver pagués deviation impossible
    # de corregir.
    active_for_presential = [
        p for p in active_professionals
        if presence_mode_by_prof.get(p) != "NO_PRESENCIAL"
        and p not in fallback_professionals
    ]
    prior_pres = data.get("prior_presential_counts") or {}
    (pres_dev_l1, presential_counts, max_presential, min_presential,
     pres_dev_linf, _pres_target_by_p,
     cum_pres_l1, cum_pres_linf, _cum_max_presential, _cum_min_presential,
     _cum_pres_target_by_p) = _add_presentiality_balance(
        model, x, active_for_presential, professionals, slot_keys, slot_rows,
        effective_capacity_pct, pres_flip=pres_flip, flippable_keys=flippable_keys,
        np_flip=np_flip,
        slot_links=slot_links, prior_presential_counts=prior_pres,
        review_slots=review_slots,
    )
    # Balanç MÀQUINES ORDINÀRIES per facultatiu (= PRES + NO_PRES NORMAL,
    # SENSE peonades, SENSE revisions, SENSE guàrdies). El comodí (TLD)
    # NO entra al balanç: absorbeix l'excedent quan els facultatius reals
    # arriben al seu target.
    # Model cap-only: peonadas emergeixen NATURALMENT per absorbir
    # l'excedent de NP sobre el target NP_ord (fins al cap mensual). En
    # estat estacionari, si el calendari NP coincideix amb la suma de
    # targets NP_ord, peonadas = 0. Per al balanç ordinari passem un
    # estimat = 0 (cap subtraction al target): si en sobren, el balanç
    # podria estar lleugerament esbiaixat però el tier NP ja les empeny
    # cap a 0.
    peonada_target_per_prof = {p: 0 for p in professionals}
    prior_total = data.get("prior_total_machine_counts") or {}
    (tot_dev_l1, tot_dev_linf, cum_tot_l1, cum_tot_linf,
     _tot_counts, _tot_target) = _add_ordinary_machine_balance(
        model, x, active_for_presential, professionals, slot_keys,
        effective_capacity_pct, review_slots, slot_links=slot_links,
        prior_total_counts=prior_total,
        peonada_vars=peonada_vars,
        peonada_target_per_prof=peonada_target_per_prof,
    )
    (spread_tc, spread_rm, tc_counts, rm_counts, family_imbalance,
     max_tc, min_tc, max_rm, min_rm) = _add_tc_rm_balance(
        model, x, active_professionals, real_professionals, slot_keys, average_capacity_pct,
        review_slots=review_slots,
    )
    # NOTA: el cap dur mensual |TC−RM| ≤ max(3, ceil(…)) s'ha eliminat.
    # L'equilibri TC vs RM intra-facultatiu és TOU (no dur): es minimitza
    # la suma de |TC−RM| per facultatiu al tram 4 amb pes baix
    # (`tc_rm_balance`). `total_family_imbalance` ja NO és un dummy a 0:
    # reflecteix el desequilibri real (també és el que es reporta al log).
    _family_diff_vars = list(family_imbalance.values())
    total_family_imbalance = model.NewIntVar(
        0, max(1, len(slot_keys)), "total_family_imbalance"
    )
    model.Add(
        total_family_imbalance == (sum(_family_diff_vars) if _family_diff_vars else 0)
    )
    # Els slots de revisió amb facultatiu fix al catàleg (assignee) ja estan
    # preassignats: equilibrar-los distorsiona el repartiment dels lliures
    # (p. ex. REV_TC fix a un facultatiu inflaria el seu recompte i deixaria
    # REV_RM concentrat). Només equilibrem els slots de revisió lliures.
    # Comparació normalitzada (igual raó que `_review_cfg`).
    _fixed_slot_ids = {
        _norm_slot_for_cfg(s) for s in (data.get("slot_fixed_assignments") or {})
    }
    review_balance_slots = {
        s for s in review_slots if _norm_slot_for_cfg(s) not in _fixed_slot_ids
    }
    spread_review_rm, review_rm_counts, max_review_rm, min_review_rm = _add_review_balance(
        model, x, active_professionals, professionals, slot_rows, slot_keys,
        review_slots=review_balance_slots,
    )
    # NOTA: la restricció DURA d'equitat de revisions (round-robin
    # determinista) s'ha eliminat. Ara l'equitat de revisions és TOVA:
    # `spread_review_rm` entra a l'objectiu al tram 4 amb pes baix
    # (`review_spread`), de manera que el solver reparteix les revisions
    # lliures entre facultatius quan no perjudica cap objectiu superior.
    # L'usuari pot configurar elegibilitat per slot de revisió a
    # Restriccions › Elegibilitat per controlar qui pot fer cadascuna.
    total_tld_usage = _add_fallback_usage_penalty(
        model, x, fallback_professionals, slot_keys, review_slots,
    )
    # NOTA: el cap mensual de peonades per facultatiu s'imposa al bloc
    # «Soft objectives» més amunt (`_add_peonada_monthly_cap`).
    fac_targets_df = data.get("facultatiu_targets", pd.DataFrame())
    if fac_targets_df is not None and not fac_targets_df.empty:
        fac_targets_df = fac_targets_df[
            fac_targets_df["professional_id"].astype(str).str.strip().str.upper()
            .isin(set(professionals))
        ].copy()
    # facultatiu_target es CALCULA pels efectes col·laterals sobre el
    # model (afegeix constraints per cap setmanal de presencials per
    # facultatiu) però el seu total NO entra al Minimize: el spread PRES
    # ja porta cap al target uniforme.
    _add_facultatiu_targets(
        model, fac_targets_df, x, slot_keys, review_slots,
        pres_flip, flippable_keys, unique_weeks, week_map, working_map,
        absent_days_by_prof, capacity_pct_by, planning_rules,
        active_professionals,
    )
    total_stability_changes = _add_stability_terms(model, x, stable_assignment_by_slot)
    total_comite_pref_miss = _add_comite_preferred_machine_terms(
        model, x, slot_keys, professionals, comite_entries,
        review_slots=review_slots,
    )
    total_guard_morning_miss = _add_guard_morning_telework_terms(
        model, x, slot_keys, guard_prof_days, review_slots
    )

    # ── Objective ─────────────────────────────────────────────────────────────
    # Nota: `total_facultatiu_target_penalty` es CALCULA per a logs/UI però
    # NO entra al Minimize: el presential_spread (L1+L∞) ja porta cap a un
    # target proporcional a la jornada; afegir-hi facultatiu_target a 500k
    # generava conflicte amb el spread i feia el solver inestable.
    # ── Objectiu: optimització JERÀRQUICA per trams (lexicogràfica) ─────────
    # Workflow funcional acordat amb la usuària:
    #   Tram 1 — PRES target EXACTE (shortfall + overage). Si el
    #      calendari demana més PRES dels que la suma de targets dona,
    #      el solver paga overage (cobertura del calendari és HARD); si
    #      en demana menys, paga shortfall (es flipa NP→PRES fins arribar).
    #   Tram 2 — NP_ord target EXACTE (shortfall + overage). NP_ord =
    #      NP_total − peonadas_setmana. Si NP_total > target, les peonades
    #      absorbeixen l'excedent fins al cap mensual (HARD = round(3 *
    #      jornada / 100)); si NP_total < target, peonadas = 0. L'excedent
    #      no absorbit va al comodí (TLD) via cobertura.
    #   Tram 3 — Equitat PRES entre facultatius (spread L1/L∞, mensual i
    #      acumulat). Amb PRES target ja complert, distribueix el marge.
    #   Tram 4 — Equitat ordinàries (PRES + NP_ord) + secundaris
    #      (estabilitat, mètric/màquina targets, comitè, telework, TLD).
    # Una suma ponderada única NO garanteix aquest ordre: el cost real és
    # pes×valor i les desviacions d'spread valen >1, així que un spread gran
    # pot superar el presencial. Per això resolem TRAM A TRAM: optimitzem el
    # tram, bloquegem el seu valor (≤ millor + slack) i passem al següent.
    # Els pesos de SOLVER_WEIGHTS ordenen DINS de cada tram (on sí que són
    # trade-offs reals); l'ordre ENTRE trams el garanteix el bloqueig.
    # `facultatiu_target` segueix sense entrar a l'objectiu (només efectes
    # col·laterals sobre el model, vegeu més amunt).
    W = SOLVER_WEIGHTS
    tier_terms = [
        ("presencial", [
            # Ex-dura, ara TOVA amb el pes més alt de tots: els fixos
            # (màquines fixes per facultatiu + canvis manuals).
            (total_fixed_assignment_miss, W["fixed_assignment_violation"]),
            (total_eligibility_penalty, W["eligibility_penalty"]),
            # Dies NP-only per facultatiu (soft): penalitza cada PRES
            # assignat al facultatiu en un dia marcat com a no-presencial.
            (total_no_pres_weekday_violation, W["no_pres_weekday_violation"]),
            # Dies PRES-only per facultatiu (simètric): penalitza NP.
            (total_pres_weekday_violation, W["pres_weekday_violation"]),
            # Regles d'equilibri (shortfall + overage sobre el target PRES
            # EXACTE): després dels compromisos de dia de cada facultatiu
            # i per sobre de la roda i els comitès.
            (total_weekly_presential_shortfall, W["weekly_presential_shortfall"]),
            (total_weekly_presential_overage, W["weekly_presential_shortfall"]),
        ]),
        ("no_presencial", [
            # Shortfall: sobre np_incl (compta peonades) → convertir NP en
            # peonada NO genera shortfall. Overage: sobre np_ord (sense
            # peonades) → l'excés d'NP ordinari es paga com a peonada.
            (total_weekly_np_shortfall, W["weekly_shortfall"]),
            (total_weekly_np_overage, W["weekly_overage"]),
            # NOTA: ja NO empenyem les peonades cap a un cap fix
            # (`peonada_shortfall` eliminat de l'objectiu). Les peonades
            # emergeixen ARA per igualar les màquines ORDINÀRIES cap avall:
            # l'excés per sobre de la quota justa (terme unilateral del
            # tram 4 `ordinary_spread`) es converteix en peonada, que resta
            # del comptador d'ordinàries. El `peonada_cap` segueix sent el
            # màxim dur mensual per facultatiu.
        ]),
        ("equitat_presencials", [
            (pres_dev_l1, W["presential_spread_l1"]),
            (pres_dev_linf, W["presential_spread_max"]),
            (cum_pres_l1, W["presential_cum_spread_l1"]),
            (cum_pres_linf, W["presential_cum_spread_max"]),
        ]),
        ("equitat_ordinaries", [
            (tot_dev_l1, W["ordinary_spread_l1"]),
            (tot_dev_linf, W["ordinary_spread_max"]),
            (cum_tot_l1, W["ordinary_cum_spread_l1"]),
            (cum_tot_linf, W["ordinary_cum_spread_max"]),
            (total_stability_changes, W["stability"]),
            # Roda d'assignació: seguir el torn rotatori (tova).
            (total_wheel_pref_miss, W["wheel_preference"]),
            (total_comite_pref_miss, W["comite_preferred_machine"]),
            (total_guard_morning_miss, W["guard_morning_telework"]),
            # TLD comodí: amb el tier 2 (NP target) ja bloquejat amb
            # peonades=0 cost, el solver minimitza ara TLD al tier 4.
            # Pes 100k (vs 5k anterior): força incentiu fort per convertir
            # slots TLD en regulars amb peonadas (cost 0 al tier 2 ja
            # bloquejat), mantenint encara la flexibilitat de TLD com a
            # vàlvula d'escapament quan el cap de peonades està exhaurit.
            (total_tld_usage, W["tld_usage"]),
            # Equilibri TC/RM intra-facultatiu (TOU, pes baix): suma de
            # |TC−RM| per facultatiu. Desempat, no competeix amb les
            # equitats principals.
            (total_family_imbalance, W["tc_rm_balance"]),
            # Equitat de revisions lliures (TOVA, pes baix): spread max−min.
            # Les revisions són slots independents (no compten com a
            # màquina), així que repartir-les surt gairebé "gratis" i només
            # actua com a desempat sense perjudicar la resta d'objectius.
            (spread_review_rm, W["review_spread"]),
        ]),
    ]

    # ── Solve per trams ─────────────────────────────────────────────────────────
    # Cada tram és un Solve independent (CP-SAT no és incremental). El temps
    # total (PAC3_SOLVER_MAX_SECONDS, per mes) es reparteix: el tram 2 és el
    # feixuc. Cada tram s'inicialitza (warm-start) amb la solució del tram
    # anterior, així el re-solve amb el tram superior bloquejat és molt ràpid.
    # PAC3_SOLVER_TIER_SLACK: marge absolut en bloquejar un tram (0 = estricte).
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = _solver_int_env("PAC3_SOLVER_WORKERS", 8)
    solver.parameters.random_seed = 42
    # El temps de wall ≈ el pressupost (PAC3_SOLVER_MAX_SECONDS): CP-SAT no
    # arriba a PROVAR l'optimalitat aquí, així que no para abans de l'hora.
    # Default 60s: el tier 4 (equitat ORD) és el feixuc i necessita marge per
    # baixar de FEASIBLE a OPTIMAL. Per màquines lentes pujar a 90-120s; per
    # màquines ràpides pots baixar a 30s. Les restriccions DURES (cap de
    # peonades, equitat de revisions, cobertura) es compleixen sempre,
    # independentment del temps de cerca.
    total_budget = float(_solver_int_env("PAC3_SOLVER_MAX_SECONDS", 60))
    # 4 trams (PRES, NP, equitat PRES, equitat ORD). Concentrem temps a
    # l'equitat ORD que sol acabar FEASIBLE (no OPTIMAL). El tier PRES
    # i NP són fàcils (objectiu 0 ja sortia a ~3s); donem-los menys.
    tier_budget_frac = (0.10, 0.15, 0.25, 0.50)
    try:
        tier_slack = max(0, int(os.environ.get("PAC3_SOLVER_TIER_SLACK", "0")))
    except (TypeError, ValueError):
        tier_slack = 0

    # ── Diagnòstic per tram ──────────────────────────────────────────────────
    # Per a cada tram, escrivim a stdout (que es captura al log de generació)
    # i a outputs/solver_log.txt el valor de cada terme i el subtotal del
    # tram. Ajuda a entendre quan el solver "es queda atrapat" en algun tram
    # i veure si les peonades, presencials o ordinaries es resolen bé.
    solver_log_lines: list[str] = []

    def _log(line: str) -> None:
        print(line)
        solver_log_lines.append(line)

    # Warm-start (opcional): sembra el solver amb un calendari anterior
    # com a HINTS (sense penalització, a diferència de `stability_from`).
    # Així clics repetits de Generar MILLOREN el pla en lloc de recomençar
    # de zero: el solver parteix de l'última solució i la refina dins del
    # pressupost. _solve_tiers neteja i re-sembra els hints a cada tram, així
    # que aquests només afecten el punt de partida del primer tram.
    _warm = data.get("warm_start_assignments")
    if _warm is not None and not _warm.empty:
        _warm_by_slot = _stability_by_slot(_warm, professionals, slot_keys)
        _n_hints = 0
        for _sk, _prof in _warm_by_slot.items():
            if (_prof, _sk) in x:
                model.AddHint(x[_prof, _sk], 1)
                _n_hints += 1
        _log(f"Warm-start: {_n_hints} assignacions sembrades del pla anterior.")

    status = _solve_tiers(
        model, solver, tier_terms, x,
        total_budget, tier_budget_frac, tier_slack, _log,
    )

    # ── Resum per facultatiu (PRES / NORMAL / Peonades / Ordinàries / TLD) ───
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        _log_per_professional_summary(
            _log, solver, real_professionals, presential_counts,
            peonada_vars, x, slot_keys, review_slots,
        )
        # Escriure tot el log a fitxer per inspecció posterior.
        try:
            from pathlib import Path as _Path
            _log_path = _Path("outputs/solver_log.txt")
            _log_path.parent.mkdir(parents=True, exist_ok=True)
            _log_path.write_text("\n".join(solver_log_lines), encoding="utf-8")
        except OSError:
            pass

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE:
            return _infeasibility_message(
                solver, _assume_names,
                keys_by_day=keys_by_day, professionals=professionals,
                unavailability_df=unavailability_df,
            ), [], []
        return "No s'ha trobat solució.", [], []

    return _extract_solution(
        solver, x, professionals, real_professionals, active_professionals,
        slot_keys, slot_rows, unique_days, presential_counts,
        tc_counts, rm_counts, family_imbalance, review_rm_counts,
        pres_dev_l1, max_presential, min_presential,
        spread_tc, max_tc, min_tc, spread_rm, max_rm, min_rm,
        spread_review_rm, max_review_rm, min_review_rm,
        total_family_imbalance, average_capacity_pct,
        pres_flip=pres_flip,
        np_flip=np_flip,
        pres_dev_linf=pres_dev_linf,
        peonada_vars=peonada_vars,
        effective_capacity_pct=effective_capacity_pct,
    )
