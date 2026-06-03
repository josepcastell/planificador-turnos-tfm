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


def _add_weekly_soft_terms(model, x, quota_hard_professionals, unique_days, unique_weeks,
                           week_map, working_map, absent_days_by_prof, keys_by_day,
                           capacity_pct_by, review_slots, planning_rules=None,
                           machine_specs=None, pres_flip=None,
                           presential_tolerance: int = 0,
                           peonada_vars=None):
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

    # NOTA: ja no cal saltar partial weeks al límit del mes. La filtració
    # `filter_module_to_month` ara segueix la regla "una setmana pertany
    # al mes del seu DILLUNS", per la qual cada setmana ISO viu sencera
    # en un solve i no es trenca. Així el target setmanal s'aplica
    # sempre a setmanes completes (5 dies Mon-Fri).
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
            target_total = rules.target_machines.get(key, 0)
            target_pres = rules.target_presential.get(key, 0)
            target_np_ord = max(0, target_total - target_pres)

            # ── PRES: shortfall + overage (target = MÍNIM i MÀXIM exacte) ──
            # La tolerància ε s'aplica simètricament: penalitzem només si
            # |PRES_count − target_pres| > ε.
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
            if target_np_ord > 0 or machine_terms:
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

