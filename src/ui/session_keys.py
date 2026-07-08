"""Registre centralitzat de claus de `st.session_state` per pestanya.

Cada grup llista totes les claus que pertanyen a una pestanya principal,
incloent drafts, signatures d'autosave, nonces d'editor i estats de selecció.
S'utilitza a la neteja de sessió de la barra lateral (buida els drafts en
memòria de totes les pestanyes) i als editors, per mantenir tot el
"vocabulari" en un únic lloc.

Si afegeixes una nova clau a un editor, registra-la aquí perquè la neteja
de sessió la pugui buidar correctament.
"""

# ── Activitat ──────────────────────────────────────────────────────────────
ACTIVITAT_CATALOG: tuple[str, ...] = (
    "slot_catalog_draft",
    "slot_catalog_current",
    "slot_catalog_draft_path",
    "slot_catalog_draft_signature",
    "_autosave_sig_slot_catalog",
    "slot_catalog_editor_nonce",
    "slot_catalog_view",
)
ACTIVITAT_LISTS: tuple[str, ...] = (
    "machines_list_input",
    "locations_list_input",
)
ACTIVITAT: tuple[str, ...] = ACTIVITAT_CATALOG + ACTIVITAT_LISTS

# ── Facultatius ────────────────────────────────────────────────────────────
FACULTATIUS: tuple[str, ...] = (
    "base_professionals_draft",
    "base_professionals_draft_path",
    "base_professionals_editor_nonce",
    "base_professionals_view",
)

# ── Restriccions (estructura del calendari, ABANS de generar):
#     Franges / Equilibri / Festius ────────────────────────────────────────
RESTRICCIONS: tuple[str, ...] = (
    "selected_fixed_work_slot_edit",
    "selected_fixed_work_slot_cell",
    "selected_punctual_work_slot_edit",
    "selected_punctual_work_slot_cell",
    "planning_rules_draft",
    "planning_rules_editor_nonce",
)

# ── Generar i revisar ─────────────────────────────────────────────────────
GENERAR: tuple[str, ...] = (
    "weekday_live_schedule",
    "weekday_reajust_report",
    "pdf_save_dir_input",
)

# ── Mètriques i canvis finals (DESPRÉS de generar) ────────────────────────
# Inclou tant la vista de mètriques (i reajust) com les restriccions
# opcionals que s'apliquen post-calendari-inicial: guàrdies, absències,
# comitès, indisponibilitats, elegibilitat, dies NP/PRES per facultatiu.
METRIQUES: tuple[str, ...] = (
    "weekday_reajust_report",
    "presential_tolerance_input",
    "presential_tolerance_input_initial_tab",
    "extraordinary_cap_input",
    # Restriccions opcionals (mogudes de Restriccions).
    "comite_draft",
    "comite_editor_nonce",
    "guards_draft",
    "guards_editor_nonce",
    "absences_draft",
    "absences_editor_nonce",
    "specific_unavailability_draft",
    "specific_unavailability_editor_nonce",
    "eligibility_draft",
    "eligibility_editor_nonce",
    "no_pres_weekdays_picker",
    "pres_weekdays_picker",
)

# ── Mapping per a la neteja iterativa ──────────────────────────────────────
TAB_SESSION_KEYS: dict[str, tuple[str, ...]] = {
    "activitat": ACTIVITAT,
    "facultatius": FACULTATIUS,
    "restriccions": RESTRICCIONS,
    "generar": GENERAR,
    "metriques": METRIQUES,
}
