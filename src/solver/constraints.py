"""Hard constraints (coverage, eligibility, daily/weekly limits, coupling)."""

import datetime as _dt

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS, WEEKDAY_CODES
from src.domain.planning_rules import PlanningRules
from src.solver.normalize import _make_slot_key, _norm_set
from src.solver.preprocessing import _matching_preassignment_keys


def _weekday_code(day_str) -> str:
    """Codi de dia-setmana (MONDAY..SUNDAY) d'una data ISO; '' si no és vàlida.
    S'usa per aplicar les vinculacions PER (dia-setmana, franja)."""
    try:
        return WEEKDAY_CODES[_dt.date.fromisoformat(str(day_str)).weekday()]
    except (ValueError, TypeError):
        return ""


def _links_for_daykey(links_by_wf, weekday_code, franja):
    """Parelles vinculades que apliquen a un (dia-setmana, franja) concret.
    Inclou les específiques d'aquell dia/franja i les GLOBALS (clau ('', ''),
    p.ex. vinculacions legacy del catàleg que apliquen a tot arreu)."""
    if not links_by_wf:
        return []
    out = list(links_by_wf.get((weekday_code, franja), ()))
    out += list(links_by_wf.get(("", ""), ()))
    return out


def _links_for_weekday(links_by_wf, weekday_code):
    """Totes les parelles vinculades d'un dia-setmana (qualsevol franja) + les
    globals. Per al COMPTATGE d'equitat, que és per dia (no per franja)."""
    if not links_by_wf:
        return []
    out = []
    for (lwd, _lfr), pairs in links_by_wf.items():
        if lwd == weekday_code or lwd == "":
            out.extend(pairs)
    return out


def _build_decision_variables(model, professionals, slot_keys):
    x = {}
    for p in professionals:
        for sk in slot_keys:
            day, franja, slot_id, presentiality, work_mode, position = sk
            var_name = (
                f"x_{p}_{day}_{franja}_{slot_id}_{presentiality}_{work_mode}_{position}"
                .replace("-", "_").replace(" ", "_")
            )
            x[p, sk] = model.NewBoolVar(var_name)
    return x


def _representative_key(keys):
    """Slot_key representatiu d'un grup: prioritza PRESENCIAL i la posició
    més baixa. Permet vincular slots encara que estiguin doblats (la posició
    extra NO_PRESENCIAL del doblat queda lliure per a un altre facultatiu)."""
    if not keys:
        return None
    return sorted(
        keys,
        key=lambda sk: (0 if str(sk[3]).upper() == "PRESENCIAL" else 1, int(sk[5])),
    )[0]


def _build_machine_term_specs(
    keys_by_day, review_slots, links_by_wf=None,
    secondary_slot_ids=None,
):
    """Pre-compute, for each day, the slot_keys that contribute to machine terms.

    Independent of professional: same structure for all P. Used by
    _collect_machine_terms_for_day to avoid re-filtering day_keys per (p, day).

    links_by_wf: dict {(weekday_code, franja): [(slot_a, slot_b), ...]} amb les
    parelles vinculades PER dia-setmana i franja (clau ('', '') = globals). Els
    slots d'una parella es compten com una sola màquina el dia que hi són
    vinculats.

    secondary_slot_ids: conjunt d'slot_ids marcats com a "màquina
    secundària" (apareixen al `linked_to` d'una altra fila al catàleg).
    Aquests slots queden COBERTS però NO COMPTEN als objectius setmanals
    d'equilibri: no entren a `machine_keys`, `presential_machine_keys`
    ni `flippable_machine_keys`. La instància principal del par linked
    sí compta (via `coupling_keys`).

    IMPORTANT: si un slot linked està DOBLAT (p.ex. TC3 amb 2 instàncies
    PRES + NP el mateix dia), només la instància REPRESENTATIVA (PRES amb
    posició més baixa) entra al coupling. Les instàncies extres (NP
    doblades) — si NO són secundàries — tornen al flow normal i queden
    al pool `flippable_machine_keys`."""
    secondary_set = _norm_set(secondary_slot_ids)
    specs = {}
    for day, day_keys in keys_by_day.items():
        # Parelles vinculades que apliquen a AQUEST dia (per dia-setmana).
        link_pairs = _links_for_weekday(links_by_wf, _weekday_code(day))
        coupling_keys: list = []
        uncoupled_linked: list = []
        # Set d'slot_keys que ja s'han contat com a part d'un par linked
        # (representatius). La resta queda fora del coupling i va al flow
        # normal a sota.
        coupled_slot_keys: set = set()
        for slot_a, slot_b in link_pairs:
            a_keys = [sk for sk in day_keys if sk[2] == slot_a and sk[4] != "PEONADA"]
            b_keys = [sk for sk in day_keys if sk[2] == slot_b and sk[4] != "PEONADA"]
            if a_keys and b_keys:
                rep_a = _representative_key(a_keys)
                rep_b = _representative_key(b_keys)
                # Només els representatius entren al coupling (els enllaça
                # `_add_structural_coupling`). La resta d'instàncies queden
                # lliures (doblades).
                coupling_keys.extend([rep_a, rep_b])
                coupled_slot_keys.update([rep_a, rep_b])
            else:
                uncoupled_linked.extend(a_keys + b_keys)

        machine_keys = []
        presential_machine_keys = []
        flippable_machine_keys = []
        for sk in day_keys:
            if sk in coupled_slot_keys:
                continue  # ja contat al coupling
            slot_id, presentiality = sk[2], sk[3]
            if slot_id in review_slots:
                continue
            # Compta com a màquina qualsevol slot que no sigui de revisió ni
            # de guàrdia. La peonada (work_mode del template) també compta a
            # l'equilibri setmanal. Sense llista hardcoded.
            if str(slot_id).upper() in GUARDS_RESERVED_SLOT_IDS:
                continue
            # Màquines SECUNDÀRIES (linked_to d'una altra fila): cobertes
            # però NO compten als objectius setmanals d'equilibri.
            if str(slot_id).strip().upper() in secondary_set:
                continue
            machine_keys.append(sk)
            if presentiality == "PRESENCIAL":
                presential_machine_keys.append(sk)
            # Slots NO_PRESENCIAL ordinaris (NORMAL): el solver els pot
            # "flipar" a presencial per arribar al target presencial.
            elif str(sk[4]).upper() == "NORMAL":
                flippable_machine_keys.append(sk)

        specs[day] = (
            coupling_keys, uncoupled_linked, machine_keys,
            presential_machine_keys, flippable_machine_keys,
        )
    return specs


def _collect_machine_terms_for_day(model, x, p, day, day_spec, prefix, pres_flip=None):
    """Return (machine_terms, presential_machine_terms) for one professional+day.

    Els slots vinculats (linked_to del catàleg) compten com una sola
    màquina. PEONADA i slots de revisió queden exclosos. Un slot
    NO_PRESENCIAL ordinari "flipat" (pres_flip[(p,sk)]==1) compta com a
    presencial. Tot es deriva del catàleg; no depèn de cap nom d'slot.
    """
    (coupling_keys, uncoupled_linked_keys, machine_keys,
     presential_machine_keys, flippable_machine_keys) = day_spec
    pres_flip = pres_flip or {}
    machine_terms = []
    presential_machine_terms = []

    if coupling_keys:
        coupled = model.NewBoolVar(f"{prefix}_urg_tc4_{p}_{day}")
        model.AddMaxEquality(coupled, [x[p, sk] for sk in coupling_keys])
        machine_terms.append(coupled)
        presential_machine_terms.append(coupled)
    else:
        for sk in uncoupled_linked_keys:
            machine_terms.append(x[p, sk])
            presential_machine_terms.append(x[p, sk])

    for sk in machine_keys:
        machine_terms.append(x[p, sk])
    for sk in presential_machine_keys:
        presential_machine_terms.append(x[p, sk])
    for sk in flippable_machine_keys:
        fv = pres_flip.get((p, sk))
        if fv is not None:
            presential_machine_terms.append(fv)

    return machine_terms, presential_machine_terms


def _add_coverage_constraints(model, x, professionals, slot_keys,
                              unlimited_professionals=None,
                              optional_slot_keys=None):
    """Cobertura HARD:
      - Cada slot_key (instància) s'ha d'assignar exactament a 1 facultatiu.
        Excepció: les claus a `optional_slot_keys` admeten `<= 1`
        (poden quedar sense assignar — pos2 condicional del doblat
        per facultatiu).
      - Doblat (mateix (dia, franja, slot_id) amb múltiples positions o
        presentialities): cap facultatiu regular pot ocupar més d'una
        instància → els slots doblats van a facultatius DIFERENTS. El
        TLD (unlimited) està exempt d'aquest cap.
    """
    unlimited = set(unlimited_professionals or ())
    optional = set(optional_slot_keys or ())
    # Group key (day, franja, slot_id): junta TOTES les instàncies del
    # mateix slot el mateix dia-franja, inclosos doblats PRES+NP (que
    # tenen presentiality diferent però són la "mateixa màquina física").
    keys_by_slot: dict[tuple, list] = {}
    for sk in slot_keys:
        keys_by_slot.setdefault((sk[0], sk[1], sk[2]), []).append(sk)
    for sk in slot_keys:
        if sk in optional:
            # Pos2 condicional: pot quedar sense assignar.
            model.Add(sum(x[p, sk] for p in professionals) <= 1)
        else:
            model.Add(sum(x[p, sk] for p in professionals) == 1)
    duplicated_groups = [g for g in keys_by_slot.values() if len(g) > 1]
    for p in professionals:
        if p in unlimited:  # TLD: sense límit (pot agafar instàncies de més)
            continue
        for group_keys in duplicated_groups:
            model.Add(sum(x[p, sk] for sk in group_keys) <= 1)


def _add_conditional_doubling_constraints(
    model, x, professionals, slot_keys,
    marked_profs_by_slot_id: dict,
    conditional_pos2_keys: set,
):
    """Doblat condicional per facultatiu: per cada slot_id marcat per
    algun facultatiu (`doubled_machines`), la posició 2 del calendari
    (afegida a `build_weekday_calendar_from_templates`) queda
    OBLIGATÒRIA si i només si almenys un dels facultatius marcats està
    assignat al slot (pos1 O pos2 del mateix (dia, franja, slot_id)).

    Formulació:
      `pos2_filled = sum(x[p, sk_pos2] for p)`     (binari: 0/1 perquè
        coverage és <= 1 per a slots opcionals)
      `marked_at_slot = sum(x[m, sk] for m in marked, sk in all_keys
        del slot)`
      Constraints:
        - `pos2_filled <= marked_at_slot`
          (pos2 filled → almenys 1 marcat present)
        - `marked_at_slot <= UB_marked * pos2_filled`
          (marcat present → pos2 filled, on UB_marked = #marcats * #keys)
    """
    if not conditional_pos2_keys or not marked_profs_by_slot_id:
        return
    # Indexa slot_keys per (day, franja, slot_id).
    keys_by_slot: dict[tuple, list] = {}
    for sk in slot_keys:
        keys_by_slot.setdefault((sk[0], sk[1], sk[2]), []).append(sk)

    # Agrupa les pos2 condicionals per (day, franja, slot_id).
    pos2_by_slot: dict[tuple, list] = {}
    for sk in conditional_pos2_keys:
        pos2_by_slot.setdefault((sk[0], sk[1], sk[2]), []).append(sk)

    for (day, franja, sid), pos2_keys in pos2_by_slot.items():
        marked = marked_profs_by_slot_id.get(str(sid).strip().upper(), set())
        if not marked:
            continue
        all_keys = keys_by_slot.get((day, franja, sid), [])
        if not all_keys:
            continue
        # pos2_filled (només per professionals reals; el TLD pot ocupar
        # múltiples instàncies — el incloem per cobrir tots els casos).
        pos2_filled_terms = [
            x[p, sk] for p in professionals for sk in pos2_keys
            if (p, sk) in x
        ]
        marked_terms = [
            x[m, sk] for m in marked for sk in all_keys
            if (m, sk) in x
        ]
        if not pos2_filled_terms or not marked_terms:
            continue
        ub_marked = max(1, len(marked_terms))
        pos2_filled = model.NewIntVar(
            0, len(pos2_filled_terms),
            f"pos2_filled_{day}_{franja}_{sid}".replace("-", "_").replace(" ", "_"),
        )
        model.Add(pos2_filled == sum(pos2_filled_terms))
        marked_sum = model.NewIntVar(
            0, ub_marked,
            f"marked_at_{day}_{franja}_{sid}".replace("-", "_").replace(" ", "_"),
        )
        model.Add(marked_sum == sum(marked_terms))
        # pos2 filled → marcat present
        model.Add(pos2_filled <= marked_sum)
        # marcat present → pos2 filled (amplificat per ub_marked perquè
        # marcat pot ser >=1 i pos2_filled binari)
        model.Add(marked_sum <= ub_marked * pos2_filled)


def _add_daily_compat_constraints(model, x, professionals, slot_rows, unique_days, review_slots,
                                  slot_links=None, unlimited_professionals=None,
                                  pres_flip=None):
    """Màxim 1 màquina per facultatiu i franja (presencial O no presencial:
    ningú pot estar a dues màquines el mateix matí/tarda) i màxim 1 slot
    PRESENCIAL per facultatiu i dia.

    Els slots vinculats (slot_links) compten com una sola màquina quan tots
    dos tenen instància a la mateixa franja. Els slots de revisió no compten
    ni tenen límit per dia. Els facultatius 'unlimited' (TLD/telediagnòstic
    remot) no tenen aquests límits.
    """
    unlimited = set(unlimited_professionals or ())
    link_pairs = list(slot_links or [])
    linked_slot_ids = {s for pair in link_pairs for s in pair}
    rows_by_day: dict[str, list] = {}
    for r in slot_rows:
        rows_by_day.setdefault(str(r.day), []).append(r)
    for p in professionals:
        if p in unlimited:
            continue
        for day in unique_days:
            day_rows = rows_by_day.get(day, [])
            for franja in ["MATI", "TARDA"]:
                franja_rows = [
                    r for r in day_rows
                    if str(r.franja) == franja
                    and str(r.slot_id) not in review_slots
                ]
                slot_terms = []
                for slot_a, slot_b in link_pairs:
                    pair_rows = [r for r in franja_rows if str(r.slot_id) in {slot_a, slot_b}]
                    if pair_rows:
                        coupled = model.NewBoolVar(
                            f"slot_link_{slot_a}_{slot_b}_{p}_{day}_{franja}"
                        )
                        model.AddMaxEquality(coupled, [x[p, _make_slot_key(r)] for r in pair_rows])
                        slot_terms.append(coupled)
                for row in franja_rows:
                    if str(row.slot_id) not in linked_slot_ids:
                        slot_terms.append(x[p, _make_slot_key(row)])
                if slot_terms:
                    model.Add(sum(slot_terms) <= 1)

            # Màxim 1 slot PRESENCIAL per dia i facultatiu (els vinculats
            # compten com una sola màquina). El comodí (unlimited) ja està
            # exclòs al principi del bucle.
            #
            # EXCEPCIÓ: les màquines NIT NO entren al cap diari. La nit és
            # un torn diferent que pot coexistir amb una màquina diürna
            # (matí/tarda) sense violar el límit d'1 presencial/dia. Així,
            # PRES MATI + PRES NIT al mateix dia és factible.
            day_rows_no_nit = [
                r for r in day_rows
                if str(getattr(r, "franja", "")).upper() != "NIT"
            ]
            counted_linked = set()
            pres_terms = []
            for slot_a, slot_b in link_pairs:
                pair_keys = [
                    _make_slot_key(r) for r in day_rows_no_nit
                    if str(r.slot_id) in {slot_a, slot_b}
                    and str(r.slot_id) not in review_slots
                    and str(getattr(r, "presentiality", "")).upper() == "PRESENCIAL"
                ]
                if pair_keys:
                    coupled = model.NewBoolVar(f"day_pres_link_{slot_a}_{slot_b}_{p}_{day}")
                    model.AddMaxEquality(coupled, [x[p, sk] for sk in pair_keys])
                    pres_terms.append(coupled)
                    counted_linked.update({slot_a, slot_b})
            for r in day_rows_no_nit:
                if str(r.slot_id) in review_slots or str(r.slot_id) in counted_linked:
                    continue
                pres = str(getattr(r, "presentiality", "")).upper()
                sk = _make_slot_key(r)
                if pres == "PRESENCIAL":
                    pres_terms.append(x[p, sk])
                elif pres_flip is not None and (p, sk) in pres_flip:
                    # Un no-presencial ordinari flipat compta com presencial.
                    pres_terms.append(pres_flip[(p, sk)])
            if len(pres_terms) > 1:
                model.Add(sum(pres_terms) <= 1)


def _add_fallback_eligibility_hard(model, x, fallback_professionals, slot_keys,
                                    eligibility_df):
    """Restricció DURA: el comodí (TLD/fallback) no pot cobrir un slot
    on l'usuari ha posat `allowed=0` al mapa d'elegibilitat.

    Per defecte, el comodí està exempt de l'elegibilitat (és el recurs
    universal — vegeu `_add_eligibility_soft`). Aquesta funció afegeix
    EXCEPCIONS estrictes: si l'usuari diu explícitament que TLD NO pot
    fer un slot concret, el solver el respecta.

    Risc: si cap altre facultatiu regular és elegible per a un slot i
    TLD està marcat com a no elegible, el model és infactible. Pertany
    a l'usuari assegurar que sempre hi ha un regular elegible per als
    slots on TLD està marcat com a no-elegible."""
    if eligibility_df is None or eligibility_df.empty:
        return
    fb = {str(p).strip().upper() for p in (fallback_professionals or set())}
    if not fb:
        return
    allowed_map: dict[tuple[str, str], int] = {}
    for r in eligibility_df.itertuples(index=False):
        try:
            allowed = int(float(getattr(r, "allowed", 0)))
        except (TypeError, ValueError):
            allowed = 0
        p_upper = str(getattr(r, "professional_id", "")).strip().upper()
        s_upper = str(getattr(r, "slot_id", "")).strip().upper()
        if p_upper and s_upper:
            allowed_map[(p_upper, s_upper)] = allowed
    for p in fallback_professionals:
        p_upper = str(p).strip().upper()
        if p_upper not in fb:
            continue
        for sk in slot_keys:
            slot_id_upper = str(sk[2]).strip().upper()
            if allowed_map.get((p_upper, slot_id_upper), 1) == 0:
                if (p, sk) in x:
                    model.Add(x[p, sk] == 0)


def _add_unavailability_constraints(model, x, slot_keys, unavailability_df, keys_by_day=None):
    if unavailability_df.empty:
        return

    required = {"professional_id", "day"}
    missing = required - set(unavailability_df.columns)
    if missing:
        raise ValueError(
            f"Unavailability missing required columns: {', '.join(sorted(missing))}"
        )

    if keys_by_day is None:
        keys_by_day = {}
        for sk in slot_keys:
            keys_by_day.setdefault(sk[0], []).append(sk)

    def _norm(value) -> str:
        # NaN/None/cadena buida → "" (cap filtre per franja/presencialitat,
        # bloqueig de dia sencer). 'nan' literal o blancs també → "".
        if value is None:
            return ""
        if isinstance(value, float) and value != value:  # NaN
            return ""
        s = str(value).strip().upper()
        return "" if s in ("", "NAN", "NONE") else s

    has_franja = "franja" in unavailability_df.columns
    has_presentiality = "presentiality" in unavailability_df.columns
    for row in unavailability_df.itertuples(index=False):
        day_keys = keys_by_day.get(str(row.day))
        if not day_keys:
            continue
        franja = _norm(getattr(row, "franja", "")) if has_franja else ""
        presentiality = _norm(getattr(row, "presentiality", "")) if has_presentiality else ""
        if franja:
            day_keys = [sk for sk in day_keys if sk[1] == franja]
        if presentiality:
            day_keys = [sk for sk in day_keys if sk[3] == presentiality]
        if not day_keys:
            continue
        for sk in day_keys:
            if (row.professional_id, sk) not in x:
                continue
            model.Add(x[row.professional_id, sk] == 0)


def _add_presence_mode_constraints(model, x, slot_keys, presence_mode_by_prof,
                                    review_slots=None):
    """Hard: si un facultatiu té presence_mode='PRESENCIAL' no se li pot
    assignar cap slot NO_PRESENCIAL, i viceversa. Buit/absent = sense
    restricció (pot fer les dues). Útil per al comodí (TLD) que només fa
    activitat no presencial.

    Les **revisions** queden FORA d'aquesta restricció: són una
    categoria especial (no compten com a presencial ni com a no-
    presencial ordinaris) i la seva continuïtat (`_add_review_continuity`)
    o assignació fixa al catàleg ha de poder-se complir encara que el
    facultatiu tingui presence_mode oposat al `presentiality` que el
    catàleg li hagi posat. Sense aquesta exempció, una revisió NP
    assignada a un facultatiu PRES-only (o viceversa) faria infactible
    el model."""
    if not presence_mode_by_prof:
        return
    review_set = _norm_set(review_slots)
    for p, mode in presence_mode_by_prof.items():
        for sk in slot_keys:
            if (p, sk) not in x:
                continue
            if str(sk[2]).strip().upper() in review_set:
                continue
            if str(sk[3]).upper() != mode:
                model.Add(x[p, sk] == 0)


def _add_structural_coupling(model, x, professionals, keys_by_day, links_by_wf=None,
                             enforce_lit=None):
    """Per cada (dia, franja) i cada parella vinculada AQUELL dia-setmana i
    franja, el mateix facultatiu cobreix el slot representatiu de tots dos.
    La vinculació és PER (dia-setmana, franja): un dia poden estar vinculades
    i un altre no. Funciona encara que algun slot estigui doblat."""
    if not links_by_wf:
        return
    for day, day_keys in keys_by_day.items():
        wd = _weekday_code(day)
        franges = {sk[1] for sk in day_keys}
        for franja in franges:
            for slot_a, slot_b in _links_for_daykey(links_by_wf, wd, franja):
                a_keys = [sk for sk in day_keys if sk[2] == slot_a and sk[1] == franja]
                b_keys = [sk for sk in day_keys if sk[2] == slot_b and sk[1] == franja]
                rep_a = _representative_key(a_keys)
                rep_b = _representative_key(b_keys)
                if rep_a is not None and rep_b is not None:
                    for p in professionals:
                        ct = model.Add(x[p, rep_a] == x[p, rep_b])
                        if enforce_lit is not None:
                            ct.OnlyEnforceIf(enforce_lit)


def _add_preassignment_constraints(model, x, preassignments_df, slot_keys, enforce_lit=None):
    if preassignments_df.empty:
        return
    for row in preassignments_df.itertuples(index=False):
        if int(row.fixed) != 1:
            continue
        matching = _matching_preassignment_keys(row, slot_keys)
        if len(matching) == 1:
            ct = model.Add(x[row.professional_id, matching[0]] == 1)
            if enforce_lit is not None:
                ct.OnlyEnforceIf(enforce_lit)
        elif len(matching) > 1:
            ct = model.Add(sum(x[row.professional_id, sk] for sk in matching) == 1)
            if enforce_lit is not None:
                ct.OnlyEnforceIf(enforce_lit)


def _add_review_continuity(model, x, professionals, keys_by_day, slot_rows, working_map,
                           review_slots, unav_index=None, enforce_lit=None):
    """En dies no laborables, cada slot de revisió (del catàleg) va al mateix
    facultatiu que el SEGÜENT dia laborable (el primer dia laborable
    posterior). No depèn de cap nom d'slot.

    Relaxació (evita infeasibility): si CAP facultatiu pot cobrir els dos
    dies enllaçats (tots tenen vacances/baixa en almenys un dels dos), no
    s'imposa la continuïtat — la cobertura assigna el slot del festiu
    lliurement."""
    from src.solver.preprocessing import _day_fully_blocked
    unav_index = unav_index or {}
    for review_slot in review_slots:
        review_days = sorted({str(r.day) for r in slot_rows if str(r.slot_id) == review_slot})
        n = len(review_days)
        for i, day in enumerate(review_days):
            if working_map.get(day, 1) == 1:
                continue
            next_working = None
            for j in range(i + 1, n):
                if working_map.get(review_days[j], 1) == 1:
                    next_working = review_days[j]
                    break
            if next_working is None:
                continue
            today_keys = [sk for sk in keys_by_day.get(day, []) if sk[2] == review_slot]
            next_keys = [sk for sk in keys_by_day.get(next_working, []) if sk[2] == review_slot]
            if len(today_keys) == 1 and len(next_keys) == 1:
                # Hi ha algun portador possible (lliure els dos dies)?
                has_carrier = any(
                    not _day_fully_blocked(p, day, unav_index)
                    and not _day_fully_blocked(p, next_working, unav_index)
                    for p in professionals
                )
                if not has_carrier:
                    continue  # relaxa: cap facultatiu pot enllaçar els dos dies
                for p in professionals:
                    ct = model.Add(x[p, today_keys[0]] == x[p, next_keys[0]])
                    if enforce_lit is not None:
                        ct.OnlyEnforceIf(enforce_lit)


def _add_flip_target_cap(model, x, pres_flip, quota_hard_professionals, unique_days,
                         unique_weeks, week_map, working_map, absent_days_by_prof,
                         capacity_pct_by, machine_specs, planning_rules=None):
    """Hard: els 'flips' (no-presencial ordinari comptat com a presencial)
    NOMÉS poden omplir fins al target presencial setmanal del facultatiu,
    mai per sobre. Els presencials FIXOS forçats per cobertura sí que
    poden superar-lo (com fins ara, amb penalització tova). Per setmana:
    fix + flips <= target + max(0, fix - target)."""
    if not pres_flip:
        return
    rules = planning_rules if planning_rules is not None else PlanningRules.defaults()
    days_by_week: dict = {}
    for d in unique_days:
        days_by_week.setdefault(week_map[d], []).append(d)

    for p in quota_hard_professionals:
        for yw in unique_weeks:
            active_days = [
                d for d in days_by_week.get(yw, [])
                if working_map.get(d, 1) == 1 and d not in absent_days_by_prof[p]
            ]
            if not active_days:
                continue
            fixed_terms, flip_terms = [], []
            for day in active_days:
                spec = machine_specs.get(day)
                if not spec:
                    continue
                _, _, _, presential_keys, flippable_keys = spec
                fixed_terms.extend(x[p, sk] for sk in presential_keys if (p, sk) in x)
                flip_terms.extend(
                    pres_flip[(p, sk)] for sk in flippable_keys if (p, sk) in pres_flip
                )
            if not flip_terms:
                continue
            eff_days = (sum(capacity_pct_by[(p, d)] for d in active_days) + 99) // 100
            target = rules.target_presential.get(min(eff_days, 5), 0)
            n_f = max(1, len(fixed_terms))
            fixed_total = model.NewIntVar(0, n_f, f"flipcap_fixed_{p}_{yw}")
            model.Add(fixed_total == (sum(fixed_terms) if fixed_terms else 0))
            over_fixed = model.NewIntVar(0, n_f, f"flipcap_overfix_{p}_{yw}")
            model.AddMaxEquality(over_fixed, [fixed_total - target, 0])
            model.Add(fixed_total + sum(flip_terms) <= target + over_fixed)
