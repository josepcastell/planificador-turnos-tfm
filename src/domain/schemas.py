"""Font ÚNICA dels esquemes (capçaleres) dels CSV del projecte.

`services/session_store` reinicialitza els fitxers d'entrada (blank_header)
en obrir una sessió nova; les capçaleres es defineixen aquí perquè hi hagi
un únic lloc de veritat (i no divergeixin de l'esquema real dels fitxers).

Les claus són el `path_template` (amb `{year}` si escau, igual que a
session_store). El valor és la línia de capçalera amb `\\n` final.
"""


CSV_HEADERS: dict[str, str] = {
    # Festius i calendari base (per any)
    "data/derived/public_holidays_{year}.csv": "day,location\n",
    "data/base_calendar_overrides_{year}.csv":
        "day,is_ics_holiday,is_extra_holiday,force_working_day,day_type,notes\n",
    # Dades mestres
    "data/professionals.csv":
        "professional_id,name,doubled_machines,non_working_weekdays,"
        "no_pres_weekdays,pres_weekdays,fallback,presence_mode,allowed_areas\n",
    "data/eligibility.csv": "professional_id,slot_id,allowed\n",
    "data/slot_catalog.csv":
        "slot_id,weekday,weekend,linked_to,doubled,review,area,"
        "metric_family,assignee,notes\n",
    "data/weekday/weekly_slot_templates.csv":
        "weekday_name,franja,slot_id,presentiality,work_mode,required_staff,"
        "is_active,doubled,linked_to\n",
    "data/maquines.csv": "nom\n",
    "data/llocs.csv": "nom\n",
    "data/planning_rules.csv": "active_days,target_machines,target_presential\n",
    # Operatives (indisponibilitats, guàrdies, comitès, preassignacions)
    "data/comite/assignments.csv":
        "professional_id,comite_name,comite_type,specific_day,weekday,notes\n",
    "data/guards/assignments.csv": "day,professional_id,guard_kind,notes\n",
    "data/absences/assignments.csv":
        "absence_type,professional_id,start_day,end_day,notes\n",
    "data/weekday/unavailability.csv": "professional_id,day,reason\n",
    "data/weekday/preassignments.csv":
        "professional_id,day,slot_id,fixed,source,notes\n",
}
