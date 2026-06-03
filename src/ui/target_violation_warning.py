"""Mostra un warning a la UI quan el solver no ha assolit el target
setmanal (PRES o NP) al darrer Generar/Regenerar."""
from __future__ import annotations

import streamlit as st

from src.services.calendar_target_analysis import compute_calendar_vs_targets
from src.services.solver_log_parser import (
    collect_target_violations,
    parse_solver_log,
)


def render_target_violation_warning(
    year: int | None = None,
    months: list[int] | None = None,
) -> None:
    """Si el darrer run del solver té shortfall/overage > 0, mostra un
    st.warning amb el desglossament i diagnòstic estructural (calendari
    vs targets). Sinó no fa res.

    Si es passen `year` i `months`, s'inclou una anàlisi del
    dimensionament del calendari (slots PRES/NP vs targets esperats),
    que dona una causa concreta del shortfall."""
    summary = parse_solver_log()
    if not summary.get("tiers"):
        return
    v = collect_target_violations(summary)
    if not any(v.values()):
        return
    items: list[str] = []
    if v["pres_shortfall"]:
        items.append(
            f"**PRES per sota del target**: {v['pres_shortfall']} unitats. "
            "El solver ha flipat NP→PRES tant com ha pogut, però estructuralment "
            "no n'hi ha hagut prou."
        )
    if v["pres_overage"]:
        items.append(
            f"**PRES per sobre del target**: {v['pres_overage']} unitats. "
            "El calendari demana més PRES dels que els targets sumen → algun "
            "facultatiu supera el target."
        )
    if v["np_shortfall"]:
        items.append(
            f"**NP per sota del target**: {v['np_shortfall']} unitats."
        )
    if v["np_overage"]:
        items.append(
            f"**NP per sobre del target**: {v['np_overage']} unitats "
            "(podria absorbir-se afegint peonades)."
        )

    # Diagnòstic estructural (calendari vs targets esperats).
    diag_lines: list[str] = []
    if year is not None and months:
        analysis = compute_calendar_vs_targets(year, months)
        diag_lines.append(
            f"📐 **Calendari vs targets esperats** (any {year}, mesos "
            f"{months}):"
        )
        diag_lines.append(
            f"   - Slots PRES al calendari: **{analysis['calendar_pres']}**, "
            f"target sumat: **{analysis['target_pres']}** → "
            f"diferència: **{analysis['diff_pres']}** "
            f"({'falten PRES al calendari' if analysis['diff_pres'] > 0 else 'sobren PRES al calendari' if analysis['diff_pres'] < 0 else 'equilibrat'})"
        )
        diag_lines.append(
            f"   - Slots NP al calendari: **{analysis['calendar_np']}**, "
            f"target NP_ord sumat: **{analysis['target_np_ord']}** → "
            f"diferència: **{analysis['diff_np']}** "
            f"({'falten NP' if analysis['diff_np'] > 0 else 'sobren NP' if analysis['diff_np'] < 0 else 'equilibrat'})"
        )
        if analysis["diff_pres"] > 0:
            diag_lines.append(
                "   → **Per fer desaparèixer el shortfall PRES**: o bé "
                "afegir més franges PRES al template (pestanya Estructura), "
                "o reduir `target_presential` a Regles d'equilibri."
            )
        elif analysis["diff_pres"] < 0:
            diag_lines.append(
                "   → **Per fer desaparèixer l'overage PRES**: o bé "
                "pujar `target_presential` a Regles d'equilibri, o reduir "
                "franges PRES al template."
            )

    body = "\n".join(f"- {it}" for it in items)
    diag_body = "\n\n" + "\n".join(diag_lines) if diag_lines else ""
    st.warning(
        "⚠️ **El solver no ha pogut assolir el target setmanal:**\n\n"
        + body + diag_body + "\n\n"
        "_Consulta `outputs/solver_log.txt` per al desglossament complet "
        "del solver._",
        icon="⚠️",
    )
