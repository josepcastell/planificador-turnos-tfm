"""Extract a CP-SAT solution into human-readable schedule and metrics rows."""

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.solver.normalize import _make_slot_key


def _extract_solution(solver, x, professionals, real_professionals, active_professionals,
                      slot_keys, slot_rows, unique_days, presential_counts,
                      tc_counts, rm_counts, family_imbalance, review_rm_counts,
                      pres_dev_l1, max_presential, min_presential,
                      spread_tc, max_tc, min_tc, spread_rm, max_rm, min_rm,
                      spread_review_rm, max_review_rm, min_review_rm,
                      total_family_imbalance, average_capacity_pct, pres_flip=None,
                      pres_dev_linf=None, peonada_vars=None,
                      effective_capacity_pct=None, np_flip=None):
    pres_flip = pres_flip or {}
    np_flip = np_flip or {}
    peonada_vars = peonada_vars or {}
    effective_capacity_pct = effective_capacity_pct or {}
    lines = ["Solució trobada:", ""]
    schedule_rows = []
    metrics_rows = []
    flips = []

    for day in unique_days:
        lines.append(f"Dia {day}:")
        day_rows = sorted(
            [r for r in slot_rows if str(r.day) == day],
            key=lambda r: (str(r.franja), str(r.slot_id), str(r.presentiality), str(r.work_mode))
        )
        for row in day_rows:
            sk = _make_slot_key(row)
            assigned = [p for p in professionals if solver.Value(x[p, sk]) == 1]
            if not assigned:
                # Slot opcional sense assignar (p.ex. pos2 condicional
                # del doblat per facultatiu sense cap marcat present).
                continue
            professional = assigned[0]
            presentiality = str(row.presentiality)
            # El flip converteix REALMENT un slot NO_PRES ordinari en
            # PRESENCIAL al schedule final. Així el comptatge de la UI
            # coincideix amb el que el solver minimitza (no hi ha
            # comptadors "fantasma" invisibles a l'usuari).
            # Marca is_flipped=1 quan el solver ha forçat la conversió;
            # la UI ho mostrarà amb un prefix "T-" davant del facultatiu
            # (indica que cal informar de presència física a l'hospital,
            # però no necessàriament el dia de l'exploració).
            is_flipped = 0
            fv = pres_flip.get((professional, sk))
            if fv is not None and solver.Value(fv) == 1:
                presentiality = "PRESENCIAL"
                is_flipped = 1
                flips.append((professional, str(row.day), str(row.slot_id)))
            # Flip INVERS (PRES→NP): una màquina presencial que el solver
            # ha convertit en remota per baixar fins al target presencial.
            # is_flipped=-1 perquè la UI la pugui distingir del cas PRES.
            nf = np_flip.get((professional, sk))
            if nf is not None and solver.Value(nf) == 1:
                presentiality = "NO_PRESENCIAL"
                is_flipped = -1
                flips.append((professional, str(row.day), str(row.slot_id)))
            # NOU MODEL DE PEONADES: work_mode a la sortida ja no surt del
            # template (que el solver ignora). Es deriva del booleà
            # `pn[professional, sk]` que el solver ha decidit a tier 2.
            # Si pn=1 → PEONADA (extra del facultatiu aquell mes), si no
            # → NORMAL. Així mètriques i PDF segueixen agregant per
            # work_mode, però la decisió la fa el solver (no l'usuari).
            pn = peonada_vars.get((professional, sk))
            if pn is not None and solver.Value(pn) == 1:
                work_mode_out = "PEONADA"
            else:
                work_mode_out = "NORMAL"
            franja_txt = f"[{row.franja}] " if str(row.franja).strip() else ""
            lines.append(f"  {franja_txt}{row.slot_id}: {professional}")
            schedule_rows.append([
                str(row.day), str(row.franja), str(row.slot_id), professional,
                presentiality, work_mode_out, is_flipped,
            ])
        lines.append("")

    lines.append("Càrrega per professional:")
    for p in real_professionals:
        guard_slots = sum(
            solver.Value(x[p, _make_slot_key(r)])
            for r in slot_rows
            if str(r.slot_id).upper() in GUARDS_RESERVED_SLOT_IDS
        )
        reduction_pct = 100 - average_capacity_pct.get(p, 100)
        lines.append(
            f"  {p}: actiu={1 if p in active_professionals else 0} "
            f"| total={sum(solver.Value(x[p, sk]) for sk in slot_keys)} "
            f"| reduccio_jornada={reduction_pct}% "
            f"| presencials={solver.Value(presential_counts[p])} "
            f"| TC_familia={solver.Value(tc_counts[p])} "
            f"| RM_familia={solver.Value(rm_counts[p])} "
            f"| desequilibri_TC_RM={solver.Value(family_imbalance[p])} "
            f"| guardies={guard_slots} "
            f"| revisions={solver.Value(review_rm_counts[p])}"
        )
        metrics_rows.append({
            "professional": p,
            "active": 1 if p in active_professionals else 0,
            "workday_reduction_pct": reduction_pct,
            # Capacitat EFECTIVA per a l'equitat (jornada × dies presents
            # − absències − postguàrdies). És el denominador real amb què el
            # solver reparteix màquines/presencials; la UI hi normalitza.
            "effective_capacity_pct": int(effective_capacity_pct.get(p, 100 - reduction_pct)),
            "total_assigned": sum(solver.Value(x[p, sk]) for sk in slot_keys),
            "presential_assigned": solver.Value(presential_counts[p]),
            "tc_family_slots": solver.Value(tc_counts[p]),
            "rm_family_slots": solver.Value(rm_counts[p]),
            "family_diff": solver.Value(family_imbalance[p]),
            "guard_slots": guard_slots,
            "review_slots": solver.Value(review_rm_counts[p]),
        })

    lines += [
        "",
        "Professionals actius per equitat: " + ", ".join(active_professionals),
        "Equitat presencial (slots PRESENCIAL per facultatiu actiu, "
        "col·lapsant parells vinculats, sense flips): "
        f"max={solver.Value(max_presential)} | "
        f"min={solver.Value(min_presential)} | "
        f"rang={solver.Value(max_presential) - solver.Value(min_presential)} | "
        f"L1={solver.Value(pres_dev_l1)}"
        + (f" | L∞={solver.Value(pres_dev_linf)}" if pres_dev_linf is not None else ""),
        f"Desequilibri total TC/RM (actius): {solver.Value(total_family_imbalance)}",
        "Equitat TC ajustada per jornada: "
        f"max={solver.Value(max_tc) / 100:.1f} | "
        f"min={solver.Value(min_tc) / 100:.1f} | "
        f"diferència={solver.Value(spread_tc) / 100:.1f}",
        "Equitat RM ajustada per jornada: "
        f"max={solver.Value(max_rm) / 100:.1f} | "
        f"min={solver.Value(min_rm) / 100:.1f} | "
        f"diferència={solver.Value(spread_rm) / 100:.1f}",
        f"Equitat revisió: max={solver.Value(max_review_rm)} | "
        f"min={solver.Value(min_review_rm)} | diferència={solver.Value(spread_review_rm)}",
    ]

    # Marcador per a la UI: slots no-presencials ordinaris que el solver
    # ha comptat com a presencials (flip) per assolir el target presencial.
    for prof, day, slot in sorted(set(flips)):
        print(f"FLIP_PRESENCIAL\t{prof}\t{day}\t{slot}")
    if flips:
        print(
            f"AVIS_FLIP_PRESENCIAL: {len(set(flips))} activitat(s) no-presencial(s) "
            "convertida(es) a presencial per assolir el target presencial."
        )

    return "\n".join(lines), schedule_rows, metrics_rows
