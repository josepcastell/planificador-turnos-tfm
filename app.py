import streamlit as st
import os
from pathlib import Path
from datetime import date, datetime

import pandas as pd
from src.domain.constants import (
    CARRY_FORWARD_SESSION_FILES,
)
from src.services.planner_inputs import load_planner_inputs
from src.services.slot_catalog import (
    review_slot_ids,
    seed_slot_catalog_if_missing,
    slot_area_map,
    slot_metric_family_map,
    weekday_slot_ids,
)
from src.domain.schedule_format import (
    set_slot_area_overrides,
    set_slot_metric_overrides,
    set_slot_review_overrides,
)
from src.ui.eligibility_editor import render_eligibility_editor
from src.ui.holiday_editor import render_holidays_editor
from src.ui.input_editors import (
    render_absences_editor,
    render_comite_editor,
    render_doubled_machines_section,
    render_guards_editor,
    render_no_pres_weekdays_editor,
    render_pres_weekdays_editor,
    render_professionals_editor,
)
from src.ui.input_save_controls import save_pending_input_drafts
from src.ui.metrics_tab import (
    render_weekday_metrics,
)
from src.ui.planning_calendar_tabs import (
    render_weekday_planning_tab,
)
from src.ui.planning_scope_controls import (
    render_weekday_scope_controls,
    weekday_scope_values,
)
from src.ui.session_sidebar import render_session_sidebar_actions
from src.ui.update_panel import render_update_panel
from src.ui.slot_catalog_editor import render_slot_catalog_editor
from src.ui.machines_editors import (
    render_machines_locations_editor,
    render_fixed_machines_editor,
)
from src.ui.styles import apply_global_styles
from src.ui.comodi_editor import render_comodi_editor
from src.ui.peonada_cap_editor import render_peonada_cap_editor
from src.ui.quick_add_panels import render_quick_add_panels
from src.ui.restriction_warnings import (
    warn_absences_vs_initial,
    warn_eligibility_vs_initial,
    warn_guards_vs_initial,
    warn_no_pres_weekday_vs_initial,
    warn_pres_weekday_vs_initial,
)
from src.ui.schedule_changes_editor import render_schedule_changes_editor
from src.ui.weekday_slot_editor import (
    render_weekday_punctual_overrides_editor,
    render_weekday_work_slot_editor,
)
from src.ui.planning_rules_editor import render_planning_rules_editor
from src.ui.workflow_state import (
    init_workflow_state,
    invalidate_after_work_slot_change,
    set_workflow_state,
)
from src.services import session_store

st.set_page_config(page_title="Planificador de torns", layout="wide")

apply_global_styles()

# Panell d'auto-actualització (a dalt de la barra lateral).
render_update_panel(Path(__file__).resolve().parent)

# Tancar el programa de forma neta (atura el servidor). Així no cal cap
# finestra de terminal per aturar-lo: s'obre sense finestra i es tanca des d'aquí.
if st.sidebar.button(
    "⏻ Tancar el programa",
    key="app_exit_btn",
    width="stretch",
    help="Desa i atura el programa. Després ja pots tancar la pestanya "
         "del navegador.",
):
    # NO aturem aquí: deixem que el run continuï fins al final perquè
    # els autosaves dels editors d'aquest mateix rerun (l'última edició
    # de l'usuari) s'apliquin abans d'apagar. El tancament real es fa
    # al FINAL d'app.py.
    st.session_state["_app_exit_requested"] = True
    st.sidebar.success("Desant i aturant el programa…")

DEFAULT_YEAR = 2026
DEFAULT_MONTH = 1


def default_app_folder(env_key: str, folder_name: str) -> Path:
    configured = os.environ.get(env_key)
    if configured:
        return Path(configured).expanduser()

    for env_var in ("USERPROFILE", "HOME"):
        env_path = os.environ.get(env_var)
        if not env_path:
            continue
        desktop = Path(env_path).expanduser() / "Desktop"
        if desktop.exists():
            return desktop / folder_name

    wsl_users_root = Path("/mnt/c/Users")
    if wsl_users_root.exists():
        ignored_names = {"All Users", "Default", "Default User", "Public"}
        for desktop in sorted(wsl_users_root.glob("*/Desktop")):
            if desktop.parent.name not in ignored_names and desktop.exists():
                return desktop / folder_name

    return Path.cwd() / folder_name


def _program_folder() -> Path:
    """Carpeta del PROGRAMA (arrel del portable). El llançador executa amb
    cwd = <bundle>/app, així que l'arrel és el pare; en desenvolupament, el
    cwd actual."""
    cwd = Path.cwd()
    return cwd.parent if cwd.name == "app" else cwd


PDF_OUTPUT_DIR = default_app_folder("PAC3_PDF_OUTPUT_DIR", "Planning_PDFs")
# Carpeta per defecte on l'usuari guarda els PDF: l'escriptori.
DESKTOP_DIR = default_app_folder("PAC3_DESKTOP_DIR", "")
# Sessions i les seves còpies de seguretat: a la MATEIXA carpeta del programa
# (perquè el portable sigui autocontingut i les sessions viatgin amb ell).
# Sobreescrivible amb la variable d'entorn PAC3_SESSION_ROOT.
_cfg_session_root = os.environ.get("PAC3_SESSION_ROOT")
DEFAULT_SESSION_ROOT = (
    Path(_cfg_session_root).expanduser() if _cfg_session_root
    else _program_folder() / "Sessions_planificador"
)
LAST_SESSION_PATH = DEFAULT_SESSION_ROOT / ".last_session"


def read_last_session_name() -> str:
    return session_store.read_last_session_name(LAST_SESSION_PATH, DEFAULT_SESSION_ROOT)


def write_last_session_name(session_dir: Path) -> None:
    session_store.write_last_session_name(session_dir, LAST_SESSION_PATH)


def infer_section_year_from_session_name(session_name: str) -> tuple[str, int]:
    return session_store.infer_section_year_from_session_name(session_name, DEFAULT_YEAR)


def seed_carry_forward_files_if_needed(session_dir: Path, source_root: Path | None = None) -> bool:
    return session_store.seed_carry_forward_files_if_needed(
        session_dir,
        CARRY_FORWARD_SESSION_FILES,
        source_root=source_root,
    )


def reset_year_sensitive_widget_state() -> None:
    for key in [
        "manual_calendar_day_main",
        "weekday_quick_absence_day",
        "processed_holidays_upload",
        "official_holidays_draft",
        "official_holidays_draft_signature",
        "base_calendar_overrides_draft",
        "base_calendar_overrides_draft_signature",
    ]:
        st.session_state.pop(key, None)


def date_input_value_in_year(widget_key: str, selected_year: int, selected_month: int = 1) -> date:
    fallback = date(selected_year, selected_month, 1)
    value = st.session_state.get(widget_key, fallback)
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date) or value.year != selected_year:
        st.session_state[widget_key] = fallback
        return fallback
    return value


def save_session_folder(
    session_dir: Path,
    year: int,
    month: int,
    include_generated: bool = True,
) -> int:
    return session_store.save_session_folder(
        session_dir,
        year,
        month,
        st.session_state.get("section_name_for_manifest", ""),
        LAST_SESSION_PATH,
        PDF_OUTPUT_DIR,
        include_generated=include_generated,
    )


def save_generated_session_folder(session_dir: Path, year: int, month: int) -> int:
    return save_session_folder(session_dir, year, month, include_generated=True)


def load_session_folder(session_dir: Path, year: int, month: int) -> int:
    return session_store.load_session_folder(session_dir, year, month, PDF_OUTPUT_DIR)


def sync_workspace_to_loaded_session() -> None:
    """Desa el workspace a la sessió CARREGADA actualment (la que es deixa)
    abans de substituir-lo per una altra sessió o de resetejar-lo. Sense
    això, canviar de sessió, de títol o d'any perdria tota la feina feta
    des de l'últim «Generar» (el workspace s'autodesa a disc, però només
    es copiava a la carpeta de sessió en generar)."""
    prev = st.session_state.get("loaded_session_dir")
    if not prev:
        return
    prev_dir = Path(prev)
    if not prev_dir.exists():
        return
    meta = session_store.read_session_metadata(prev_dir)
    _, name_year = infer_section_year_from_session_name(prev_dir.name)
    try:
        prev_year = int(meta.get("year", name_year))
    except (TypeError, ValueError):
        prev_year = name_year
    try:
        session_store.save_session_folder(
            prev_dir,
            prev_year,
            DEFAULT_MONTH,
            meta.get("section", ""),
            LAST_SESSION_PATH,
            PDF_OUTPUT_DIR,
            include_generated=True,
        )
    except OSError:
        st.warning(
            f"No s'ha pogut sincronitzar la sessió anterior «{prev_dir.name}» "
            "abans de canviar. Revisa que cap fitxer no estigui obert a Excel."
        )


def create_empty_session_folder(
    session_dir: Path,
    year: int,
    carry_forward_source: Path | None = None,
    section_name: str | None = None,
) -> None:
    session_store.create_empty_session_folder(
        session_dir,
        year,
        (section_name if section_name is not None
         else st.session_state.get("section_name_for_manifest", "")),
        CARRY_FORWARD_SESSION_FILES,
        carry_forward_source=carry_forward_source,
    )


init_workflow_state()

DEFAULT_SESSION_ROOT.mkdir(parents=True, exist_ok=True)
# Migració única d'arrels antigues (Desktop/Sessions_planificador i
# <paquet>/dades/sessions): si l'arrel actual és buida i l'antiga té
# sessions, es COPIEN aquí. Sense això, actualitzar el programa faria
# aparèixer l'app buida i l'usuari creuria que ha perdut les dades.
_legacy_roots = [_program_folder() / "dades" / "sessions"]
for _env_var in ("USERPROFILE", "HOME"):
    _env_path = os.environ.get(_env_var)
    if _env_path:
        _legacy_roots.append(Path(_env_path).expanduser() / "Desktop" / "Sessions_planificador")
_migrated_n = session_store.migrate_legacy_session_roots(DEFAULT_SESSION_ROOT, _legacy_roots)
if _migrated_n:
    st.toast(
        f"S'han recuperat {_migrated_n} sessió(ns) de la ubicació antiga.",
        icon="📦",
    )
session_folders = session_store.list_session_folders(DEFAULT_SESSION_ROOT)
session_options = [p.name for p in session_folders]
last_session_name = read_last_session_name()
last_session_dir = DEFAULT_SESSION_ROOT / last_session_name if last_session_name else None
last_session_meta = session_store.read_session_metadata(last_session_dir) if last_session_dir else {}
inferred_section, inferred_year = infer_section_year_from_session_name(last_session_name)
initial_section = last_session_meta.get("section") or inferred_section
try:
    initial_year = int(last_session_meta.get("year", inferred_year))
except ValueError:
    initial_year = inferred_year

st.sidebar.markdown(
    """
    <div class="planner-title">Planificador de torns</div>
    """,
    unsafe_allow_html=True,
)
st.session_state.setdefault("section_name_for_manifest", initial_section)
# Traspassem el valor "pendent" al widget abans d'instanciar-lo (Streamlit
# no permet escriure a la clau del widget un cop creat).
_pending_section = st.session_state.pop("_pending_section_name", None)
if _pending_section is not None:
    st.session_state["section_name_for_manifest"] = _pending_section
section_name = st.sidebar.text_input(
    "Títol del calendari",
    key="section_name_for_manifest",
    help="Canviar el títol REANOMENA la sessió actual (no en crea cap de "
         "nova). Per començar una sessió nova, fes servir «➕ Nova sessió».",
)
year = st.sidebar.number_input("Any", min_value=2020, max_value=2100, value=initial_year, step=1)
safe_section_name = "".join(
    c if c.isalnum() or c in {"_", "-"} else "_"
    for c in section_name.strip()
).strip("_") or "Seccio"
default_session_dir = DEFAULT_SESSION_ROOT / f"{safe_section_name}_{year}"
default_session_name = default_session_dir.name
selected_session = ""
session_identity = f"{safe_section_name}_{year}"
previous_session_identity = st.session_state.get("session_identity")
is_app_boot = previous_session_identity is None
session_identity_changed = previous_session_identity != session_identity
preserve_working_state = is_app_boot and session_store.workspace_has_user_data(year)
# Si veníem de l'estat "sense sessió" (eliminada l'última), només sortim
# d'aquest estat quan l'usuari ha escrit un nou títol explícitament. La
# detecció es fa abans del cicle d'identitat per evitar que es netegi
# acabant la identitat reseteja.
if st.session_state.get("no_active_session"):
    if section_name.strip():
        st.session_state.pop("no_active_session", None)
    else:
        st.warning(
            "No hi ha cap sessió activa. Escriu un nom al camp **Títol del "
            "calendari** (sidebar) i prem Enter per crear-ne una de nova."
        )
        st.stop()

# ── Canvi de TÍTOL (mateix any) = REANOMENAR la sessió carregada ──────────
# Editar el títol mai crea una sessió nova (per això hi ha el botó
# «➕ Nova sessió»): la carpeta de la sessió actual es reanomena i tot el
# treball segueix intacte.
_prev_loaded_str = st.session_state.get("loaded_session_dir")
if (
    session_identity_changed
    and not is_app_boot
    and _prev_loaded_str
    and section_name.strip()
):
    _prev_section, _prev_year = infer_section_year_from_session_name(
        previous_session_identity or ""
    )
    _prev_dir = Path(_prev_loaded_str)
    if _prev_year == year and _prev_dir.exists() and _prev_dir != default_session_dir:
        if default_session_dir.exists():
            # toast (no error): sobreviu al st.rerun i l'usuari entén per
            # què el títol «rebota» al valor anterior.
            st.toast(
                f"Ja existeix una sessió «{default_session_dir.name}»: "
                "tria un altre nom o selecciona-la al desplegable.",
                icon="⚠️",
            )
            st.session_state["_pending_section_name"] = _prev_section
            st.rerun()
        _meta = session_store.read_session_metadata(_prev_dir)
        _old_name = _prev_dir.name
        try:
            _prev_dir.rename(default_session_dir)
        except OSError as _exc:
            # Fitxer obert a Excel / lock de sync: mai una pantalla vermella
            # per editar el títol — avisem i restaurem el nom anterior.
            st.toast(
                f"No s'ha pogut reanomenar la sessió ({_exc}). Tanca els "
                "fitxers oberts (Excel) i torna-ho a provar.",
                icon="⚠️",
            )
            st.session_state["_pending_section_name"] = _prev_section
            st.rerun()
        try:
            _m_month = int(_meta.get("month", DEFAULT_MONTH))
        except (TypeError, ValueError):
            _m_month = DEFAULT_MONTH
        (default_session_dir / "session.txt").write_text(
            session_store.session_manifest(year, _m_month, section_name.strip()),
            encoding="utf-8",
        )
        write_last_session_name(default_session_dir)
        st.session_state["loaded_session_dir"] = str(default_session_dir)
        st.session_state["session_identity"] = session_identity
        st.toast(
            f"Sessió reanomenada: «{_old_name}» → «{default_session_dir.name}»",
            icon="✏️",
        )
        st.rerun()

if session_identity_changed:
    reset_year_sensitive_widget_state()
    st.session_state["session_identity"] = session_identity

# Si la identitat acaba de canviar (canvi de títol/any) i la sessió per
# defecte d'aquesta nova identitat encara no existeix, la creem ARA perquè
# el desplegable la pugui mostrar com a seleccionada des del primer cop.
previous_year_session_dir = DEFAULT_SESSION_ROOT / f"{safe_section_name}_{year - 1}"
_carry_pre = previous_year_session_dir if previous_year_session_dir.exists() else None
if _carry_pre is None and last_session_dir and last_session_dir.exists() and last_session_dir != default_session_dir:
    _carry_pre = last_session_dir
if session_identity_changed and not default_session_dir.exists():
    create_empty_session_folder(default_session_dir, year, carry_forward_source=_carry_pre)
    if not preserve_working_state:
        sync_workspace_to_loaded_session()
        session_store.reset_current_workspace_for_new_session(year)
        load_session_folder(default_session_dir, year, DEFAULT_MONTH)
        set_workflow_state(False)
    write_last_session_name(default_session_dir)
    # Refresquem la llista per incloure la nova sessió al desplegable.
    session_folders = session_store.list_session_folders(DEFAULT_SESSION_ROOT)
    session_options = [p.name for p in session_folders]

# Pre-omplim la selecció del desplegable amb la sessió per defecte de la
# nova identitat (si es coneix). Així el desplegable mostra sempre la
# sessió activa sense que l'usuari l'hagi de triar manualment.
_selectbox_key = f"selected_saved_session_{session_identity}"
if session_identity_changed and default_session_name in session_options:
    st.session_state[_selectbox_key] = default_session_name

if session_options:
    default_selected_index = (
        session_options.index(default_session_name)
        if default_session_name in session_options
        else 0
    )
    selected_session = st.sidebar.selectbox(
        "Sessió activa",
        session_options,
        format_func=lambda value: value,
        index=default_selected_index,
        key=_selectbox_key,
    )

session_dir = DEFAULT_SESSION_ROOT / selected_session if selected_session else default_session_dir
previous_year_session_dir = DEFAULT_SESSION_ROOT / f"{safe_section_name}_{year - 1}"
carry_forward_source_dir = previous_year_session_dir if previous_year_session_dir.exists() else None
if carry_forward_source_dir is None and last_session_dir and last_session_dir.exists() and last_session_dir != session_dir:
    carry_forward_source_dir = last_session_dir

# Càrrega de sessió: si la sessió activa difereix de la que estava
# carregada al workspace, recarreguem.
_loaded_key = "loaded_session_dir"
_loaded_prev = st.session_state.get(_loaded_key)
_loaded_now = str(session_dir)
_session_changed = _loaded_prev != _loaded_now

if not session_dir.exists():
    # No existeix: la creem (és nova, o canvi de títol/any sense pre-existent).
    create_empty_session_folder(session_dir, year, carry_forward_source=carry_forward_source_dir)
    if not preserve_working_state:
        sync_workspace_to_loaded_session()
        session_store.reset_current_workspace_for_new_session(year)
        load_session_folder(session_dir, year, DEFAULT_MONTH)
        set_workflow_state(False)
    write_last_session_name(session_dir)
    # Pre-omplir el desplegable perquè la nova sessió hi aparegui com a
    # seleccionada. El selectbox ja s'ha renderitzat amb opcions antigues
    # (sense aquesta sessió), per això cal forçar una nova rerunada.
    st.session_state[f"selected_saved_session_{session_identity}"] = default_session_name
    st.session_state["loaded_session_dir"] = str(session_dir)
    st.rerun()
else:
    # La sessió existeix. Si toca, sembrem dades de carry-forward (només per
    # a la sessió per defecte del títol+any actuals).
    if selected_session == default_session_name or not selected_session:
        seed_carry_forward_files_if_needed(session_dir, carry_forward_source_dir)
    # Carreguem si l'usuari ha canviat de sessió (selectbox) o si l'identitat
    # ha canviat (títol/any). En boot amb workspace ja poblat, preservem.
    needs_load = _session_changed and not preserve_working_state
    if needs_load:
        sync_workspace_to_loaded_session()
        load_session_folder(session_dir, year, DEFAULT_MONTH)
        write_last_session_name(session_dir)
        set_workflow_state(False)
        # Buidar drafts en memòria (incloses les claus per-facultatiu)
        # perquè els editors rellegeixin del disc de la sessió nova.
        from src.ui.session_keys import clear_tab_session_state as _clear_keys
        _clear_keys(st.session_state)
        # Propostes d'equilibri de la sessió ANTERIOR: fora (serien un diff
        # obsolet contra el calendari de la sessió nova).
        from src.services.balance_proposal import discard_proposal as _dp
        _dp()

# Avís de col·lisió de noms: títols diferents poden sanejar-se a la MATEIXA
# carpeta («Equip TC» i «Equip.TC» → Equip_TC_2026) i compartirien dades.
_manifest_section = session_store.read_session_metadata(session_dir).get("section", "")
if (
    _manifest_section
    and section_name.strip()
    and _manifest_section.strip().lower() != section_name.strip().lower()
):
    st.sidebar.warning(
        f"Aquesta sessió es va crear amb el títol «{_manifest_section}» i el "
        f"títol actual és «{section_name.strip()}». Si són seccions diferents, "
        "fes servir títols que no coincideixin en lletres i números."
    )

# Registrem la sessió carregada per a la propera rerunada.
st.session_state[_loaded_key] = _loaded_now

# ── Botó «➕ Nova sessió» ───────────────────────────────────────────────────
# L'única via per crear sessions noves (editar el títol només reanomena).
if not st.session_state.get("_new_session_armed"):
    if st.sidebar.button(
        "➕ Nova sessió",
        key="new_session_btn",
        width="stretch",
        help="Crea una sessió nova buida (l'actual es desa abans). Les "
             "dades mestres (facultatius, regles) es traspassen.",
    ):
        st.session_state["_new_session_armed"] = True
        st.rerun()
else:
    _new_title = st.sidebar.text_input(
        "Nom de la nova sessió",
        key="new_session_name_input",
        placeholder="p. ex. Secció B",
    )
    _ns_ok, _ns_no = st.sidebar.columns(2)
    if _ns_ok.button(
        "Crea",
        type="primary",
        width="stretch",
        key="new_session_create",
        disabled=not str(_new_title or "").strip(),
    ):
        _clean_title = str(_new_title).strip()
        _safe_new = "".join(
            c if c.isalnum() or c in {"_", "-"} else "_" for c in _clean_title
        ).strip("_") or "Seccio"
        _new_dir = DEFAULT_SESSION_ROOT / f"{_safe_new}_{year}"
        if _new_dir.exists():
            st.sidebar.error("Ja existeix una sessió amb aquest nom.")
        else:
            # Desa la sessió actual, crea la nova (amb traspàs de mestres),
            # buida el workspace i carrega-la.
            sync_workspace_to_loaded_session()
            create_empty_session_folder(
                _new_dir, year,
                carry_forward_source=session_dir if session_dir.exists() else None,
                section_name=_clean_title,
            )
            session_store.reset_current_workspace_for_new_session(year)
            load_session_folder(_new_dir, year, DEFAULT_MONTH)
            set_workflow_state(False)
            write_last_session_name(_new_dir)
            from src.ui.session_keys import clear_tab_session_state as _clear_new
            _clear_new(st.session_state)
            st.session_state["_pending_section_name"] = _clean_title
            st.session_state["loaded_session_dir"] = str(_new_dir)
            st.session_state["session_identity"] = f"{_safe_new}_{year}"
            st.session_state.pop("_new_session_armed", None)
            st.toast(f"Sessió nova: «{_new_dir.name}»", icon="🆕")
            st.rerun()
    if _ns_no.button("Cancel·la", width="stretch", key="new_session_cancel"):
        st.session_state.pop("_new_session_armed", None)
        st.rerun()

planning_scope, month, selected_quarter, selected_semester, selected_months, display_month = (
    weekday_scope_values(DEFAULT_MONTH)
)
scope_start_month = selected_months[0]
scope_end_month = selected_months[-1]
month = scope_start_month if planning_scope != "Mes seleccionat" else month

base_calendar_path = Path(f"data/base_calendar_{year}.csv")
unavailability_path = Path(f"data/derived/unavailability_{year}.csv")
preassignments_reconciled_path = Path(f"data/derived/preassignments_weekday_{year}.csv")
weekday_day_info_path = Path("data/weekday/day_info.csv")
weekday_calendar_slots_path = Path("data/weekday/calendar_slots.csv")
professionals_path = Path("data/professionals.csv")
absences_path = Path("data/absences/assignments.csv")
eligibility_path = Path("data/eligibility.csv")
guards_path = Path("data/guards/assignments.csv")
weekly_templates_path = Path("data/weekday/weekly_slot_templates.csv")
slot_catalog_path = Path("data/slot_catalog.csv")

public_holidays_path = Path(f"data/derived/public_holidays_{year}.csv")
base_calendar_overrides_path = Path(f"data/base_calendar_overrides_{year}.csv")
sidebar_actions = render_session_sidebar_actions(session_dir)

if sidebar_actions.save_version_clicked:
    # Primer sincronitzem el treball ACTUAL del workspace a la carpeta de
    # sessió: sense això, la versió fotografiaria l'estat de l'últim
    # «Generar», no el d'ara mateix.
    save_session_folder(session_dir, year, month)
    _snapshot_path = session_store.create_session_snapshot(session_dir)
    if _snapshot_path is not None:
        st.toast(f"Versió {_snapshot_path.name} desada", icon="✅")
    else:
        st.toast("No s'ha pogut desar la versió.", icon="⚠️")
    st.rerun()

if sidebar_actions.restore_clicked and sidebar_actions.selected_snapshot is not None:
    restored = session_store.restore_session_snapshot(
        sidebar_actions.selected_snapshot, session_dir, year, month, PDF_OUTPUT_DIR,
    )
    # Buidar drafts/cachés perquè els editors rellegeixin la versió restaurada.
    from src.ui.session_keys import TAB_SESSION_KEYS as _TAB_KEYS_RESTORE
    for _keys in _TAB_KEYS_RESTORE.values():
        for _k in _keys:
            st.session_state.pop(_k, None)
    st.sidebar.success(
        f"Versió {sidebar_actions.selected_snapshot.name} restaurada "
        f"({restored} fitxers)"
    )
    st.rerun()

if sidebar_actions.delete_session_clicked:
    if session_store.delete_session_folder(session_dir):
        # Reset workspace i drafts perquè la sessió eliminada no quedi
        # repoblada per la memòria en cau.
        session_store.reset_current_workspace_for_new_session(year)
        from src.ui.session_keys import TAB_SESSION_KEYS as _TAB_KEYS_DEL
        for _keys in _TAB_KEYS_DEL.values():
            for _k in _keys:
                st.session_state.pop(_k, None)
        st.session_state.pop("loaded_session_dir", None)
        st.session_state.pop(
            f"selected_saved_session_{session_identity}", None,
        )
        st.session_state.pop("session_identity", None)
        # Mirem si queden altres sessions: si en queda alguna, activem-ne
        # la primera i actualitzem el títol perquè coincideixi. Si no en
        # queda cap, marquem l'estat "sense sessió" per evitar la creació
        # automàtica fins que l'usuari decideixi.
        _remaining = [
            p.name for p in session_store.list_session_folders(DEFAULT_SESSION_ROOT)
        ]
        if _remaining:
            _new_section, _ = infer_section_year_from_session_name(_remaining[0])
            if _new_section:
                # Usem una clau pendent: el widget ja està instanciat en aquesta
                # rerunada. La pròxima rerunada el text_input la consumirà.
                st.session_state["_pending_section_name"] = _new_section
            st.session_state.pop("no_active_session", None)
            st.sidebar.success(f"Sessió «{session_dir.name}» eliminada")
        else:
            st.session_state["_pending_section_name"] = ""
            st.session_state["no_active_session"] = True
            st.sidebar.success(
                f"Sessió «{session_dir.name}» eliminada. No queda cap sessió."
            )
        set_workflow_state(False)
    else:
        st.sidebar.warning("La sessió ja no existia al disc")
    st.rerun()

slot_catalog_df = seed_slot_catalog_if_missing(
    slot_catalog_path,
    weekday_templates_path=weekly_templates_path,
)
# Si l'usuari està editant el catàleg en aquesta sessió i encara no ha
# persistit a disc (autosave en curs, etc.), el DRAFT a session_state és
# la font de veritat més recent. Tots els overrides (area, metric_family,
# review) s'han de derivar del MATEIX df — abans `slot_catalog_df` (disc)
# es feia servir per a area/metric/review i `_catalog_for_options` (draft
# si existia) només per a `catalog_weekday_slots`. Resultat: si marcaves
# una activitat de revisió al catàleg, l'override no s'actualitzava fins
# que es persistia el draft a disc — i les mètriques continuaven sense
# detectar la revisió. Ara unifiquem: tots usen el draft si està viu.
_draft_catalog = st.session_state.get("slot_catalog_draft")
_catalog_for_options = _draft_catalog if isinstance(_draft_catalog, pd.DataFrame) else slot_catalog_df
set_slot_area_overrides(slot_area_map(_catalog_for_options))
set_slot_metric_overrides(slot_metric_family_map(_catalog_for_options))
set_slot_review_overrides(review_slot_ids(_catalog_for_options))
catalog_weekday_slots = weekday_slot_ids(_catalog_for_options)
planner_inputs = load_planner_inputs(
    professionals_path,
    weekly_templates_path,
    eligibility_path,
    catalog_weekday_slots=catalog_weekday_slots,
)
professionals_df = planner_inputs.professionals_df
professional_options = planner_inputs.professional_options
all_professional_options = planner_inputs.all_professional_options
templates_df = planner_inputs.templates_df
eligibility_slots_df = planner_inputs.eligibility_slots_df
existing_slots = planner_inputs.existing_slots
weekday_eligibility_slots = planner_inputs.weekday_eligibility_slots


def _professional_options_from_draft(
    weekday_fallback: list[str],
) -> tuple[list[str], list[str]]:
    """Prefer the live Facultatius draft over the saved CSV so dropdowns in
    Elegibilitat reflect just-typed edits without an extra rerun lag."""
    draft = st.session_state.get("base_professionals_draft")
    if not isinstance(draft, pd.DataFrame) or "professional_id" not in draft.columns:
        return weekday_fallback, sorted(set(weekday_fallback))
    ids = draft["professional_id"].fillna("").astype(str).str.strip().str.upper()
    wkd_mask = draft.get("dies_laborables", pd.Series(True, index=draft.index)).fillna(False).astype(bool)
    valid = (ids != "") & (ids != "NONE")
    weekday = sorted(set(ids[valid & wkd_mask].tolist()))
    return weekday, sorted(set(weekday))


professional_options, all_professional_options = (
    _professional_options_from_draft(professional_options)
)


def save_current_pending_input_drafts(scope_key: str, selected_year: int) -> None:
    save_pending_input_drafts(scope_key)


st.header(section_name or "Planificador de torns")

# «Desar versió» viu ara al desplegable «🕘 Versions de la sessió» del
# sidebar (sidebar_actions.save_version_clicked, gestionat més amunt).

# L'àmbit del calendari (desplegable). Aquests valors s'usen a tot arreu.
with st.expander("Àmbit del calendari", expanded=False):
    (
        planning_scope,
        month,
        selected_quarter,
        selected_semester,
        selected_months,
        display_month,
    ) = render_weekday_scope_controls(session_dir.name, year, DEFAULT_MONTH)
scope_start_month = selected_months[0]
scope_end_month = selected_months[-1]
month = scope_start_month if planning_scope != "Mes seleccionat" else month

(
    slot_catalog_tab,
    professionals_tab,
    data_tab2,
    weekday_calendar_tab,
    final_metrics_tab,
) = st.tabs([
    "Activitat",
    "Facultatius",
    "Restriccions",
    "Calendari",
    "Mètriques",
])

with slot_catalog_tab:
    # NOTA: el sostre de peonades (extraordinary_cap) s'edita ara a
    # Mètriques i canvis finals › Altres restriccions › "Peonades màx./mes".

    _machines_list, _locations_list = render_machines_locations_editor()
    render_slot_catalog_editor(
        slot_catalog_path,
        weekday_templates_path=weekly_templates_path,
        professional_options=all_professional_options,
        machines=_machines_list,
        locations=_locations_list,
        year=year,
    )

with professionals_tab:
    render_professionals_editor(
        professionals_df,
        professionals_path,
        eligibility_path,
        catalog_weekday_slots=catalog_weekday_slots,
    )
    # «Llocs on treballa cada facultatiu», «Slots que es doblen» i
    # «Màquines fixes per facultatiu» viuen a la pestanya Restriccions.

with data_tab2:
    (
        franges_subtab,
        festius_subtab,
        absences_subtab,
        guards_subtab,
        altres_subtab,
    ) = st.tabs(
        [
            "Franges de treball",
            "Festius",
            "Absències",
            "Guàrdies",
            "Altres restriccions",
        ]
    )
    with franges_subtab:
        st.caption(
            "**Com doblar una màquina**: afegeix-hi dues files per al "
            "mateix (dia, franja, slot), una PRESENCIAL i una "
            "NO_PRESENCIAL. El solver hi assignarà dos facultatius "
            "diferents (el segon mostrat amb prefix **T-** si la NP es "
            "flipa a PRES)."
        )
        template_overrides_path = Path(
            f"data/weekday/template_overrides_{year}.csv"
        )
        # Filtrar slots de revisió: no s'assignen a cap franja (s'apliquen
        # al dia sencer des del catàleg) i no compten com a màquina.
        _review_ids = {
            str(s).strip().upper()
            for s in review_slot_ids(_catalog_for_options)
        }
        _existing_non_review = [
            s for s in existing_slots
            if str(s).strip().upper() not in _review_ids
        ]
        if not templates_df.empty and "slot_id" in templates_df.columns:
            _templates_non_review = templates_df[
                ~templates_df["slot_id"].fillna("").astype(str)
                .str.strip().str.upper().isin(_review_ids)
            ].copy()
        else:
            _templates_non_review = templates_df
        render_weekday_work_slot_editor(
            year,
            display_month,
            base_calendar_path,
            public_holidays_path,
            _templates_non_review,
            _existing_non_review,
            weekly_templates_path,
            template_overrides_path,
            invalidate_after_work_slot_change,
        )
        # Canvis puntuals del mes (overrides per a un mes/dia concret).
        # Estructural: forma part del calendari INICIAL (els overrides
        # es consoliden a la generació de templates abans del solver).
        with st.expander("Canvis puntuals del mes", expanded=False):
            st.caption(
                "Modifica les franges per a un mes/dia concret. Aquests "
                "canvis es consoliden al calendari abans del solver i "
                "s'apliquen tant al calendari INICIAL com al DEFINITIU."
            )
            render_weekday_punctual_overrides_editor(
                year,
                display_month,
                base_calendar_path,
                public_holidays_path,
                _templates_non_review,
                _existing_non_review,
                template_overrides_path,
                invalidate_after_work_slot_change,
            )
    with festius_subtab:
        render_holidays_editor(
            year,
            month,
            public_holidays_path,
            base_calendar_overrides_path,
            date_input_value_in_year,
        )
    with absences_subtab:
        st.caption(
            "Restricció estructural: aplica al calendari INICIAL i al "
            "DEFINITIU. Bloqueja les assignacions del facultatiu als "
            "dies indicats (vacances, permisos)."
        )
        render_absences_editor(
            absences_path,
            all_professional_options,
            professionals_path=professionals_path,
            eligibility_path=eligibility_path,
            weekday_unavailability_path=Path("data/weekday/unavailability.csv"),
        )
        warn_absences_vs_initial(absences_path)
    with guards_subtab:
        st.caption(
            "Assigna les guàrdies del mes i genera automàticament la "
            "postguàrdia (bloqueja PRES de l'endemà)."
        )
        render_guards_editor(guards_path, all_professional_options)
        warn_guards_vs_initial(guards_path)

    with altres_subtab:
        # Totes s'apliquen quan cliques Generar a Calendari. TOTES són
        # TOVES, ordenades de MÉS a MENYS pes: el solver les respecta en
        # aquest ordre de prioritat i només infringeix una si la
        # cobertura del calendari ho fa estrictament impossible — cap
        # xoc entre elles pot deixar el solver sense solució.
        st.markdown(
            "##### ⚖️ Restriccions (de més a menys pes — el solver les "
            "respecta en aquest ordre sempre que el calendari ho permet)"
        )
        render_fixed_machines_editor(slot_catalog_path, all_professional_options)
        with st.expander("Canvi d'activitat (manual)", expanded=False):
            st.caption(
                "Edita una assignació concreta del calendari generat. El "
                "canvi es desa com a preassignació; el solver la respectarà "
                "a la pròxima Generació."
            )
            render_schedule_changes_editor(
                year=year,
                month=month,
                selected_months=selected_months,
                professional_options=professional_options,
                all_professional_options=all_professional_options,
            )
        with st.expander("Elegibilitat per activitat", expanded=False):
            st.caption(
                "Defineix quins facultatius poden cobrir cada activitat "
                "(`allowed=0` bloqueja, `allowed=1` permet). Aplica al "
                "calendari inicial i al definitiu. **També serveix per "
                "limitar algú a un lloc concret**: n'hi ha prou amb "
                "bloquejar-li les activitats dels altres llocs."
            )
            render_eligibility_editor(
                eligibility_path,
                professional_options,
                weekday_eligibility_slots,
                "weekday",
            )
            warn_eligibility_vs_initial(eligibility_path)
        with st.expander(
            "Dies de la setmana no-presencials per facultatiu",
            expanded=False,
        ):
            render_no_pres_weekdays_editor(
                professionals_path, eligibility_path,
            )
            warn_no_pres_weekday_vs_initial(professionals_path)
        with st.expander(
            "Dies de la setmana presencials per facultatiu",
            expanded=False,
        ):
            render_pres_weekdays_editor(
                professionals_path, eligibility_path,
            )
            warn_pres_weekday_vs_initial(professionals_path)
        with st.expander("Roda d'assignació (torns rotatoris)", expanded=False):
            from src.ui.wheel_editor import render_wheel_editor
            render_wheel_editor(existing_slots, professional_options)
        with st.expander("Regles d'equilibri de la càrrega", expanded=False):
            st.caption(
                "**Quantes** màquines o presencials toquen a cadascú "
                "(repartides segons la jornada). És diferent dels **dies "
                "NP/PRES** de sobre, que fixen **quins dies** ve cada "
                "facultatiu: per això pesen més que l'equilibri — si xoquen, "
                "mana la preferència personal."
            )
            render_planning_rules_editor(Path("data/planning_rules.csv"))
        with st.expander("Comitès", expanded=False):
            render_comite_editor(
                professional_options=professional_options,
                all_professional_options=all_professional_options,
                catalog_weekday_slots=catalog_weekday_slots,
            )

        st.markdown("##### ⚙️ Configuració")
        with st.expander("Peonades/mes (jornada completa)", expanded=False):
            render_peonada_cap_editor()
        with st.expander("Màquines que es doblen per facultatiu", expanded=False):
            render_doubled_machines_section(
                professionals_path,
                eligibility_path,
                catalog_weekday_slots=catalog_weekday_slots,
            )
        with st.expander("Comodí (fallback)", expanded=False):
            render_comodi_editor(professionals_path)

with weekday_calendar_tab:
    render_weekday_planning_tab(
        year,
        month,
        selected_months,
        display_month,
        scope_start_month,
        scope_end_month,
        public_holidays_path,
        base_calendar_overrides_path,
        base_calendar_path,
        absences_path,
        guards_path,
        professional_options,
        session_dir,
        save_current_pending_input_drafts,
        save_session_folder,
        save_generated_session_folder,
        PDF_OUTPUT_DIR,
        professionals_path,
        DESKTOP_DIR,
        all_professional_options=all_professional_options,
    )
    # (Els comptadors per facultatiu s'han mogut a la pestanya «Mètriques
    # i canvis finals», dins un desplegable.)
    # Ajustos ràpids sota el render — TOTS sense solver: absència/guàrdia
    # es registren a dades i buiden les caselles afectades a l'instant;
    # canvi puntual, peonada i presencialitat editen el calendari
    # directament. El solver només ho considera en tornar a «Generar».
    render_quick_add_panels(
        year,
        month,
        selected_months,
        professional_options,
        all_professional_options,
        professionals_path,
        PDF_OUTPUT_DIR,
        absences_path,
        guards_path,
    )

with final_metrics_tab:
    render_weekday_metrics(
        year,
        month,
        scope_start_month,
        scope_end_month,
        selected_months,
        public_holidays_path,
        base_calendar_overrides_path,
        base_calendar_path,
        session_dir,
        save_generated_session_folder,
        PDF_OUTPUT_DIR,
        professionals_path,
    )

# ── Tancament segur (botó «⏻ Tancar el programa» del sidebar) ──────────────
# S'executa al FINAL del run: tots els autosaves dels editors d'aquest
# mateix rerun ja s'han aplicat, i el workspace se sincronitza a la sessió
# abans d'apagar el servidor.
if st.session_state.pop("_app_exit_requested", False):
    try:
        save_session_folder(session_dir, year, month)
    except OSError:
        pass  # apagar igualment: el workspace a disc ja té els autosaves
    st.sidebar.success("Programa aturat. Ja pots tancar aquesta pestanya.")
    import threading as _threading
    import time as _time

    def _shutdown_server() -> None:
        _time.sleep(1.0)  # deixa que el missatge arribi al navegador
        os._exit(0)

    _threading.Thread(target=_shutdown_server, daemon=True).start()

st.stop()
