"""Expander informatiu a la pestanya Calendari inicial que descriu les
restriccions estructurals (hard) que el solver imposa sempre i que NO
es poden configurar des de la UI. Ajuda l'usuari a entendre per què
algunes assignacions són impossibles."""
import streamlit as st


def render_initial_constraints_info() -> None:
    """Expander amb les lleis estructurals del calendari inicial."""
    with st.expander(
        "ℹ️ Lleis estructurals del calendari (no configurables)",
        expanded=False,
    ):
        st.markdown(
            """
El solver imposa sempre aquestes restriccions estructurals, que NO es
poden configurar des de la UI:

**Cobertura**
- Cada slot del calendari ha de tenir **exactament 1 facultatiu**
  assignat (el comodí TLD també compta).
- Un facultatiu regular no pot cobrir més d'una instància del mateix
  grup-slot el mateix dia (vincles compten com 1).

**Cap diari per facultatiu**
- Màxim **1 màquina per franja** (MATÍ o TARDA) per facultatiu i dia.
  Els slots vinculats compten com 1 màquina.
- Màxim **1 PRESENCIAL per dia** per facultatiu (excloent la franja NIT).
- Si l'usuari ha marcat algun facultatiu com a comodí (Restriccions ›
  Comodí) i clica el Regenerar d'aquell expander, el comodí queda exempt
  d'aquests caps. Al calendari inicial NO hi ha comodí — cap exempció.

**Màquina secundària (linked)**
- Una activitat amb "Màquina secundària" al catàleg s'assigna sempre al
  mateix facultatiu que la principal el mateix dia (la principal en
  PRESENCIAL, la secundària per defecte en NO_PRESENCIAL).
- Comuna com a 1 sola màquina al recompte d'ordinàries.

**Continuïtat de revisió**
- En dies no laborables (festius/caps de setmana), les revisions
  s'assignen al mateix facultatiu que el següent dia laborable.
- Si cap facultatiu pot cobrir els dos dies enllaçats, la continuïtat
  es relaxa per evitar infactibilitat.

**Acoblament de slots vinculats**
- Si dos slots tenen `linked_to`, el solver els assigna al mateix
  facultatiu per a cada (dia, franja).

Aquestes restriccions estan hardcoded perquè són estructurals: definir
què és físicament possible al planning, no una preferència ajustable.
"""
        )
