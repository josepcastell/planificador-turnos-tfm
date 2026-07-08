"""Penalitzacions diverses: ús del comodí, cap de peonades, preferències de
comitè, teletreball post-guàrdia, elegibilitat tova i estabilitat respecte
a la solució anterior."""

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.domain.schedule_format import slot_comite_family
from src.solver.normalize import _norm_set


def _add_fallback_usage_penalty(model, x, fallback_professionals, slot_keys, review_slots):
    """Soft: penalitza cada assignació de màquina al comodí (TLD/fallback).
    Així el sobrant l'absorbeixen primer els facultatius regulars i el
    comodí queda com a últim recurs. No es prohibeix (cobertura dura)."""
    fb = set(fallback_professionals or ())
    if not fb:
        zero = model.NewIntVar(0, 1, "total_tld_usage")
        model.Add(zero == 0)
        return zero
    eligible_sk = [
        sk for sk in slot_keys
        if sk[2] not in review_slots and str(sk[2]).upper() not in GUARDS_RESERVED_SLOT_IDS
    ]
    terms = [x[p, sk] for p in fb for sk in eligible_sk if (p, sk) in x]
    total = model.NewIntVar(0, max(1, len(terms)), "total_tld_usage")
    model.Add(total == (sum(terms) if terms else 0))
    return total


def _add_comite_preferred_machine_terms(model, x, slot_keys, professionals,
                                        comite_entries, review_slots=None):
    """Soft, 3 nivells de preferència el dia de comitè (millor → pitjor):
      1) PRESENCIAL a la localització (àrea) del comitè      → penalització 0
      2) té màquina però no presencial a la localització     → penalització 1
      3) cap màquina aquell dia                              → penalització 3
    Totalment tou: no hi ha cap restricció dura."""
    if not comite_entries:
        total = model.NewIntVar(0, 1, "total_comite_pref_miss")
        model.Add(total == 0)
        return total

    review = _norm_set(review_slots)
    professional_set = set(professionals)
    # PRESENCIAL a la localització del comitè (família == comite_type).
    pres_loc_by_day: dict[tuple[str, str], list] = {}
    # Qualsevol màquina (ni revisió ni guàrdia), per dia.
    machine_by_day: dict[str, list] = {}
    for sk in slot_keys:
        slot_id = str(sk[2])
        if slot_id.upper() in review or slot_id.upper() in GUARDS_RESERVED_SLOT_IDS:
            continue
        machine_by_day.setdefault(sk[0], []).append(sk)
        if str(sk[3]).upper() == "PRESENCIAL":
            fam = slot_comite_family(slot_id)
            if fam:  # qualsevol àrea definida per l'usuari
                pres_loc_by_day.setdefault((sk[0], fam), []).append(sk)

    coef_no_presloc = 1   # té màquina però no presencial a la localització
    coef_no_machine = 2   # cap màquina (acumulat → 3 si tampoc presencial@loc)
    terms = []
    ub = 0
    for professional_id, day_str, comite_type in comite_entries:
        if professional_id not in professional_set:
            continue
        machines = [
            sk for sk in machine_by_day.get(day_str, [])
            if (professional_id, sk) in x
        ]
        if not machines:
            continue
        presloc = [
            sk for sk in pres_loc_by_day.get((day_str, comite_type), [])
            if (professional_id, sk) in x
        ]
        has_presloc = model.NewBoolVar(
            f"comite_presloc_{professional_id}_{day_str}_{comite_type}"
        )
        if presloc:
            model.AddMaxEquality(has_presloc, [x[professional_id, sk] for sk in presloc])
        else:
            model.Add(has_presloc == 0)
        has_machine = model.NewBoolVar(
            f"comite_hasmachine_{professional_id}_{day_str}"
        )
        model.AddMaxEquality(has_machine, [x[professional_id, sk] for sk in machines])
        terms.append(coef_no_presloc * (1 - has_presloc))
        terms.append(coef_no_machine * (1 - has_machine))
        ub += coef_no_presloc + coef_no_machine

    total = model.NewIntVar(0, max(1, ub), "total_comite_pref_miss")
    model.Add(total == (sum(terms) if terms else 0))
    return total


def _add_guard_morning_telework_terms(model, x, slot_keys, guard_prof_days, review_slots):
    """Soft: el dia de guàrdia, PRIORITZAR que el facultatiu cobreixi una
    màquina NO_PRESENCIAL ordinària al MATÍ (teletreball: la tarda i la nit
    estan bloquejades per la guàrdia). Penalitza no aconseguir-ho. No es
    força: si no hi ha cap màquina NP possible aquell matí per a aquell
    facultatiu, la penalització simplement no s'aplica."""
    if not guard_prof_days:
        total = model.NewIntVar(0, 1, "total_guard_morning_miss")
        model.Add(total == 0)
        return total

    morning_np_by_day: dict[str, list] = {}
    for sk in slot_keys:
        if sk[1] != "MATI" or str(sk[3]).upper() != "NO_PRESENCIAL":
            continue
        if str(sk[4]).upper() != "NORMAL":
            continue
        slot_id = str(sk[2])
        if slot_id in review_slots or slot_id.upper() in GUARDS_RESERVED_SLOT_IDS:
            continue
        morning_np_by_day.setdefault(sk[0], []).append(sk)

    terms = []
    for professional_id, day_str in guard_prof_days:
        cand = [
            sk for sk in morning_np_by_day.get(day_str, [])
            if (professional_id, sk) in x
        ]
        if not cand:
            continue
        has = model.NewBoolVar(f"guard_np_morning_{professional_id}_{day_str}")
        model.AddMaxEquality(has, [x[professional_id, sk] for sk in cand])
        miss = model.NewBoolVar(f"guard_np_morning_miss_{professional_id}_{day_str}")
        model.Add(miss == 1 - has)
        terms.append(miss)

    total = model.NewIntVar(0, max(1, len(terms)), "total_guard_morning_miss")
    model.Add(total == (sum(terms) if terms else 0))
    return total


def _add_eligibility_soft(model, x, professionals, slot_keys, eligibility_df,
                          fallback_professionals=None):
    """Soft (amb pes molt alt): penalitza assignar un facultatiu NO
    elegible a un slot. Es deixa com a soft (no com a x==0) perquè, si
    les dades d'elegibilitat estan incompletes o hi ha un cas extrem
    sense cap elegible, el solver doni una solució (amb cost altíssim)
    en comptes de fallar.

    El comodí (fallback/TLD) s'assigna SENSE elegibilitat: és el recurs
    universal (cobreix qualsevol slot com a últim recurs), així que mai
    se'l penalitza — equival a treure'l de la llista d'elegibilitat."""
    fb = {str(p).strip().upper() for p in (fallback_professionals or set())}
    if eligibility_df is None or eligibility_df.empty:
        z = model.NewIntVar(0, 1, "total_eligibility_penalty")
        model.Add(z == 0)
        return z
    allowed_map: dict[tuple[str, str], int] = {}
    for r in eligibility_df.itertuples(index=False):
        try:
            allowed = int(float(getattr(r, "allowed", 0)))
        except (TypeError, ValueError):
            allowed = 0
        allowed_map[(getattr(r, "professional_id"), getattr(r, "slot_id"))] = allowed
    terms = []
    for p in professionals:
        if str(p).strip().upper() in fb:
            continue
        for sk in slot_keys:
            if allowed_map.get((p, sk[2]), 1) == 0 and (p, sk) in x:
                terms.append(x[p, sk])
    total = model.NewIntVar(0, max(1, len(terms)), "total_eligibility_penalty")
    model.Add(total == (sum(terms) if terms else 0))
    return total


def _add_stability_terms(model, x, stable_assignment_by_slot):
    changes = []
    for sk, professional in stable_assignment_by_slot.items():
        changed = model.NewBoolVar(
            f"changed_from_previous_{professional}_{sk[0]}_{sk[1]}_{sk[2]}"
        )
        model.Add(changed == 1 - x[professional, sk])
        changes.append(changed)
    total = model.NewIntVar(0, max(1, len(changes)), "total_stability_changes")
    model.Add(total == (sum(changes) if changes else 0))
    return total


def _add_no_pres_weekday_soft(model, x, slot_keys, no_pres_weekday_map,
                               review_slots=None):
    """Soft: penalitza les assignacions PRESENCIALS al facultatiu en
    dies de la setmana marcats com a NP-only (no_pres_weekdays). Les
    revisions queden fora (no compten com a presencial ordinari): un
    facultatiu amb dilluns NP-only pot fer una revisió PRES dilluns.

    `no_pres_weekday_map`: dict {professional_id: set(day_str)} amb els
    dies concrets on cada facultatiu NO hauria de fer PRES.

    El comodí (TLD) també hi entra: si l'usuari el marca, es respecta
    la mateixa lògica. Generalment el TLD ja té presence_mode=NP per
    defecte, així que aquesta restricció hi és redundant.
    """
    return _add_presentiality_weekday_soft(
        model, x, slot_keys, no_pres_weekday_map,
        forbidden_presentiality="PRESENCIAL",
        var_name="total_no_pres_weekday_violation",
        review_slots=review_slots,
    )


def _add_pres_weekday_soft(model, x, slot_keys, pres_weekday_map,
                           review_slots=None):
    """Soft simètric: penalitza les assignacions NO_PRESENCIALS al
    facultatiu en dies de la setmana marcats com a PRES-only
    (pres_weekdays). Les revisions queden fora.

    `pres_weekday_map`: dict {professional_id: set(day_str)} amb els
    dies concrets on cada facultatiu NO hauria de fer NP."""
    return _add_presentiality_weekday_soft(
        model, x, slot_keys, pres_weekday_map,
        forbidden_presentiality="NO_PRESENCIAL",
        var_name="total_pres_weekday_violation",
        review_slots=review_slots,
    )


def _add_presentiality_weekday_soft(model, x, slot_keys, weekday_map,
                                     forbidden_presentiality: str,
                                     var_name: str,
                                     review_slots=None):
    """Patró compartit: penalitza assignacions amb la presentiality
    `forbidden_presentiality` al facultatiu en dies marcats al mapa.
    Revisions excloses."""
    if not weekday_map:
        zero = model.NewIntVar(0, 1, var_name)
        model.Add(zero == 0)
        return zero
    review_set = _norm_set(review_slots)
    forbidden = str(forbidden_presentiality).upper()
    terms = []
    for sk in slot_keys:
        if str(sk[3]).upper() != forbidden:
            continue
        if str(sk[2]).strip().upper() in review_set:
            continue
        day_str = str(sk[0])
        for p, days in weekday_map.items():
            if day_str in days and (p, sk) in x:
                terms.append(x[p, sk])
    total = model.NewIntVar(0, max(1, len(terms)), var_name)
    model.Add(total == (sum(terms) if terms else 0))
    return total
