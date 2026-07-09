"""Objectius tous basats en targets (setmanals/mensuals): targets per
facultatiu, metric targets (TC/RM/peonades), targets per màquina."""

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.domain.planning_rules import PlanningRules
from src.solver.constraints import _build_machine_term_specs, _collect_machine_terms_for_day
from src.solver.normalize import _make_slot_key, _norm_set


def _add_peonada_monthly_cap(model, x, professionals, slot_keys,
                              average_capacity_pct, fallback_professionals=None,
                              cap_per_month_full_time=3, review_slots=None,
                              secondary_slot_ids=None):
    """Peonades mensuals per facultatiu: TARGET + CAP (l'usuari indica un
    valor que és alhora mínim i màxim mensuals, proporcional a la
    jornada). El solver intenta col·locar EXACTAMENT cap(p) peonades a
    NP no-revisió, no doblada i no secundària de cada facultatiu i mes.

    Cap individual:
        `cap(p) = round(cap_per_month_full_time * capacity_pct[p] / 100)`
    Jornada al 70% → cap ≈ 2; jornada 100% → cap = 3. El comodí
    (fallback) està exempt.

    Restriccions estructurals al conjunt elegible:
      - Només NO_PRESENCIAL (les peonades MAI són PRES).
      - Cap revisió (es tracten amb mecanisme propi).
      - Cap slot DOBLAT (`(day, franja, slot_id)` que apareix més
        d'un cop entre `slot_keys`): les peonades només es poden
        aplicar a màquines d'un sol facultatiu.
      - Cap màquina SECUNDÀRIA (slots que apareixen al `linked_to`
        del catàleg): són la part vinculada d'un altre slot i no
        s'usen com a peonades.

    Restriccions runtime:
      - HARD: `pn[p, sk] <= x[p, sk]` (no peonada si no assignada).
      - HARD: `sum_{sk in month} pn[p, sk] <= cap(p)` (sostre).
      - SOFT: shortfall = max(0, cap(p) − sum(pn)). Penalitzat al
        solver perquè el solver afegeixi peonades fins arribar a cap(p).

    Retorna (peonada_vars, total_shortfall):
      peonada_vars: dict {(p, sk): BoolVar}
      total_shortfall: IntVar amb la suma de shortfalls (s'afegeix a
        l'objectiu del solver amb un pes moderat)."""
    from collections import Counter
    fb = {str(f).strip().upper() for f in (fallback_professionals or ())}
    review_set = _norm_set(review_slots)
    secondary_set = _norm_set(secondary_slot_ids)
    # Compta instàncies de (day, franja, slot_id) per detectar doblats.
    slot_counts = Counter((sk[0], sk[1], sk[2]) for sk in slot_keys)
    no_pres_keys = [
        sk for sk in slot_keys
        if str(sk[3]).upper() == "NO_PRESENCIAL"
        and str(sk[2]).strip().upper() not in review_set
        and str(sk[2]).strip().upper() not in secondary_set
        and slot_counts[(sk[0], sk[1], sk[2])] == 1
    ]
    if not no_pres_keys or int(cap_per_month_full_time) <= 0:
        zero = model.NewIntVar(0, 1, "total_peonada_shortfall")
        model.Add(zero == 0)
        return {}, zero

    keys_by_month: dict[str, list] = {}
    for sk in no_pres_keys:
        keys_by_month.setdefault(str(sk[0])[:7], []).append(sk)

    peonada_vars: dict = {}
    shortfall_terms = []
    ub_total = 0
    for p in professionals:
        if str(p).strip().upper() in fb:
            continue
        cap_pct = max(0, int(average_capacity_pct.get(p, 100)))
        cap_n = max(0, round(int(cap_per_month_full_time) * cap_pct / 100))
        if cap_n <= 0:
            continue
        for ym, month_keys in keys_by_month.items():
            month_pn = []
            for sk in month_keys:
                if (p, sk) not in x:
                    continue
                vname = (
                    f"peonada_{p}_{sk[0]}_{sk[1]}_{sk[2]}_{sk[5]}"
                    .replace("-", "_").replace(" ", "_")
                )
                pn = model.NewBoolVar(vname)
                model.Add(pn <= x[p, sk])
                peonada_vars[(p, sk)] = pn
                month_pn.append(pn)
            if month_pn:
                # HARD cap mensual.
                model.Add(sum(month_pn) <= cap_n)
                # SOFT shortfall: el solver intenta arribar a cap_n.
                cnt = model.NewIntVar(
                    0, max(1, len(month_pn)),
                    f"peonada_count_{p}_{ym}".replace("-", "_"),
                )
                model.Add(cnt == sum(month_pn))
                short = model.NewIntVar(
                    0, cap_n,
                    f"peonada_short_{p}_{ym}".replace("-", "_"),
                )
                model.Add(short >= cap_n - cnt)
                shortfall_terms.append(short)
                ub_total += cap_n

    total_short = model.NewIntVar(
        0, max(1, ub_total), "total_peonada_shortfall"
    )
    model.Add(total_short == (sum(shortfall_terms) if shortfall_terms else 0))
    return peonada_vars, total_short


def weekly_auto_targets(kind, quota_hard_professionals, unique_days, unique_weeks,
                        week_map, working_map, absent_days_by_prof,
                        capacity_pct_by, machine_specs):
    """Targets setmanals AUTOMÀTICS per als modes «presencial» i «total»:
    per cada setmana, la càrrega REAL (nombre de màquines-grup d'aquella
    setmana — PRESENCIALS si kind='presencial', totes si kind='total')
    es reparteix entre els facultatius actius proporcionalment a la seva
    capacitat aquella setmana. Retorna {(professional, setmana): target}."""
    from src.solver.objectives_balance import _apportion_by_capacity

    days_by_week: dict = {}
    for d in unique_days:
        days_by_week.setdefault(week_map[d], []).append(d)

    # Càrrega per dia (independent del professional): grups vinculats
    # compten 1; per a 'presencial', un grup compta si té algun membre PRES.
    load_by_day: dict[str, int] = {}
    for day, spec in (machine_specs or {}).items():
        coupling_groups, machine_keys, presential_keys, _flip = spec
        if kind == "presencial":
            n_groups = sum(
                1 for g in coupling_groups
                if any(str(sk[3]).upper() == "PRESENCIAL" for sk in g)
            )
            load_by_day[day] = n_groups + len(presential_keys)
        else:
            load_by_day[day] = len(coupling_groups) + len(machine_keys)

    out: dict = {}
    for yw in unique_weeks:
        week_days = [
            d for d in days_by_week.get(yw, []) if working_map.get(d, 1) == 1
        ]
        load = sum(load_by_day.get(d, 0) for d in week_days)
        if load <= 0:
            continue
        week_capacity: dict = {}
        for p in quota_hard_professionals:
            active = [d for d in week_days if d not in absent_days_by_prof[p]]
            cap = sum(capacity_pct_by[(p, d)] for d in active)
            if cap > 0:
                week_capacity[p] = cap
        actius = sorted(week_capacity)
        targets = _apportion_by_capacity(load, actius, week_capacity)
        for p, t in targets.items():
            out[(p, yw)] = t
    return out


def monthly_auto_targets(kind, quota_hard_professionals, unique_days,
                         working_map, absent_days_by_prof, capacity_pct_by,
                         machine_specs):
    """Target MENSUAL automàtic per facultatiu (modes «mensual_presencial»
    i «mensual_total»): la càrrega REAL de tot el mes (màquines-grup
    PRESENCIALS si kind='presencial', totes si kind='total') repartida
    proporcionalment a la capacitat mensual. Retorna {professional: target}."""
    from src.solver.objectives_balance import _apportion_by_capacity

    working_days = [d for d in unique_days if working_map.get(d, 1) == 1]
    load = 0
    for d in working_days:
        coupling_groups, machine_keys, presential_keys, _flip = machine_specs[d]
        if kind == "presencial":
            load += sum(
                1 for g in coupling_groups
                if any(str(sk[3]).upper() == "PRESENCIAL" for sk in g)
            ) + len(presential_keys)
        else:
            load += len(coupling_groups) + len(machine_keys)
    caps: dict = {}
    for p in quota_hard_professionals:
        c = sum(
            capacity_pct_by[(p, d)] for d in working_days
            if d not in absent_days_by_prof[p]
        )
        if c > 0:
            caps[p] = c
    return _apportion_by_capacity(load, sorted(caps), caps)


def _add_monthly_soft_terms(model, x, quota_hard_professionals, unique_days,
                            working_map, absent_days_by_prof, keys_by_day,
                            capacity_pct_by, specs, mode, rules, pres_flip,
                            presential_tolerance, eligibility_df=None):
    """Objectiu tou MENSUAL: tot el període del solve (un mes) es tracta
    com un ÚNIC bloc — la càrrega real del mes es reparteix entre els
    facultatius proporcionalment a la seva capacitat mensual, sense cap
    objectiu per setmana. Tres variants (`mode`):

      mensual_presencial — càrrega = màquines-grup PRESENCIALS del mes;
                           es compta el PRES de cada facultatiu.
      mensual_total      — càrrega = TOTES les màquines-grup del mes;
                           es compta el total de cada facultatiu.
      activitat          — PRIMARI: instàncies de l'activitat
                           `rules.balance_activity` al mes, repartides
                           NOMÉS entre els facultatius ELEGIBLES (si
                           `eligibility_df` hi és) — un no-elegible amb
                           target > 0 generaria una penalització
                           impossible de satisfer. SECUNDARI: la RESTA
                           de màquines del mes (excloent l'activitat i
                           els blocs que la contenen) també s'equilibra,
                           entre TOTS els facultatius actius, per sota
                           de l'objectiu primari.

    Retorna la mateixa forma que `_add_weekly_soft_terms`:
        (total_pres_shortfall, total_pres_overage,
         total_np_ord_shortfall, total_np_ord_overage)
    amb els dos primers portant la desviació PRIMÀRIA (tram 1) i els dos
    NP la desviació SECUNDÀRIA de la resta de màquines en mode
    «activitat» (tram 2) — zero als altres modes, com al «total»
    setmanal."""
    from src.solver.objectives_balance import _apportion_by_capacity

    def _zero(name):
        v = model.NewIntVar(0, 1, name)
        model.Add(v == 0)
        return v

    zeros = (
        "total_weekly_np_ord_shortfall",
        "total_weekly_np_ord_overage",
    )

    working_days = [d for d in unique_days if working_map.get(d, 1) == 1]

    activity = ""
    if mode == "activitat":
        # normalize_slot: el catàleg (i per tant balance_activity) pot dur
        # espais o guions; les claus del solver ja estan normalitzades —
        # sense això, "ECO-DOPPLER" mai coincidiria amb "ECO_DOPPLER" i el
        # criteri primari quedaria silenciosament inert.
        from src.domain.slot_norm import normalize_slot
        activity = normalize_slot(
            str(getattr(rules, "balance_activity", "") or "")
        )
        if not activity:
            # Sense activitat seleccionada no hi ha res a equilibrar.
            return (
                _zero("total_weekly_presential_shortfall"),
                _zero("total_weekly_presential_overage"),
                _zero(zeros[0]), _zero(zeros[1]),
            )
        act_keys_by_day: dict = {}
        for d in working_days:
            act_keys_by_day[d] = [
                sk for sk in keys_by_day.get(d, [])
                if str(sk[2]).strip().upper() == activity
            ]
        load = sum(len(v) for v in act_keys_by_day.values())
    elif mode == "mensual_presencial":
        load = 0
        for d in working_days:
            coupling_groups, _mk, presential_keys, _flip = specs[d]
            load += sum(
                1 for g in coupling_groups
                if any(str(sk[3]).upper() == "PRESENCIAL" for sk in g)
            ) + len(presential_keys)
    else:  # mensual_total
        load = 0
        for d in working_days:
            coupling_groups, machine_keys, _pk, _flip = specs[d]
            load += len(coupling_groups) + len(machine_keys)

    # Elegibilitat per al mode «activitat»: parell absent ⇒ permès (mateix
    # criteri que `_add_eligibility_soft`), així que només queden fora del
    # repartiment els facultatius amb `allowed=0` explícit per l'activitat.
    denied_for_activity: set = set()
    if activity and eligibility_df is not None and not getattr(
        eligibility_df, "empty", True
    ):
        from src.domain.slot_norm import normalize_slot as _norm_act
        for r in eligibility_df.itertuples(index=False):
            if _norm_act(str(getattr(r, "slot_id", ""))) != activity:
                continue
            try:
                ok = int(float(getattr(r, "allowed", 1)))
            except (TypeError, ValueError):
                ok = 1
            if ok == 0:
                denied_for_activity.add(
                    str(getattr(r, "professional_id", "")).strip().upper()
                )

    # Capacitat mensual per facultatiu (suma de jornades dels seus dies
    # actius del mes). `month_capacity_all` inclou tothom amb capacitat;
    # `month_capacity` (repartiment PRIMARI) en treu els no-elegibles per
    # a l'activitat i, en mode «activitat», es calcula NOMÉS sobre els
    # dies on l'activitat té instàncies — un facultatiu que mai hi és
    # aquells dies (guàrdies/absències recurrents) no ha de rebre un
    # target impossible de complir.
    act_days: set = set()
    if mode == "activitat":
        act_days = {d for d, v in act_keys_by_day.items() if v}
    month_capacity_all: dict = {}
    month_capacity: dict = {}
    active_days_by_prof: dict = {}
    for p in quota_hard_professionals:
        adays = [
            d for d in working_days if d not in absent_days_by_prof[p]
        ]
        active_days_by_prof[p] = adays
        cap = sum(capacity_pct_by[(p, d)] for d in adays)
        if cap > 0:
            month_capacity_all[p] = cap
        if str(p).strip().upper() in denied_for_activity:
            continue
        cap_primary = (
            sum(capacity_pct_by[(p, d)] for d in adays if d in act_days)
            if mode == "activitat" else cap
        )
        if cap_primary > 0:
            month_capacity[p] = cap_primary

    actius = sorted(month_capacity)
    targets = _apportion_by_capacity(load, actius, month_capacity)

    short_terms: list = []
    over_terms: list = []
    for p in actius:
        adays = active_days_by_prof[p]
        if mode == "activitat":
            count_terms = [
                x[p, sk] for d in adays for sk in act_keys_by_day.get(d, [])
                if (p, sk) in x
            ]
        else:
            count_terms = []
            for d in adays:
                mt, pmt = _collect_machine_terms_for_day(
                    model, x, p, d, specs[d], "soft_month_assign",
                    pres_flip=pres_flip,
                )
                count_terms.extend(
                    pmt if mode == "mensual_presencial" else mt
                )
        target = targets.get(p, 0)
        if not count_terms and target <= 0:
            continue
        n = max(1, len(count_terms))
        cnt = model.NewIntVar(0, n, f"monthly_count_{mode}_{p}")
        model.Add(cnt == (sum(count_terms) if count_terms else 0))
        short = model.NewIntVar(0, max(1, target), f"monthly_short_{p}")
        model.Add(short >= target - cnt - presential_tolerance)
        model.Add(short >= 0)
        short_terms.append(short)
        over = model.NewIntVar(0, n, f"monthly_over_{p}")
        model.Add(over >= cnt - target - presential_tolerance)
        model.Add(over >= 0)
        over_terms.append(over)

    ub = max(1, sum(targets.values()) + load)
    total_short = model.NewIntVar(0, ub, "total_weekly_presential_shortfall")
    model.Add(total_short == (sum(short_terms) if short_terms else 0))
    total_over = model.NewIntVar(0, ub, "total_weekly_presential_overage")
    model.Add(total_over == (sum(over_terms) if over_terms else 0))

    # ── SECUNDARI (només mode «activitat»): la RESTA de màquines del mes
    # també s'equilibra — l'activitat és el criteri PRINCIPAL (tram 1) i
    # la resta va al parell NP (tram 2), per sota. S'exclouen del
    # recompte i de la càrrega les instàncies de l'activitat i els blocs
    # vinculats que la contenen (aquests ja «són» l'activitat: una sola
    # persona cobreix el bloc). El repartiment inclou TOTS els
    # facultatius actius (l'elegibilitat per slot ja la vigila el terme
    # d'elegibilitat propi). ──
    if mode != "activitat":
        return total_short, total_over, _zero(zeros[0]), _zero(zeros[1])

    rest_specs: dict = {}
    rest_load = 0
    for d in working_days:
        coupling_groups, machine_keys, presential_keys, flip = specs[d]
        fg = [
            g for g in coupling_groups
            if not any(str(sk[2]).strip().upper() == activity for sk in g)
        ]
        fm = [
            sk for sk in machine_keys
            if str(sk[2]).strip().upper() != activity
        ]
        fp = [
            sk for sk in presential_keys
            if str(sk[2]).strip().upper() != activity
        ]
        rest_specs[d] = (fg, fm, fp, flip)
        rest_load += len(fg) + len(fm)

    rest_actius = sorted(month_capacity_all)
    rest_targets = _apportion_by_capacity(
        rest_load, rest_actius, month_capacity_all,
    )
    rest_short_terms: list = []
    rest_over_terms: list = []
    for p in rest_actius:
        count_terms = []
        for d in active_days_by_prof[p]:
            mt, _pmt = _collect_machine_terms_for_day(
                model, x, p, d, rest_specs[d], "soft_month_rest",
                pres_flip=pres_flip,
            )
            count_terms.extend(mt)
        target = rest_targets.get(p, 0)
        if not count_terms and target <= 0:
            continue
        n = max(1, len(count_terms))
        cnt = model.NewIntVar(0, n, f"monthly_rest_count_{p}")
        model.Add(cnt == (sum(count_terms) if count_terms else 0))
        short = model.NewIntVar(0, max(1, target), f"monthly_rest_short_{p}")
        model.Add(short >= target - cnt - presential_tolerance)
        model.Add(short >= 0)
        rest_short_terms.append(short)
        over = model.NewIntVar(0, n, f"monthly_rest_over_{p}")
        model.Add(over >= cnt - target - presential_tolerance)
        model.Add(over >= 0)
        rest_over_terms.append(over)

    rest_ub = max(1, sum(rest_targets.values()) + rest_load)
    total_np_short = model.NewIntVar(0, rest_ub, zeros[0])
    model.Add(
        total_np_short == (sum(rest_short_terms) if rest_short_terms else 0)
    )
    total_np_over = model.NewIntVar(0, rest_ub, zeros[1])
    model.Add(
        total_np_over == (sum(rest_over_terms) if rest_over_terms else 0)
    )
    return total_short, total_over, total_np_short, total_np_over


def _add_weekly_soft_terms(model, x, quota_hard_professionals, unique_days, unique_weeks,
                           week_map, working_map, absent_days_by_prof, keys_by_day,
                           capacity_pct_by, review_slots, planning_rules=None,
                           machine_specs=None, pres_flip=None,
                           presential_tolerance: int = 0,
                           peonada_vars=None, eligibility_df=None):
    """Objectiu tou per setmana × facultatiu: acostar PRES i NP_ord al
    target individual (planning_rules, escalat als dies efectius). Tant
    el shortfall com l'overage es penalitzen, perquè el target és un
    valor EXACTE: si el calendari requereix més PRES dels que els
    targets sumen, el solver paga overage; si en requereix menys, paga
    shortfall.

    `peonada_vars` (opcional): dict {(p, sk): BoolVar}. NP_ord per
    setmana = sum(NP_total) − sum(peonadas en aquella setmana). Així
    les peonades absorbeixen l'excedent de NP fins al cap mensual i
    no contribueixen al recompte d'NP_ord.

    Retorna 4 IntVars amb la suma global:
        (total_pres_shortfall, total_pres_overage,
         total_np_ord_shortfall, total_np_ord_overage)
    """
    rules = planning_rules if planning_rules is not None else PlanningRules.defaults()
    specs = machine_specs if machine_specs is not None else _build_machine_term_specs(keys_by_day, review_slots)
    mode = getattr(rules, "mode", "personalitzat") or "personalitzat"

    def _zero(name):
        v = model.NewIntVar(0, 1, name)
        model.Add(v == 0)
        return v

    # Mode «none»: sense regles d'equilibri setmanal — retorna termes nuls
    # (l'equitat mensual dels trams 3-4 segueix activa).
    if mode == "none":
        return (
            _zero("total_weekly_presential_shortfall"),
            _zero("total_weekly_presential_overage"),
            _zero("total_weekly_np_ord_shortfall"),
            _zero("total_weekly_np_ord_overage"),
        )

    # Modes MENSUALS (presencial/total de tot el mes o activitat concreta):
    # deleguem al helper mensual — cap objectiu per setmana.
    if mode in ("mensual_presencial", "mensual_total", "activitat"):
        return _add_monthly_soft_terms(
            model, x, quota_hard_professionals, unique_days,
            working_map, absent_days_by_prof, keys_by_day, capacity_pct_by,
            specs, mode, rules, pres_flip, presential_tolerance,
            eligibility_df=eligibility_df,
        )

    # Modes automàtics: target per (professional, setmana) derivat de la
    # càrrega real de la setmana (les franges manen; cap taula manual).
    auto_targets: dict = {}
    if mode in ("presencial", "total"):
        auto_targets = weekly_auto_targets(
            mode, quota_hard_professionals, unique_days, unique_weeks,
            week_map, working_map, absent_days_by_prof, capacity_pct_by,
            specs,
        )

    pres_shortfall_terms: list = []
    pres_overage_terms: list = []
    np_shortfall_terms: list = []
    np_overage_terms: list = []

    # Index ràpid: peonadas del facultatiu p en cada dia (per restar-les
    # del recompte NP de la setmana corresponent).
    peonada_by_prof_day: dict = {}
    for (p_pn, sk_pn), pn_var in (peonada_vars or {}).items():
        peonada_by_prof_day.setdefault((p_pn, sk_pn[0]), []).append(pn_var)

    days_by_week: dict = {}
    for d in unique_days:
        days_by_week.setdefault(week_map[d], []).append(d)

    # NOTA: amb el MES NATURAL (1..últim dia), les setmanes al límit del
    # mes poden ser PARCIALS (p.ex. un setembre que comença en dimarts).
    # No cal saltar-les: els targets es dimensionen als dies presents —
    # els modes automàtics reparteixen la càrrega REAL dels dies del
    # fragment, i el mode personalitzat escala per dies efectius
    # (key = min(eff_days, 5)).
    for p in quota_hard_professionals:
        for yw in unique_weeks:
            week_days = days_by_week.get(yw, [])
            active_days = [
                d for d in week_days
                if working_map.get(d, 1) == 1 and d not in absent_days_by_prof[p]
            ]
            if not active_days:
                continue
            eff_days = (sum(capacity_pct_by[(p, d)] for d in active_days) + 99) // 100

            machine_terms = []
            presential_terms = []
            for day in active_days:
                mt, pmt = _collect_machine_terms_for_day(
                    model, x, p, day, specs[day], "soft_week_assign", pres_flip=pres_flip
                )
                machine_terms.extend(mt)
                presential_terms.extend(pmt)

            n_m = max(1, len(machine_terms))
            n_p = max(1, len(presential_terms))
            total_m = model.NewIntVar(0, n_m, f"weekly_machine_soft_{p}_{yw}")
            model.Add(total_m == (sum(machine_terms) if machine_terms else 0))
            total_pres = model.NewIntVar(0, n_p, f"weekly_presential_soft_{p}_{yw}")
            model.Add(total_pres == (sum(presential_terms) if presential_terms else 0))

            week_peonadas = [
                pn for d in active_days
                for pn in peonada_by_prof_day.get((p, d), [])
            ]

            key = min(eff_days, 5)
            if mode == "presencial":
                # AUTO: només es fixa el PRES setmanal (repartiment de la
                # càrrega presencial real); l'NP queda per a l'equitat.
                target_pres = auto_targets.get((p, yw), 0)
                target_total = 0
                target_np_ord = 0
            elif mode == "total":
                # AUTO: es fixa el TOTAL setmanal; la barreja PRES/NP la
                # determinen les franges (cap target presencial propi).
                target_pres = 0
                target_total = auto_targets.get((p, yw), 0)
                target_np_ord = 0
            else:  # personalitzat (taula manual)
                target_total = rules.target_machines.get(key, 0)
                target_pres = rules.target_presential.get(key, 0)
                target_np_ord = max(0, target_total - target_pres)

            # ── Mode «total»: un únic parell shortfall/overage sobre el
            # TOTAL de màquines de la setmana (va al tram 1 via les llistes
            # PRES; el tram 2 queda buit). ──
            if mode == "total":
                tot_short = model.NewIntVar(0, n_m, f"weekly_tot_short_{p}_{yw}")
                model.Add(tot_short >= target_total - total_m - presential_tolerance)
                model.Add(tot_short >= 0)
                pres_shortfall_terms.append(tot_short)
                tot_over = model.NewIntVar(0, n_m, f"weekly_tot_over_{p}_{yw}")
                model.Add(tot_over >= total_m - target_total - presential_tolerance)
                model.Add(tot_over >= 0)
                pres_overage_terms.append(tot_over)
                continue

            # ── PRES: shortfall + overage (target = MÍNIM i MÀXIM exacte) ──
            # La tolerància ε s'aplica simètricament: penalitzem només si
            # |PRES_count − target_pres| > ε. (Mode «total»: mai s'hi arriba
            # — el continue de dalt; mode «presencial»: target automàtic.)
            if target_pres > 0 or presential_terms:
                pres_short = model.NewIntVar(0, n_p, f"weekly_pres_short_{p}_{yw}")
                model.Add(pres_short >= target_pres - total_pres - presential_tolerance)
                model.Add(pres_short >= 0)
                pres_shortfall_terms.append(pres_short)

                pres_over = model.NewIntVar(0, n_p, f"weekly_pres_over_{p}_{yw}")
                model.Add(pres_over >= total_pres - target_pres - presential_tolerance)
                model.Add(pres_over >= 0)
                pres_overage_terms.append(pres_over)

            # ── NP_ord: shortfall + overage, asimètrics respecte a peonades.
            # np_incl = NP TOTAL (total_m − total_pres), comptant peonades:
            #   és el treball NP REAL fet aquella setmana (la persona hi és,
            #   independentment de si es paga com a peonada).
            # np_ord  = np_incl − peonades: NP ORDINARI (sense les peonades).
            #
            #   · SHORTFALL es mesura sobre np_incl: convertir un NP en
            #     peonada NO ha de generar shortfall (el treball NP s'ha fet).
            #     Així les peonades poden reduir les ordinàries CAP AVALL
            #     sense xocar amb el target NP setmanal.
            #   · OVERAGE es mesura sobre np_ord: l'excés d'activitat NP
            #     ORDINÀRIA (per sobre del target) s'ha de pagar com a peonada,
            #     que en reduir np_ord fa baixar l'overage.
            # Mode «presencial»: l'NP setmanal NO es fixa (queda per a
            # l'equitat mensual) — sense aquest guard, el target 0
            # penalitzaria TOTES les NP de la setmana.
            if mode == "personalitzat" and (target_np_ord > 0 or machine_terms):
                np_incl = model.NewIntVar(0, n_m, f"weekly_np_incl_{p}_{yw}")
                model.Add(np_incl == total_m - total_pres)
                np_ord = model.NewIntVar(-n_m, n_m, f"weekly_np_ord_{p}_{yw}")
                if week_peonadas:
                    model.Add(np_ord == np_incl - sum(week_peonadas))
                else:
                    model.Add(np_ord == np_incl)

                np_short = model.NewIntVar(0, n_m, f"weekly_np_short_{p}_{yw}")
                model.Add(np_short >= target_np_ord - np_incl - presential_tolerance)
                model.Add(np_short >= 0)
                np_shortfall_terms.append(np_short)

                np_over = model.NewIntVar(0, n_m, f"weekly_np_over_{p}_{yw}")
                model.Add(np_over >= np_ord - target_np_ord - presential_tolerance)
                model.Add(np_over >= 0)
                np_overage_terms.append(np_over)

    n_prof = max(1, len(quota_hard_professionals))
    n_weeks = max(1, len(unique_weeks))
    ub = max(1, n_prof * n_weeks * 10)
    total_pres_short = model.NewIntVar(0, ub, "total_weekly_presential_shortfall")
    model.Add(total_pres_short == (sum(pres_shortfall_terms) if pres_shortfall_terms else 0))
    total_pres_over = model.NewIntVar(0, ub, "total_weekly_presential_overage")
    model.Add(total_pres_over == (sum(pres_overage_terms) if pres_overage_terms else 0))
    total_np_short = model.NewIntVar(0, ub, "total_weekly_np_ord_shortfall")
    model.Add(total_np_short == (sum(np_shortfall_terms) if np_shortfall_terms else 0))
    total_np_over = model.NewIntVar(0, ub, "total_weekly_np_ord_overage")
    model.Add(total_np_over == (sum(np_overage_terms) if np_overage_terms else 0))
    return total_pres_short, total_pres_over, total_np_short, total_np_over


def _facultatiu_target_num(value):
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _add_facultatiu_targets(model, targets_df, x, slot_keys, review_slots,
                            pres_flip, flippable_keys, unique_weeks, week_map,
                            working_map, absent_days_by_prof, capacity_pct_by,
                            planning_rules, active_professionals):
    """Objectiu tou fort (el fixa l'usuari a Mètriques): per facultatiu i
    SETMANA, acostar les presencialitats i les no-presencials als valors
    editats. El valor és per a una setmana completa; s'escala segons els
    dies efectius de la setmana amb la mateixa forma que el target de
    base (planning_rules). No-presencials = màquines − presencials."""
    if targets_df is None or targets_df.empty:
        z = model.NewIntVar(0, 1, "total_facultatiu_target_penalty")
        model.Add(z == 0)
        return z

    rules = planning_rules if planning_rules is not None else PlanningRules.defaults()
    review = _norm_set(review_slots)
    flip = pres_flip or {}
    flippable = flippable_keys or []
    cols = getattr(targets_df, "columns", [])
    has_np = "target_no_presential" in cols
    base_pres5 = max(1, rules.target_presential.get(5, 3))
    base_mach5 = max(1, rules.target_machines.get(5, 4))
    active = set(active_professionals)

    pres_by_day: dict = {}
    for sk in slot_keys:
        # Els slots de revisió no compten com a presencial al target,
        # encara que el calendari operatiu els tingués amb presentiality=PRES.
        if str(sk[2]).strip().upper() in review:
            continue
        if str(sk[3]).upper() == "PRESENCIAL":
            pres_by_day.setdefault(sk[0], []).append(sk)
    flip_by_day: dict = {}
    for sk in flippable:
        flip_by_day.setdefault(sk[0], []).append(sk)
    mach_by_day: dict = {}
    for sk in slot_keys:
        sid = str(sk[2]).strip().upper()
        if sid not in review and sid not in GUARDS_RESERVED_SLOT_IDS:
            mach_by_day.setdefault(sk[0], []).append(sk)
    days_by_week: dict = {}
    for d, w in week_map.items():
        days_by_week.setdefault(w, []).append(d)

    penalties = []
    ub = 0
    for row in targets_df.itertuples(index=False):
        p = str(row.professional_id).strip().upper()
        if p not in active:
            continue
        tgt_pres = _facultatiu_target_num(row.target_presential)
        tgt_np = _facultatiu_target_num(
            getattr(row, "target_no_presential", None)
        ) if has_np else None
        if tgt_pres is None and tgt_np is None:
            continue
        for yw in unique_weeks:
            adays = [
                d for d in days_by_week.get(yw, [])
                if working_map.get(d, 1) == 1 and d not in absent_days_by_prof.get(p, set())
            ]
            if not adays:
                continue
            eff = (sum(capacity_pct_by.get((p, d), 100) for d in adays) + 99) // 100
            key = min(max(1, eff), 5)
            pres_terms = [
                x[p, sk] for d in adays for sk in pres_by_day.get(d, [])
                if (p, sk) in x
            ]
            pres_terms += [
                flip[(p, sk)] for d in adays for sk in flip_by_day.get(d, [])
                if (p, sk) in flip
            ]
            n_p = max(1, len(pres_terms))
            if tgt_pres is not None and pres_terms:
                tw = max(0, round(
                    tgt_pres * rules.target_presential.get(key, base_pres5) / base_pres5
                ))
                cnt = model.NewIntVar(0, n_p, f"facw_pres_{p}_{yw}")
                model.Add(cnt == sum(pres_terms))
                dev = model.NewIntVar(0, n_p + tw, f"facw_pres_dev_{p}_{yw}")
                model.AddAbsEquality(dev, cnt - tw)
                penalties.append(dev)
                ub += n_p + tw
            if tgt_np is not None:
                mach_terms = [
                    x[p, sk] for d in adays for sk in mach_by_day.get(d, [])
                    if (p, sk) in x
                ]
                if mach_terms:
                    tw = max(0, round(
                        tgt_np * rules.target_machines.get(key, base_mach5) / base_mach5
                    ))
                    n_m = max(1, len(mach_terms))
                    mc = model.NewIntVar(0, n_m, f"facw_m_{p}_{yw}")
                    model.Add(mc == sum(mach_terms))
                    pcv = model.NewIntVar(0, n_m, f"facw_pc_{p}_{yw}")
                    model.Add(pcv == (sum(pres_terms) if pres_terms else 0))
                    npv = model.NewIntVar(0, n_m, f"facw_np_{p}_{yw}")
                    model.Add(npv == mc - pcv)
                    dev = model.NewIntVar(0, n_m + tw, f"facw_np_dev_{p}_{yw}")
                    model.AddAbsEquality(dev, npv - tw)
                    penalties.append(dev)
                    ub += n_m + tw
    total = model.NewIntVar(0, max(1, ub), "total_facultatiu_target_penalty")
    model.Add(total == (sum(penalties) if penalties else 0))
    return total

