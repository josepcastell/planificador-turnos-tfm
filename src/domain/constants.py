from pathlib import Path


WEEKDAY_SCOPE_OPTIONS = ["Mes seleccionat", "Trimestre"]

CATALAN_MONTHS = {
    1: "Gener",
    2: "Febrer",
    3: "Març",
    4: "Abril",
    5: "Maig",
    6: "Juny",
    7: "Juliol",
    8: "Agost",
    9: "Setembre",
    10: "Octubre",
    11: "Novembre",
    12: "Desembre",
}

WEEKDAY_LABELS = ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres", "Dissabte", "Diumenge"]
WEEKDAY_NAMES_BY_INDEX = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
WEEKDAY_TEMPLATE_COLUMNS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]
CORE_SLOT_IDS = [
    "3T_DIR",
    "1.5T_DIR",
    "TC_DIR",
    "RM_HUB",
    "RM_DELTA",
    "TC3_HUB",
    "TC4_HUB",
    "TC_URG",
    "TC_DELTA",
    "PET_RM",
    "ECO3",
    "REVISA_RM",
    "GD",
    "POST_GUARDIA",
    "REFUERZO",
]

# Slots gestionats exclusivament des de la pestanya Guàrdies (Calendari base).
# No s'inclouen al catàleg de slots editable per evitar que apareguin als
# templates d'entre setmana / cap de setmana.
GUARDS_RESERVED_SLOT_IDS = {"GD", "POST_GUARDIA", "REFUERZO"}

FRANJA_ORDER = {"MATI": 0, "TARDA": 1, "NIT": 2, "12H": 3}
WORK_MODE_ORDER = {"NORMAL": 0, "PEONADA": 1}
PRESENTIALITY_ORDER = {"PRESENCIAL": 0, "NO_PRESENCIAL": 1}

# Família TC/RM: ja no és una llista hardcoded. Es deriva del nom del slot
# (vegeu src.domain.schedule_format.slot_metric_family): conté "TC" → TC,
# conté "RM" → RM. Així el solver funciona amb qualsevol nom del catàleg.

METRIC_TARGET_CALENDARS = ["Entre setmana"]

CARRY_FORWARD_SESSION_FILES = [
    Path("data/professionals.csv"),
    Path("data/eligibility.csv"),
    Path("data/slot_catalog.csv"),
    Path("data/weekday/weekly_slot_templates.csv"),
    Path("data/absences/assignments.csv"),
    Path("data/comite/assignments.csv"),
    Path("data/weekday/unavailability.csv"),
    Path("data/planning_rules.csv"),
]

ABSENCE_TYPES = [
    "vacances",
    "baixa",
    "permis",
    "assumptes_propis",
    "maternitat_paternitat",
    "formacio",
    "vaga",
    "altres_absencies",
]

# Comitè types — registered separately from absences (data/comite/assignments.csv).
# A comitè does NOT generate unavailability; it forces the professional to be
# assigned to a machine of the corresponding family that day.
COMITE_TYPES = ["HUB", "DIR"]

# Weekday codes used by the comitè recurrent pattern (matching python's weekday()).
WEEKDAY_CODES = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

# Cap facultatiu real és exempt de la quota setmanal. El sentinel virtual
# "NONE" sí que se n'exclou (no és una persona). Els slots de revisió
# (REVISA*) no compten com a màquina, fet que cobreix els casos previs.
QUOTA_EXEMPT_PROFESSIONALS = {"NONE"}

# Slots que compten per a la quota setmanal de màquines: qualsevol slot del
# catàleg que NO sigui de revisió (REVISA*) ni de guàrdia. Es deriva en
# temps d'execució (vegeu src.solver.constraints), sense llista hardcoded.

# NOTA: les antigues constants WEEKLY_MACHINE_QUOTA_HARD,
# WEEKLY_PRESENTIAL_QUOTA_HARD i WEEKLY_MACHINE_SOFT_TARGET s'han
# eliminat. Els valors actuals dels targets per setmana es defineixen
# a PlanningRules (data/planning_rules.csv, editable des de l'UI a
# l'apartat Equilibri).

# Objective function weights (CP-SAT minimization).
# Magnitudes ordered by priority (higher = wins ties): manual metric targets and
# stability dominate everything else; weekly equity (presential/TC-RM spread,
# telework) beats fine balancing (family_imbalance, review_spread).
# Spread terms are scaled by 100 (capacity normalization), so spread weights
# look smaller than they really are vs raw integer counts.
# Ordre acordat amb l'usuari (7 que manen + resta a sota):
#  1 canvis manuals (stability) · 2 franges presencials · 3 targets
#  pres/no-pres (editables + planning_rules) · 4 peonades ≤3/mes ·
#  5 resta a TLD · 6 comitè mateixa localització · 7 guàrdia matí.
SOLVER_WEIGHTS = {
    # Elegibilitat: TOVA però amb pes molt alt (només cedeix si no hi ha
    # cap altra opció possible; mai supera la cobertura dura).
    "eligibility_penalty": 10_000_000,
    # Dies de la setmana exclusivament no-presencials (per facultatiu).
    # TOVA però amb pes molt alt: el solver evita assignar slots PRES
    # al facultatiu en aquells dies, però pot infringir si és estrictament
    # necessari per cobrir el calendari. Les revisions queden fora (no
    # compten com a presencial ordinari). Pes 6M: per sobre del target
    # PRES setmanal (3M) i de l'stability (5M), per sota d'elegibilitat (10M).
    "no_pres_weekday_violation": 6_000_000,
    # Dies de la setmana exclusivament presencials (per facultatiu). Mateix
    # pes i lògica que el cas simètric: penalitza NP en aquests dies,
    # revisions excloses.
    "pres_weekday_violation": 6_000_000,
    # 1 — preservar els canvis puntuals que fa l'usuari (en reajustar,
    #     mínim de canvis respecte al pla anterior).
    "stability": 5_000_000,
    # 2 — franges presencials: assolir el target presencial setmanal.
    # Pes alt — per sobre dels spreads (PRES i ORDINÀRIES, ~1M cadascun):
    # els targets es respecten ABANS que el solver intenti l'equilibri.
    # Si dos repartiments compleixen el target, el spread escolleix el
    # més equitatiu.
    # NOTA: l'overage presencial reutilitza aquest mateix pes a core.py.
    "weekly_presential_shortfall": 3_000_000,
    # 3 — acostar-se als targets de dies presencials i no-presencials:
    #     editables a Mètriques (per setmana) + planning_rules (màquines).
    "weekly_overage": 500_000,
    "weekly_shortfall": 500_000,
    # 5 — TLD comodí: pes ALT (20× el valor inicial 5k) perquè el solver
    #     minimitzi agresivament l'ús de TLD al tier 4, després que el
    #     tier 2 hagi assolit el target NP (peonades emergeixen com a
    #     vàlvula sub-cap per absorbir overage). Així la jerarquia
    #     efectiva és:
    #       tier 2: assolir np_ord = target (peonades emergeixen com cal)
    #       tier 4: dels NP "extra" (sub-cap), convertir TLD→regular_peo
    #     Si poseu TLD al tier 2 directament, el solver es queda encallat
    #     en mínims locals i l'overage augmenta — el separar tiers manté
    #     l'optimitzaci'o ordenada.
    "tld_usage": 100_000,
    # Equitat de PRESENCIALITATS per facultatiu, col·lapsant parells
    # vinculats (igual que fa la UI a Mètriques) i amb target individual
    # proporcional a la jornada. Es minimitza en DUES dimensions:
    #   · L1 (suma de desviacions |count_p − target_p|): dóna gradient a
    #     TOTS els facultatius, no només els extrems → millor convergència.
    #   · L∞ (màx desviació): evita que un facultatiu es quedi enrere.
    "presential_spread_l1": 200_000,
    "presential_spread_max": 400_000,
    # Equitat ACUMULADA (cross-month): si generes mes a mes dins un scope,
    # el solver veu els counts dels mesos previs i minimitza el spread
    # ACUMULAT. Pesos superiors als mensuals: el que importa al final és
    # l'acumulat (el mensual ja és prou bo amb el spread del mes).
    "presential_cum_spread_l1": 300_000,
    "presential_cum_spread_max": 600_000,
    # Equitat de MÀQUINES ORDINÀRIES (PRES + NO_PRES ORD, sense peonades).
    # Pesos alts (per sota dels targets setmanals): l'objectiu final de
    # l'usuari és que TOTS els facultatius tinguin el mateix nombre,
    # amb TLD i peonades com a vàlvula. El L∞ és el sostre dur (cap dev
    # > 1 si possible).
    "ordinary_spread_l1": 500_000,
    "ordinary_spread_max": 2_000_000,
    "ordinary_cum_spread_l1": 700_000,
    "ordinary_cum_spread_max": 2_500_000,
    # Equitats SECUNDÀRIES amb pes baix (només per a desempat). No
    # competeixen amb les principals.
    "tc_rm_balance": 10_000,         # desequilibri intra-facultatiu TC vs RM
    # Equitat de revisions lliures (spread max−min entre facultatius
    # actius). TOVA i de baixa prioritat (tram 4): el solver reparteix
    # les revisions quan no perjudica cap objectiu superior. Les
    # revisions són slots independents (no compten com a màquina), així
    # que aquest terme actua sobretot com a desempat sense fer trade-off
    # amb la cobertura ni l'equitat de màquines.
    "review_spread": 20_000,
    # 6 — comitè i màquina presencial a la mateixa localització.
    "comite_preferred_machine": 50_000,
    # 7 — guàrdia: prioritzar NO_PRESENCIAL (teletreball) el matí del dia
    # de guàrdia (la tarda i la nit ja queden bloquejades).
    "guard_morning_telework": 40_000,
}
