"""Equitat/balanç sobre comptadors (presencialitats, no-presencialitats,
màquines ordinàries, dies de treball, TC/RM, revisions). Conjuntament són
les penalitzacions de "spread" entre facultatius actius."""

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.domain.schedule_format import slot_metric_family
from src.solver.normalize import _make_slot_key, _norm_set


def _apportion_by_capacity(total, actius, capacity_pct):
    """Reparteix `total` unitats ENTERES entre `actius` proporcionalment a
    la jornada (`capacity_pct`), amb el mètode del RESIDU MAJOR: la
    diferència d'arrodoniment s'assigna primer als de més jornada
    (round-robin determinista). Retorna {p: int} amb suma == total, o {}
    si no es pot repartir (cap actiu, total ≤ 0 o suma de jornades ≤ 0)."""
    if not actius or total <= 0:
        return {}
    sum_j = sum(max(0, capacity_pct.get(p, 100)) for p in actius)
    if sum_j <= 0:
        return {}
    target = {
        p: int(round(total * max(0, capacity_pct.get(p, 100)) / sum_j))
        for p in actius
    }
    diff = total - sum(target.values())
    ordered = sorted(actius, key=lambda p: -max(0, capacity_pct.get(p, 100)))
    i = 0
    while diff != 0 and ordered:
        p = ordered[i % len(ordered)]
        if diff > 0:
            target[p] += 1
            diff -= 1
        elif target[p] > 0:
            target[p] -= 1
            diff += 1
        i += 1
    return target


def _add_count_balance(model, x, active_professionals, professionals, slot_keys,
                       average_capacity_pct, slot_links=None,
                       prior_counts=None, presentiality_filter="PRESENCIAL",
                       name_prefix="pres", exclude_work_modes=(),
                       extra_terms_by_prof=None, review_slots=None):
    """Helper genèric d'equilibri sobre slots d'una presentialitat concreta.
    Comparteix la lògica entre PRESENCIAL i NO_PRESENCIAL:
      · Col·lapsa parells vinculats (OR per (dia, parell-canònic, work_mode,
        posició)), alineat amb `_collapse_linked` a la UI.
      · Target individual proporcional a la jornada efectiva.
      · Minimitza L1 (suma desviacions) + L∞ (màx desviació) mensual.
      · Si rep `prior_counts` (mesos anteriors), afegeix també L1+L∞ sobre
        el comptador ACUMULAT amb target acumulat proporcional.
      · `extra_terms_by_prof`: dict {prof: [vars]} amb termes addicionals a
        sumar al comptador d'aquell professional (p.ex. flips per a PRES).
    Retorna (l1_mes, counts_per_p, max_var, min_var, linf_mes, target_per_p,
             cum_l1, cum_linf, cum_max, cum_min, cum_target_per_p)."""
    slot_links = slot_links or []
    extra_terms_by_prof = extra_terms_by_prof or {}
    link_partner: dict[str, str] = {}
    for a, b in slot_links:
        au, bu = str(a).strip().upper(), str(b).strip().upper()
        link_partner[au] = bu
        link_partner[bu] = au

    exclude_wm = {str(w).strip().upper() for w in (exclude_work_modes or ())}
    # Defensa: si un slot de revisio acaba al slot_keys amb presentiality
    # PRESENCIAL (cas patològic d'una configuració incorrecta del catàleg),
    # NO ha d'entrar al comptador de presencials. Els slots de revisio
    # estan totalment aïllats del balanç ordinari/presencial.
    review_set = _norm_set(review_slots)
    presential_keys = [
        sk for sk in slot_keys
        if sk[3] == presentiality_filter
        and str(sk[4]).strip().upper() not in exclude_wm
        and str(sk[2]).strip().upper() not in review_set
    ]

    def _group_key(sk):
        sid = str(sk[2]).strip().upper()
        partner = link_partner.get(sid)
        if partner is None:
            return (sk[0], sid, sk[4], sk[5])
        canon = min(sid, partner)
        return (sk[0], "__LINK__", canon, sk[4], sk[5])

    groups: dict = {}
    for sk in presential_keys:
        groups.setdefault(_group_key(sk), []).append(sk)

    extra_max = max((len(v) for v in extra_terms_by_prof.values()), default=0)
    target_base = max(1, len(groups))
    max_p = max(1, len(groups) + extra_max)
    presential_counts = {}
    for p in professionals:
        terms = []
        for gidx, (gkey, gkeys) in enumerate(groups.items()):
            xs = [x[p, sk] for sk in gkeys]
            if len(xs) == 1:
                terms.append(xs[0])
            else:
                g_var = model.NewBoolVar(f"{name_prefix}_group_{p}_{gidx}")
                model.AddMaxEquality(g_var, xs)
                terms.append(g_var)
        terms.extend(extra_terms_by_prof.get(p, []))
        var = model.NewIntVar(0, max_p, f"{name_prefix}_count_{p}")
        model.Add(var == (sum(terms) if terms else 0))
        presential_counts[p] = var

    actius = list(active_professionals)
    target_p = _apportion_by_capacity(target_base, actius, average_capacity_pct)

    devs = {}
    for p in actius:
        tp = target_p.get(p, 0)
        d = model.NewIntVar(0, max_p, f"{name_prefix}_dev_{p}")
        model.Add(d >= presential_counts[p] - tp)
        model.Add(d >= tp - presential_counts[p])
        devs[p] = d

    l1 = model.NewIntVar(0, max_p * max(1, len(actius)), f"{name_prefix}_dev_l1")
    model.Add(l1 == (sum(devs.values()) if devs else 0))
    linf = model.NewIntVar(0, max_p, f"{name_prefix}_dev_linf")
    if devs:
        for d in devs.values():
            model.Add(linf >= d)
    else:
        model.Add(linf == 0)

    max_v = model.NewIntVar(0, max_p, f"max_{name_prefix}")
    min_v = model.NewIntVar(0, max_p, f"min_{name_prefix}")
    if actius:
        active_counts = [presential_counts[p] for p in actius]
        model.AddMaxEquality(max_v, active_counts)
        model.AddMinEquality(min_v, active_counts)
    else:
        model.Add(max_v == 0)
        model.Add(min_v == 0)

    prior = prior_counts or {}
    cum_l1 = model.NewIntVar(0, 1, f"cum_{name_prefix}_dev_l1")
    cum_linf = model.NewIntVar(0, 1, f"cum_{name_prefix}_dev_linf")
    cum_max = model.NewIntVar(0, 1, f"cum_max_{name_prefix}")
    cum_min = model.NewIntVar(0, 1, f"cum_min_{name_prefix}")
    cum_target_by_p: dict = {}
    if actius and prior:
        sum_prior = sum(int(prior.get(p, 0) or 0) for p in actius)
        total_acum = sum_prior + max_p
        ub_acum = max(1, total_acum + 1)
        cumulative = {}
        for p in actius:
            pr = int(prior.get(p, 0) or 0)
            c = model.NewIntVar(0, ub_acum, f"cum_{name_prefix}_{p}")
            model.Add(c == pr + presential_counts[p])
            cumulative[p] = c
        cum_target_by_p = _apportion_by_capacity(total_acum, actius, average_capacity_pct)
        cum_devs = {}
        for p in actius:
            tp = cum_target_by_p.get(p, 0)
            d = model.NewIntVar(0, ub_acum, f"cum_{name_prefix}_dev_{p}")
            model.Add(d >= cumulative[p] - tp)
            model.Add(d >= tp - cumulative[p])
            cum_devs[p] = d
        cum_l1 = model.NewIntVar(0, ub_acum * max(1, len(actius)), f"cum_{name_prefix}_dev_l1")
        model.Add(cum_l1 == (sum(cum_devs.values()) if cum_devs else 0))
        cum_linf = model.NewIntVar(0, ub_acum, f"cum_{name_prefix}_dev_linf")
        for d in cum_devs.values():
            model.Add(cum_linf >= d)
        cum_max = model.NewIntVar(0, ub_acum, f"cum_max_{name_prefix}")
        cum_min = model.NewIntVar(0, ub_acum, f"cum_min_{name_prefix}")
        model.AddMaxEquality(cum_max, list(cumulative.values()))
        model.AddMinEquality(cum_min, list(cumulative.values()))
    else:
        model.Add(cum_l1 == 0)
        model.Add(cum_linf == 0)
        model.Add(cum_max == 0)
        model.Add(cum_min == 0)

    return (l1, presential_counts, max_v, min_v, linf, target_p,
            cum_l1, cum_linf, cum_max, cum_min, cum_target_by_p)


def _add_presentiality_balance(model, x, active_professionals, professionals, slot_keys,
                               slot_rows, average_capacity_pct, pres_flip=None,
                               flippable_keys=None, slot_links=None,
                               prior_presential_counts=None, review_slots=None):
    """Equilibri de PRESENCIALITATS per facultatiu actiu. Vegeu
    `_add_count_balance` per al detall. Inclou els flips PRES com a
    comptador addicional perquè ara muten el schedule final (visibles
    a la UI com a PRES). EXCLOU les revisions (no compten com a
    presencial al balanç ni al target)."""
    pres_flip = pres_flip or {}
    flippable_keys = flippable_keys or []
    extra: dict = {}
    for p in professionals:
        flips_p = [pres_flip[(p, sk)] for sk in flippable_keys if (p, sk) in pres_flip]
        if flips_p:
            extra[p] = flips_p
    return _add_count_balance(
        model, x, active_professionals, professionals, slot_keys,
        average_capacity_pct, slot_links=slot_links,
        prior_counts=prior_presential_counts,
        presentiality_filter="PRESENCIAL",
        name_prefix="pres",
        extra_terms_by_prof=extra,
        review_slots=review_slots,
    )


def _add_ordinary_machine_balance(model, x, active_professionals, professionals, slot_keys,
                               average_capacity_pct, review_slots, slot_links=None,
                               prior_total_counts=None, peonada_vars=None,
                               peonada_target_per_prof=None):
    """Equilibri de MÀQUINES ORDINÀRIES per facultatiu actiu, col·lapsant
    parells vinculats com fa la UI. Inclou PRES + NO_PRES ORDINÀRIA;
    EXCLOU peonades (extraordinàries, decidides pel solver via
    `peonada_vars`), revisions i guàrdies. Comodí (fallback) ha d'estar
    exclòs dels `active_professionals` per absorbir l'excedent. Target
    individual proporcional a la jornada, L1+L∞ mensual + acumulat — igual
    que `_add_presentiality_balance`.

    `peonada_vars` (opcional): dict {(p, sk): BoolVar} amb les peonades
    decidides pel solver (vegeu `_add_peonada_monthly_cap`). Si es passa,
    les peonades NO entren al comptador d'ordinàries: el comptador real
    és (total_machines − peonades_marcades). Així el balanç compara
    NORMAL contra NORMAL, sense que les peonades distorsionin l'spread."""
    slot_links = slot_links or []
    review = _norm_set(review_slots)
    peonada_vars = peonada_vars or {}
    link_partner: dict[str, str] = {}
    for a, b in slot_links:
        au, bu = str(a).strip().upper(), str(b).strip().upper()
        link_partner[au] = bu
        link_partner[bu] = au

    machine_keys = [
        sk for sk in slot_keys
        if str(sk[2]).strip().upper() not in review
        and str(sk[2]).strip().upper() not in GUARDS_RESERVED_SLOT_IDS
        and str(sk[4]).strip().upper() != "PEONADA"
    ]

    def _group_key(sk):
        """Clau canònica del grup per al col·lapse:
          · Vinculats: slot_a i slot_b s'unifiquen en una clau canònica
            (la mateixa per als dos), AMB la mateixa presencialitat.
            Així un facultatiu que té el parell sencer (PRES + PRES)
            compta 1 sola vegada per al balanç.
          · Doblats: les 2 files (PRES + NP) tenen el mateix slot_id i
            posició, però DIFERENT presentiality. Incloent-la a la clau,
            les 2 files queden en grups separats → cada facultatiu
            que les cobreix compta 1 vegada per cada posició.

        Doblat + Vinculat: PRES (del doblat) + partner del link en un grup,
        NP (de l'altra meitat del doblat) en un grup separat. El facultatiu
        del parell linkat compta 1; el del NP doblat compta 1."""
        sid = str(sk[2]).strip().upper()
        pres = str(sk[3]).strip().upper()
        partner = link_partner.get(sid)
        if partner is None:
            return (sk[0], sid, sk[4], sk[5], pres)
        canon = min(sid, partner)
        return (sk[0], "__LINK__", canon, sk[4], sk[5], pres)

    groups: dict = {}
    for sk in machine_keys:
        groups.setdefault(_group_key(sk), []).append(sk)

    # Index ràpid de peonades per facultatiu (per restar-les del comptador).
    peonadas_by_prof: dict = {}
    for (p_pn, sk_pn), pn_var in peonada_vars.items():
        peonadas_by_prof.setdefault(p_pn, []).append(pn_var)

    max_p = max(1, len(groups))
    machine_counts = {}
    for p in professionals:
        terms = []
        for gidx, (gkey, gkeys) in enumerate(groups.items()):
            xs = [x[p, sk] for sk in gkeys]
            if len(xs) == 1:
                terms.append(xs[0])
            else:
                g_var = model.NewBoolVar(f"tot_group_{p}_{gidx}")
                model.AddMaxEquality(g_var, xs)
                terms.append(g_var)
        # Comptador ORDINÀRIES = total grups assignats − peonades del facultatiu.
        # Així el balanç compara nomes les NORMAL: les peonades, que son
        # EXTRA, no distorsionen l'spread (un facultatiu amb 4 normals + 3
        # peonades = 4 ordinaries, no 7).
        total_groups = sum(terms) if terms else 0
        peonadas_p = peonadas_by_prof.get(p, [])
        var = model.NewIntVar(0, max_p, f"tot_count_{p}")
        if peonadas_p:
            model.Add(var == total_groups - sum(peonadas_p))
        else:
            model.Add(var == total_groups)
        machine_counts[p] = var

    actius = list(active_professionals)
    # AJUST DEL TARGET: si restem peonades del comptador (machine_counts),
    # també hem de restar-les del target perquè els dos costats de la
    # comparació siguin coherents. Si no, sum(target) > sum(count_real)
    # i tots els facultatius surten amb deviation > 0 encara que estiguin
    # perfectament equilibrats.
    peonada_target_per_prof = peonada_target_per_prof or {}
    total_expected_peonadas = sum(
        max(0, int(peonada_target_per_prof.get(p, 0))) for p in actius
    )
    target_max_p = max(1, max_p - total_expected_peonadas)
    target_p = _apportion_by_capacity(
        target_max_p if max_p > 0 else 0, actius, average_capacity_pct
    )

    # UNILATERAL (només EXCÉS): penalitzem només machine_counts > target.
    # L'excés d'ordinàries per sobre de la quota justa (proporcional a la
    # jornada) s'ha de convertir en PEONADA (que resta de machine_counts),
    # igualant les ordinàries CAP AVALL. Estar PER SOTA de la quota NO es
    # penalitza: un facultatiu amb poca capacitat (p.ex. només divendres)
    # no es pot apujar, i no volem forçar-li peonades.
    devs = {}
    for p in actius:
        tp = target_p.get(p, 0)
        d = model.NewIntVar(0, max_p, f"tot_dev_{p}")
        model.Add(d >= machine_counts[p] - tp)
        devs[p] = d

    l1 = model.NewIntVar(0, max_p * max(1, len(actius)), "tot_dev_l1")
    model.Add(l1 == (sum(devs.values()) if devs else 0))
    linf = model.NewIntVar(0, max_p, "tot_dev_linf")
    if devs:
        for d in devs.values():
            model.Add(linf >= d)
    else:
        model.Add(linf == 0)

    prior = prior_total_counts or {}
    cum_l1 = model.NewIntVar(0, 1, "cum_tot_dev_l1")
    cum_linf = model.NewIntVar(0, 1, "cum_tot_dev_linf")
    if actius and prior:
        sum_prior = sum(int(prior.get(p, 0) or 0) for p in actius)
        total_acum = sum_prior + max_p
        ub_acum = max(1, total_acum + 1)
        cumulative = {p: model.NewIntVar(0, ub_acum, f"cum_tot_{p}") for p in actius}
        for p in actius:
            model.Add(cumulative[p] == int(prior.get(p, 0) or 0) + machine_counts[p])
        cum_target = _apportion_by_capacity(total_acum, actius, average_capacity_pct)
        # UNILATERAL (mateix criteri que el mensual): només l'excés acumulat
        # per sobre de la quota justa es penalitza i es converteix en peonada.
        cum_devs = {}
        for p in actius:
            tp = cum_target.get(p, 0)
            d = model.NewIntVar(0, ub_acum, f"cum_tot_dev_{p}")
            model.Add(d >= cumulative[p] - tp)
            cum_devs[p] = d
        cum_l1 = model.NewIntVar(0, ub_acum * max(1, len(actius)), "cum_tot_dev_l1")
        model.Add(cum_l1 == (sum(cum_devs.values()) if cum_devs else 0))
        cum_linf = model.NewIntVar(0, ub_acum, "cum_tot_dev_linf")
        for d in cum_devs.values():
            model.Add(cum_linf >= d)
    else:
        model.Add(cum_l1 == 0)
        model.Add(cum_linf == 0)

    return l1, linf, cum_l1, cum_linf, machine_counts, target_p


def _add_tc_rm_balance(model, x, active_professionals, real_professionals, slot_keys,
                       average_capacity_pct, review_slots=None):
    max_p = len(slot_keys)
    max_norm = max_p * 10000
    tc_counts, rm_counts, family_imbalance = {}, {}, {}

    review_set = _norm_set(review_slots)
    tc_family_keys = [
        sk for sk in slot_keys
        if slot_metric_family(sk[2]) == "TC"
        and str(sk[2]).strip().upper() not in review_set
    ]
    rm_family_keys = [
        sk for sk in slot_keys
        if slot_metric_family(sk[2]) == "RM"
        and str(sk[2]).strip().upper() not in review_set
    ]

    for p in real_professionals:
        tc_var = model.NewIntVar(0, max_p, f"tc_count_total_{p}")
        rm_var = model.NewIntVar(0, max_p, f"rm_count_total_{p}")
        diff_var = model.NewIntVar(0, max_p, f"family_diff_total_{p}")
        model.Add(tc_var == sum(x[p, sk] for sk in tc_family_keys))
        model.Add(rm_var == sum(x[p, sk] for sk in rm_family_keys))
        model.AddAbsEquality(diff_var, tc_var - rm_var)
        tc_counts[p] = tc_var
        rm_counts[p] = rm_var
        family_imbalance[p] = diff_var

    norm_tc, norm_rm = {}, {}
    for p in real_professionals:
        cap = max(1, average_capacity_pct.get(p, 100))
        ntc = model.NewIntVar(0, max_norm, f"normalized_tc_{p}")
        nrm = model.NewIntVar(0, max_norm, f"normalized_rm_{p}")
        model.Add(ntc == tc_counts[p] * (10000 // cap))
        model.Add(nrm == rm_counts[p] * (10000 // cap))
        norm_tc[p] = ntc
        norm_rm[p] = nrm

    max_tc = model.NewIntVar(0, max_norm, "max_tc_family")
    min_tc = model.NewIntVar(0, max_norm, "min_tc_family")
    spread_tc = model.NewIntVar(0, max_norm, "spread_tc_family")
    max_rm = model.NewIntVar(0, max_norm, "max_rm_family")
    min_rm = model.NewIntVar(0, max_norm, "min_rm_family")
    spread_rm = model.NewIntVar(0, max_norm, "spread_rm_family")
    for p in active_professionals:
        model.Add(max_tc >= norm_tc[p])
        model.Add(min_tc <= norm_tc[p])
        model.Add(max_rm >= norm_rm[p])
        model.Add(min_rm <= norm_rm[p])
    model.Add(spread_tc == max_tc - min_tc)
    model.Add(spread_rm == max_rm - min_rm)
    return spread_tc, spread_rm, tc_counts, rm_counts, family_imbalance, max_tc, min_tc, max_rm, min_rm


def _add_review_balance(model, x, active_professionals, professionals, slot_rows, slot_keys,
                        review_slots=None):
    """Equitat de revisions SOFT: minimitza l'spread (max−min) de cada
    TIPUS de revisió PER SEPARAT (p.ex. REV_RM pel seu compte i REV_TC pel
    seu) i en suma els resultats.

    Important: és un balanç NOMÉS entre revisions del MATEIX tipus. NO té
    cap relació amb les màquines ordinàries ni amb el balanç TC/RM de
    màquines: agrupem per l'`slot_id` de la revisió, no per família de
    màquina.

    Separar per tipus és clau: si totes les revisions es comptessin
    juntes, una revisió restringida a un sol facultatiu per elegibilitat
    (p.ex. REV_TC només l'pot fer un) deixaria clavat l'spread global i
    neutralitzaria el repartiment de les altres (REV_RM acabaria
    concentrat en un facultatiu).

    Retorna (spread_total, review_counts_per_prof, max_total, min_total);
    els tres últims són sobre el comptador TOTAL de revisions (per a
    l'informe del log/mètriques)."""
    review_set = _norm_set(review_slots)
    review_keys = [
        _make_slot_key(r) for r in slot_rows
        if str(r.slot_id).strip().upper() in review_set
    ]
    max_r = max(1, len(review_keys))
    actius = list(active_professionals)

    # Comptador TOTAL de revisions per facultatiu (per a l'informe).
    review_counts = {}
    for p in professionals:
        rc = model.NewIntVar(0, max_r, f"review_count_{p}")
        model.Add(rc == sum(x[p, sk] for sk in review_keys))
        review_counts[p] = rc

    # Claus agrupades pel TIPUS de revisió (slot_id de la pròpia revisió).
    # NO s'agrupa per família de màquina: cada tipus de revisió s'equilibra
    # pel seu compte.
    keys_by_type: dict[str, list] = {}
    for sk in review_keys:
        keys_by_type.setdefault(str(sk[2]).strip().upper(), []).append(sk)

    # Spread (max−min) INDEPENDENT per tipus de revisió; el total és la suma.
    type_spreads = []
    for rtype, rkeys in keys_by_type.items():
        rmax = max(1, len(rkeys))
        safe = rtype.replace(" ", "_")
        rcounts = []
        for p in actius:
            rc = model.NewIntVar(0, rmax, f"review_{safe}_{p}")
            model.Add(rc == sum(x[p, sk] for sk in rkeys))
            rcounts.append(rc)
        if not rcounts:
            continue
        rmax_v = model.NewIntVar(0, rmax, f"max_review_{safe}")
        rmin_v = model.NewIntVar(0, rmax, f"min_review_{safe}")
        rspread = model.NewIntVar(0, rmax, f"spread_review_{safe}")
        model.AddMaxEquality(rmax_v, rcounts)
        model.AddMinEquality(rmin_v, rcounts)
        model.Add(rspread == rmax_v - rmin_v)
        type_spreads.append(rspread)

    spread = model.NewIntVar(0, max_r, "spread_review_rm")
    model.Add(spread == (sum(type_spreads) if type_spreads else 0))

    # max/min sobre el comptador TOTAL de revisions (per a l'informe).
    max_v = model.NewIntVar(0, max_r, "max_review_rm")
    min_v = model.NewIntVar(0, max_r, "min_review_rm")
    if actius:
        model.AddMaxEquality(max_v, [review_counts[p] for p in actius])
        model.AddMinEquality(min_v, [review_counts[p] for p in actius])
    else:
        model.Add(max_v == 0)
        model.Add(min_v == 0)
    return spread, review_counts, max_v, min_v
