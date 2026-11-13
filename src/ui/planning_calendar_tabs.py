from collections.abc import Callable
from pathlib import Path
import shutil

import pandas as pd
import streamlit as st

from src.services.generation_inputs import ensure_generation_inputs
from src.services.planning_commands import (
    general_pdf_export_steps,
    prepare_pipeline_steps,
    weekday_planning_step,
)
from src.services.schedule_editing import schedule_readjustment_report
from src.ui.command_progress import run_and_store
from src.ui.table_state import data_editor_height


@st.cache_data(show_spinner=False, max_entries=12)
def _pdf_page_pngs(path: str, mtime_ns: int, size: int) -> list[bytes]:
    """Pàgines d'un PDF del calendari com a PNG (PyMuPDF). En memòria cau
    per (fitxer, data, mida): abans es tornava a rasteritzar a cada clic, i
    ara que es mostren tots els mesos de l'àmbit es notaria."""
    import fitz
    with fitz.open(path) as doc:
        return [page.get_pixmap(dpi=450).tobytes("png") for page in doc]


_PDF_SAVE_DIR_FILE = Path("data/pdf_save_dir.txt")


def _load_pdf_save_dir(default: Path) -> str:
    """Ruta de la carpeta on l'usuari vol guardar els PDF (recordada a disc)."""
    try:
        if _PDF_SAVE_DIR_FILE.exists() and _PDF_SAVE_DIR_FILE.stat().st_size:
            value = _PDF_SAVE_DIR_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    return str(default)


def _save_pdf_save_dir(value: str) -> None:
    try:
        _PDF_SAVE_DIR_FILE.parent.mkdir(parents=True, exist_ok=True)
        if (
            not _PDF_SAVE_DIR_FILE.exists()
            or _PDF_SAVE_DIR_FILE.read_text(encoding="utf-8") != value
        ):
            _PDF_SAVE_DIR_FILE.write_text(value, encoding="utf-8")
    except OSError:
        pass


def _collect_tagged_lines(tag: str, n_fields: int) -> list[tuple]:
    """Línies que el pipeline marca com 'TAG<TAB>camp1<TAB>...' a stdout/stderr;
    retorna les tuples dels primers n_fields camps, úniques i ordenades."""
    out = str(st.session_state.get("last_action_stdout", "") or "")
    err = str(st.session_state.get("last_action_stderr", "") or "")
    prefix = tag + "\t"
    found = []
    for line in (out + "\n" + err).splitlines():
        line = line.strip()
        if line.startswith(prefix):
            parts = line.split("\t")
            if len(parts) > n_fields:
                found.append(tuple(parts[1:1 + n_fields]))
    return sorted(set(found))


def _notify_guard_absence_conflicts(container) -> None:
    """Mostra un avís si el pas de preparació ha detectat que un facultatiu
    té una guàrdia/reforç/postguàrdia i una absència el mateix dia."""
    conflicts = _collect_tagged_lines("CONFLICTE_GUARDIA_ABSENCIA", 2)
    if not conflicts:
        return
    ctx = container if container is not None else st
    detall = "\n".join(f"- {prof} el {day}" for prof, day in conflicts)
    ctx.warning(
        f"⚠️ {len(conflicts)} conflicte(s) entre guàrdia i "
        f"indisponibilitat (mateix facultatiu i dia):\n{detall}"
    )


def _notify_presencial_flips(container) -> None:
    """Avisa si el solver ha convertit activitats no-presencials ordinàries
    a presencials per assolir el target presencial d'algun facultatiu."""
    flips = _collect_tagged_lines("FLIP_PRESENCIAL", 3)
    if not flips:
        return
    ctx = container if container is not None else st
    detall = "\n".join(f"- {prof} · {day} · {slot}" for prof, day, slot in flips[:12])
    if len(flips) > 12:
        detall += f"\n- … i {len(flips) - 12} més"
    ctx.info(
        f"ℹ️ {len(flips)} activitat(s) no presencial(s) convertida(es) a "
        f"presencial per assolir l'objectiu de presencials:\n{detall}"
    )


def rerender_pdf_after_edit(
    before: pd.DataFrame | None,
    professionals_path: Path,
    pdf_output_dir: Path,
    year: int,
    selected_months: list[int],
) -> int:
    """Després d'un canvi a mà al calendari (ja desat): torna a fer el PDF
    dels mesos de l'àmbit I dels mesos on hi ha hagut canvis. Abans només
    es feia el de l'àmbit (o cap, des de «Canvi d'activitat»), i un canvi
    en un altre mes deixava el seu PDF desfasat respecte del calendari i
    de l'Excel."""
    from src.services.schedule_editing import changed_months
    schedule_path = Path("outputs/schedule_weekday.csv")
    try:
        after = pd.read_csv(schedule_path, dtype=str)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        after = None
    months = sorted(set(selected_months) | changed_months(before, after, year))
    return export_general_weekday_pdf(
        schedule_path, professionals_path, pdf_output_dir, year, months,
    )


def _notify_uncovered(container) -> None:
    """Avisa, en vermell, de les activitats que el solver ha deixat SENSE
    COBRIR perquè no hi havia cap facultatiu disponible (potser són
    màquines a tancar aquell dia), agrupades per dia i amb el motiu."""
    from src.domain.schedule_format import calendar_display_franja_label
    holes = _collect_tagged_lines("SENSE_COBRIR", 4)
    if not holes:
        return
    # Per dia i motiu (una roda i un dèficit general poden coincidir).
    by_day: dict = {}
    for day, franja, slot, why in holes:
        fr = calendar_display_franja_label(franja)
        by_day.setdefault((day, why), []).append(f"{slot} ({fr})" if fr else slot)
    detall = "\n".join(
        f"- **{day}**: {', '.join(slots)}" + (f" — {why}" if why != "-" else "")
        for (day, why), slots in sorted(by_day.items())
    )
    ctx = container if container is not None else st
    ctx.error(
        f"🔴 {len(holes)} activitat(s) SENSE COBRIR: ningú no la pot fer, ni "
        "tan sols amb doble feina. Surten en vermell al calendari, al PDF i "
        f"a l'Excel (potser cal tancar aquestes activitats aquells dies):\n{detall}"
    )


def _notify_double_shifts(container) -> None:
    """Avisa de les DOBLES FEINES: no hi havia prou facultatius i algú
    assumeix més d'una activitat a la mateixa franja (o més d'una
    presencial el dia), agrupades per dia i amb el motiu."""
    doubles = _collect_tagged_lines("DOBLE_FEINA", 4)
    if not doubles:
        return
    detall = "\n".join(
        f"- **{day}**: {prof} fa {what}" + (f" — {why}" if why != "-" else "")
        for day, prof, what, why in doubles
    )
    ctx = container if container is not None else st
    ctx.warning(
        f"⚠️ {len(doubles)} doble(s) feina(es): no hi havia prou facultatius "
        f"i algú assumeix més d'una activitat:\n{detall}"
    )


def _redraw_outdated_pdfs(
    weekday_schedule_path: Path,
    professionals_path: Path,
    pdf_output_dir: Path,
    year: int,
    months: list[int],
    container=None,
) -> None:
    """Si el codi que dibuixa el PDF és més nou que el PDF desat (p. ex.
    després d'actualitzar el programa, que n'ha canviat el disseny), torna
    a dibuixar els PDF d'aquests mesos. Només un intent per sessió i versió:
    si fallés, no es reintenta a cada clic."""
    import src.tools.export_monthly_pdfs as _exporter
    code_mtime = Path(_exporter.__file__).stat().st_mtime
    pdf_dir = pdf_output_dir / "entre_setmana"
    stale = [
        m for m in months
        if (pdf_dir / f"general_calendar_{year}_{m:02d}.pdf").exists()
        and (pdf_dir / f"general_calendar_{year}_{m:02d}.pdf").stat().st_mtime < code_mtime
    ]
    tried = st.session_state.setdefault("pdf_redraw_tried", set())
    stale = [m for m in stale if (year, m, code_mtime) not in tried]
    if not stale or not Path(weekday_schedule_path).exists():
        return
    tried.update((year, m, code_mtime) for m in stale)
    export_general_weekday_pdf(
        weekday_schedule_path, professionals_path, pdf_output_dir,
        year, stale, container=container,
    )


def export_general_weekday_pdf(
    weekday_schedule_path: Path,
    professionals_path: Path,
    pdf_output_dir: Path,
    year: int,
    selected_months: list[int],
    container=None,
    show_operational_overlays: bool = True,
) -> int:
    """Genera el PDF clàssic (calendari general) d'entre setmana al directori
    intern de l'app perquè el visualitzador el mostri.

    `show_operational_overlays=False` amaga absències/guàrdies/PG al PDF:
    s'usa per al calendari INICIAL, on el solver no les ha considerat."""
    return run_and_store(
        "Exportar PDF d'entre setmana",
        general_pdf_export_steps(
            weekday_schedule_path,
            professionals_path,
            pdf_output_dir / "entre_setmana",
            year,
            selected_months,
            weekdays_only=True,
            show_operational_overlays=show_operational_overlays,
        ),
        completed_key="step_pdfs",
        total_steps=max(2, len(selected_months)),
        container=container,
    )


# NOTA: sense caller a la UI des que els Ajustos ràpids apliquen substitut
# directe (v1.6.0). Es conserva deliberadament com a motor del reajust amb
# estabilitat per si es reintrodueix el botó; si d'aquí a unes versions
# ningú no l'usa, elimineu-la juntament amb schedule_weekday_before_reajust.
def run_weekday_regenerate(
    label: str,
    year: int,
    scope_start_month: int,
    scope_end_month: int,
    selected_months: list[int],
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    base_calendar_path: Path,
    session_dir: Path,
    month: int,
    save_generated_session_folder: Callable[[Path, int, int], int],
    pdf_output_dir: Path,
    professionals_path: Path,
    container=None,
    keep_restriction: str | None = None,
) -> int:
    """Regenera el planning d'entre setmana. UN únic calendari
    (`outputs/schedule_weekday.csv`) que acumula totes les restriccions.

    Abans de regenerar, fa un snapshot del calendari actual a
    `outputs/schedule_weekday_prev.csv` per al botó «Desfer».

    El paràmetre `keep_restriction` es manté per compatibilitat amb
    els botons per-desplegable, però ja no té efecte: totes les
    restriccions s'apliquen sempre."""
    weekday_schedule_path = Path("outputs/schedule_weekday.csv")
    prev_path = Path("outputs/schedule_weekday_prev.csv")
    stability_path = Path("outputs/schedule_weekday_before_reajust.csv")
    # ── Snapshot UNDO: copiem el calendari actual a _prev abans de
    # regenerar perquè el botó "Desfer" pugui restaurar-lo.
    if weekday_schedule_path.exists() and weekday_schedule_path.stat().st_size > 0:
        shutil.copyfile(weekday_schedule_path, prev_path)
        shutil.copyfile(weekday_schedule_path, stability_path)
        # Backup PDFs també.
        try:
            prev_pdf_dir = pdf_output_dir / "entre_setmana_prev"
            current_pdf_dir = pdf_output_dir / "entre_setmana"
            if current_pdf_dir.exists():
                prev_pdf_dir.mkdir(parents=True, exist_ok=True)
                for pdf in current_pdf_dir.glob("*.pdf"):
                    shutil.copyfile(pdf, prev_pdf_dir / pdf.name)
        except OSError:
            pass
    steps = [
        *prepare_pipeline_steps(
            year,
            public_holidays_path,
            base_calendar_overrides_path,
            base_calendar_path,
        ),
        weekday_planning_step(
            year,
            scope_start_month,
            scope_end_month,
            stability_from=stability_path if stability_path.exists() else None,
            keep_restriction=keep_restriction,
            max_seconds=st.session_state.get("solver_max_seconds", 180),
            warm_start=st.session_state.get("solver_warm_start", False),
        ),
    ]
    run_and_store(
        label,
        steps,
        completed_key="step_planning",
        total_steps=len(selected_months) + 3,
        container=container,
    )
    if st.session_state.get("last_action_code") == 0:
        st.session_state["step_metrics"] = False
        st.session_state.pop("weekday_live_schedule", None)
        # Informe de què ha canviat el solver vs el calendari anterior.
        if stability_path.exists() and stability_path.stat().st_size > 0:
            st.session_state["weekday_reajust_report"] = schedule_readjustment_report(
                stability_path,
                weekday_schedule_path,
                ["day", "franja", "slot_id", "presentiality", "work_mode"],
                pd.DataFrame(),
            )
        _notify_guard_absence_conflicts(container)
        _notify_presencial_flips(container)
        _notify_double_shifts(container)
        _notify_uncovered(container)
        # Genera el PDF (subdir entre_setmana, l'únic que utilitzem).
        export_general_weekday_pdf(
            weekday_schedule_path, professionals_path, pdf_output_dir,
            year, selected_months, container=container,
        )
        save_generated_session_folder(session_dir, year, month)
        return 0
    return int(st.session_state.get("last_action_code", 1))


def run_weekday_undo(pdf_output_dir: Path) -> bool:
    """Desfà l'últim Regenerar restaurant `schedule_weekday.csv` (i el
    seu PDF) des del snapshot `_prev`. Retorna True si s'ha restaurat,
    False si no hi havia snapshot disponible.

    Nota: és un undo de NIVELL ÚNIC. Si fas Regenerar→Undo→Undo, el segon
    undo no torna més enrere (perquè cada Regenerar reescriu el snapshot)."""
    prev_path = Path("outputs/schedule_weekday_prev.csv")
    schedule_path = Path("outputs/schedule_weekday.csv")
    if not (prev_path.exists() and prev_path.stat().st_size > 0):
        return False
    shutil.copyfile(prev_path, schedule_path)
    # Restaura PDFs també.
    try:
        prev_pdf_dir = pdf_output_dir / "entre_setmana_prev"
        current_pdf_dir = pdf_output_dir / "entre_setmana"
        if prev_pdf_dir.exists():
            current_pdf_dir.mkdir(parents=True, exist_ok=True)
            for pdf in prev_pdf_dir.glob("*.pdf"):
                shutil.copyfile(pdf, current_pdf_dir / pdf.name)
    except OSError:
        pass
    # Invalidem l'informe de canvis (no és coherent post-undo).
    st.session_state.pop("weekday_reajust_report", None)
    st.session_state.pop("weekday_live_schedule", None)
    return True


def has_undo_available() -> bool:
    """True si hi ha snapshot `_prev` per desfer."""
    prev_path = Path("outputs/schedule_weekday_prev.csv")
    return prev_path.exists() and prev_path.stat().st_size > 0


def _render_balance_proposal_panel(
    weekday_schedule_path,
    professionals_path,
    pdf_output_dir,
    year,
    selected_months,
    session_dir,
    month,
    save_generated_session_folder,
) -> None:
    """Panell d'ACCEPTACIÓ de les regles d'equilibri: quan hi ha un mode
    actiu, «Generar» deixa el calendari BASE (segons les franges) com a
    actiu i una PROPOSTA amb l'equilibri aplicat. Aquí es mostren els
    canvis exactes i l'usuari decideix si s'apliquen o no."""
    from src.services import balance_proposal as bp

    # Mode «No equilibrar»: mai propostes — si en queda una d'antiga (p. ex.
    # generada abans de canviar el mode), s'esborra en silenci.
    from src.domain.planning_rules import PlanningRules
    if PlanningRules.from_csv(Path("data/planning_rules.csv")).mode == "none":
        if bp.proposal_exists():
            bp.discard_proposal()
        return

    if not bp.proposal_exists():
        return
    diff = bp.load_proposal_diff()
    with st.container(border=True):
        st.markdown("#### ⚖️ Regles d'equilibri: proposta de canvis")
        if diff.empty:
            st.success(
                "Les regles d'equilibri no canvien res: el calendari generat "
                "segons les franges ja compleix l'equilibri triat."
            )
            if st.button("Entesos", key="bp_ack", width="stretch"):
                bp.discard_proposal()
                st.rerun()
            return
        st.caption(
            f"Per complir les regles d'equilibri caldria fer **{len(diff)} "
            "canvi(s)** sobre el calendari generat segons les franges. "
            "Revisa'ls i decideix:"
        )
        st.dataframe(
            diff,
            hide_index=True,
            width="stretch",
            height=min(330, 60 + 35 * len(diff)),
        )
        col_apply, col_keep = st.columns(2)
        if col_apply.button(
            f"✅ Aplicar l'equilibri ({len(diff)} canvis)",
            type="primary", width="stretch", key="bp_apply",
        ):
            n = bp.apply_proposal()
            export_general_weekday_pdf(
                weekday_schedule_path, professionals_path, pdf_output_dir,
                year, selected_months,
            )
            save_generated_session_folder(session_dir, year, month)
            st.session_state.pop("weekday_live_schedule", None)
            st.toast(f"Equilibri aplicat: {n} canvis", icon="✅")
            st.rerun()
        if col_keep.button(
            "✋ Mantenir el calendari segons les franges",
            width="stretch", key="bp_discard",
        ):
            bp.discard_proposal()
            st.toast(
                "Proposta descartada: es manté el calendari de les franges",
                icon="🗂️",
            )
            st.rerun()


def _render_pdf_save_dir(pdf_default_save_dir: Path) -> Path:
    """Carpeta on es guarden els PDF i l'Excel: es tria amb la finestra
    de Windows («📂 Canviar carpeta…») i es recorda a disc. Si la
    finestra no es pot obrir, el camp passa a ser editable."""
    if "pdf_save_dir_input" not in st.session_state:
        st.session_state["pdf_save_dir_input"] = _load_pdf_save_dir(pdf_default_save_dir)

    def _choose_pdf_save_dir() -> None:
        from src.services.folder_picker import FolderPickerUnavailable, pick_folder
        try:
            chosen = pick_folder(
                st.session_state.get("pdf_save_dir_input"),
                "Tria la carpeta on desar els PDF i l'Excel",
            )
        except FolderPickerUnavailable:
            st.session_state["pdf_save_dir_manual"] = True
            return
        if chosen:
            st.session_state["pdf_save_dir_input"] = chosen

    _manual_dir = st.session_state.get("pdf_save_dir_manual", False)
    c_dir, c_pick = st.columns([5, 1.3], vertical_alignment="bottom")
    with c_dir:
        pdf_save_dir_value = st.text_input(
            "Carpeta on desar els PDF i l'Excel",
            key="pdf_save_dir_input",
            disabled=not _manual_dir,
            help="Prem «Canviar carpeta…» per triar-la amb la finestra de "
                 "Windows. Es recorda per a la pròxima vegada.",
        )
    with c_pick:
        st.button(
            "📂 Canviar carpeta…", key="pdf_save_dir_pick",
            on_click=_choose_pdf_save_dir, width="stretch",
        )
    if _manual_dir:
        st.caption(
            "No s'ha pogut obrir la finestra de Windows: escriu la ruta de "
            "la carpeta aquí sobre."
        )
    pdf_save_dir = (
        Path(pdf_save_dir_value.strip())
        if pdf_save_dir_value.strip()
        else pdf_default_save_dir
    )
    # Autosave de la carpeta: persisteix immediatament si l'usuari l'edita.
    _disk_pdf_dir = _load_pdf_save_dir(pdf_default_save_dir)
    if str(pdf_save_dir) != _disk_pdf_dir:
        _save_pdf_save_dir(str(pdf_save_dir))
    return pdf_save_dir


def render_weekday_planning_tab(
    year: int,
    month: int,
    selected_months: list[int],
    display_month: int,
    scope_start_month: int,
    scope_end_month: int,
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    base_calendar_path: Path,
    absences_path: Path,
    guards_path: Path,
    professional_options: list[str],
    session_dir: Path,
    save_pending_input_drafts: Callable[[str, int], None],
    save_session_folder: Callable[..., int],
    save_generated_session_folder: Callable[[Path, int, int], int],
    pdf_output_dir: Path,
    professionals_path: Path,
    pdf_default_save_dir: Path,
    all_professional_options: list[str] | None = None,
) -> None:
    weekday_schedule_path = Path("outputs/schedule_weekday.csv")
    schedule_exists = (
        weekday_schedule_path.exists() and weekday_schedule_path.stat().st_size > 0
    )
    # Mode «activitat» sense activitat vàlida: la generació funcionaria però
    # l'equilibri per activitat quedaria silenciosament inert — avisem aquí,
    # no només dins l'editor de regles (que potser no s'obre).
    from src.domain.planning_rules import PlanningRules
    _rules_gen = PlanningRules.from_csv(Path("data/planning_rules.csv"))
    if _rules_gen.mode == "activitat":
        from src.services.slot_catalog import load_slot_catalog, weekday_slot_ids
        try:
            _act_opts = weekday_slot_ids(
                load_slot_catalog(Path("data/slot_catalog.csv"))
            )
        except Exception:
            _act_opts = []
        if not _rules_gen.balance_activity:
            st.warning(
                "Les regles d'equilibri estan en mode «activitat» però no "
                "hi ha cap activitat triada: en generar no s'aplicarà cap "
                "equilibri per activitat. Tria-la a Restriccions › Altres "
                "restriccions › Regles d'equilibri de la càrrega."
            )
        elif _rules_gen.balance_activity not in _act_opts:
            st.warning(
                f"L'activitat de l'equilibri «{_rules_gen.balance_activity}» "
                "ja no és al catàleg: l'equilibri per activitat no tindrà "
                "efecte. Revisa Restriccions › Altres restriccions › Regles "
                "d'equilibri de la càrrega."
            )
    gen_btn_col, exp_general_col, exp_byprof_col, gen_progress_col = st.columns(
        [1, 1, 1, 2]
    )
    with gen_btn_col:
        generate_weekday_requested = st.button(
            "Generar",
            width="stretch",
            key="generate_weekday_planning",
            type="primary",
        )
    with exp_general_col:
        export_general_requested = st.button(
            "Desar PDF",
            width="stretch",
            key="export_weekday_general_pdf",
            disabled=not schedule_exists,
        )
    with exp_byprof_col:
        export_excel_requested = st.button(
            "Desar Excel",
            width="stretch",
            key="export_weekday_excel",
            disabled=not schedule_exists,
            help="Genera un .xlsx amb una fulla mestra «Calendari» i "
                 "una fulla per cada facultatiu amb la seva agenda.",
        )
    gen_progress_box = gen_progress_col.container()
    # Avisos llargs (doble feina, SENSE COBRIR) a tota l'amplada, sota els
    # botons: a la columna de progrés quedaven estrets i molt llargs.
    gen_notices_box = st.container()

    # Qualitat del solver: temps per mes. Només dues opcions: per a més
    # qualitat es torna a Generar amb «Millorar el calendari actual», que
    # parteix del calendari ja fet i no en perd la feina.
    _QUALITY_SECONDS = {
        "Ràpid (~60 s/mes)": 60,
        "Equilibrat (~180 s/mes)": 180,
    }
    _quality_label = st.selectbox(
        "Qualitat (temps de solver per mes)",
        list(_QUALITY_SECONDS.keys()),
        index=1,
        key="solver_quality_choice",
        help="Més temps deixa que el solver reparteixi millor la càrrega. "
             "**Per a més qualitat**, torna a prémer **Generar** amb "
             "«Millorar el calendari actual» marcat: parteix del calendari "
             "que ja tens i el millora, sense perdre la feina feta.",
    )
    st.session_state["solver_max_seconds"] = _QUALITY_SECONDS[_quality_label]

    # Warm-start: en lloc de recomençar de zero, parteix del calendari ja
    # generat i el MILLORA (clics repetits el refinen progressivament).
    st.checkbox(
        "Millorar el calendari actual (en lloc de començar de nou)",
        value=False,
        key="solver_warm_start",
        disabled=not schedule_exists,
        help="Parteix del calendari actual (no el força, només l'aprofita) "
             "i el refina: és la manera de guanyar qualitat sense perdre la "
             "feina feta. Si el marques i tornes a clicar Generar diverses "
             "vegades, cada cop millora una mica més. Desmarcat = generació "
             "nova des de zero.",
    )

    pdf_save_dir = _render_pdf_save_dir(pdf_default_save_dir)

    # NOTA: la tolerància ε s'ha mogut a Mètriques i canvis finals
    # › Altres restriccions › "Tolerància ε" (és un paràmetre que se
    # sol ajustar després del calendari inicial, per relaxar el target).

    def _ensure_pdf_save_dir() -> bool:
        _save_pdf_save_dir(str(pdf_save_dir))
        try:
            pdf_save_dir.mkdir(parents=True, exist_ok=True)
            return True
        except OSError as exc:
            st.error(f"No s'ha pogut accedir a la carpeta «{pdf_save_dir}»: {exc}")
            return False

    if export_general_requested and _ensure_pdf_save_dir():
        # El PDF clàssic ja s'ha renderitzat en generar/reajustar: el copiem a
        # la carpeta triada (instantani). Si no hi és, el generem.
        from src.domain.month_scope import catalan_month_name
        _redraw_outdated_pdfs(
            weekday_schedule_path, professionals_path, pdf_output_dir,
            year, selected_months, container=gen_progress_box,
        )
        src_dir = pdf_output_dir / "entre_setmana"
        copied = []
        for _m in selected_months:
            _src = src_dir / f"general_calendar_{year}_{_m:02d}.pdf"
            if _src.exists() and _src.stat().st_size > 0:
                _name = catalan_month_name(_m)
                # L'ANY va al nom: ara una mateixa sessió conté diversos
                # anys i, sense ell, l'octubre del 2027 sobreescriuria el
                # del 2026 a la carpeta de destí.
                _dest = f"calendari {_name} {year}.pdf" if _name else _src.name
                shutil.copyfile(_src, pdf_save_dir / _dest)
                copied.append(_dest)
        if copied:
            st.toast(
                f"PDF desat a {pdf_save_dir} ({len(copied)} mes/os)",
                icon="✅",
            )
        else:
            code = run_and_store(
                "Desar PDF",
                general_pdf_export_steps(
                    weekday_schedule_path,
                    professionals_path,
                    pdf_save_dir,
                    year,
                    selected_months,
                    weekdays_only=True,
                ),
                completed_key="step_pdfs",
                total_steps=max(2, len(selected_months)),
                container=gen_progress_box,
            )
            if code == 0:
                st.toast(f"PDF desat a {pdf_save_dir}", icon="✅")

    if export_excel_requested and _ensure_pdf_save_dir():
        from src.domain.month_scope import catalan_months_label
        from src.services.excel_export import export_schedule_to_excel
        _label = catalan_months_label(selected_months)
        # Amb l'any: una mateixa sessió conté diversos anys i el fitxer
        # d'un any no ha de trepitjar el d'un altre.
        _label = f"{_label} {year}" if _label else str(year)
        _xlsx_path = pdf_save_dir / f"calendari {_label}.xlsx"
        try:
            n_rows = export_schedule_to_excel(
                weekday_schedule_path,
                _xlsx_path,
                selected_months=selected_months,
                year=year,
            )
        except Exception as exc:
            st.error(f"No s'ha pogut generar l'Excel: {exc}")
            n_rows = 0
        if n_rows > 0:
            st.toast(
                f"Excel desat a {_xlsx_path} ({n_rows} files)",
                icon="✅",
            )
        elif n_rows == 0:
            st.warning(
                "No hi ha files al calendari per exportar (genera primer "
                "el calendari)."
            )

    st.divider()
    # Proposta de les regles d'equilibri pendent d'acceptar (si n'hi ha).
    _render_balance_proposal_panel(
        weekday_schedule_path, professionals_path, pdf_output_dir,
        year, selected_months, session_dir, month,
        save_generated_session_folder,
    )
    # El PDF renderitzat es mostra a sota. L'edició d'assignacions s'ha mogut
    # a la pestanya "Mètriques i canvis".
    calendar_container = st.container()
    if not schedule_exists:
        st.session_state.pop("weekday_live_schedule", None)

    if generate_weekday_requested:
        save_pending_input_drafts("save_weekday_inputs_tab", year)
        save_session_folder(
            session_dir,
            year,
            month,
            include_generated=False,
        )
        ensure_generation_inputs(
            public_holidays_path,
            base_calendar_overrides_path,
            absences_path,
            guards_path,
            Path("data/weekday/preassignments.csv"),
        )
        weekday_steps = [
            *prepare_pipeline_steps(
                year,
                public_holidays_path,
                base_calendar_overrides_path,
                base_calendar_path,
            ),
            weekday_planning_step(
                year, scope_start_month, scope_end_month,
                initial=True,  # IGNORA restriccions opcionals (Mètriques).
                max_seconds=st.session_state.get("solver_max_seconds", 180),
                warm_start=st.session_state.get("solver_warm_start", False),
            ),
        ]
        code = run_and_store(
            "Generar planning d'entre setmana",
            weekday_steps,
            completed_key="step_planning",
            total_steps=len(selected_months) + 3,
            container=gen_progress_box,
        )
        if code == 0:
            st.session_state["step_base_calendar"] = True
            st.session_state["step_details_confirmed"] = True
            st.session_state["step_module_calendars"] = True
            st.session_state["step_operational_constraints"] = True
            st.session_state["step_pdfs"] = False
            st.session_state["step_metrics"] = False
            st.session_state.pop("weekday_live_schedule", None)
            # Una generació completa no és un reajust: invalidem l'informe.
            st.session_state.pop("weekday_reajust_report", None)
            _notify_guard_absence_conflicts(gen_progress_box)
            _notify_presencial_flips(gen_progress_box)
            _notify_double_shifts(gen_notices_box)
            _notify_uncovered(gen_notices_box)
            # Genera el PDF perquè es vegi directament a l'app
            # (visualitzador de sota).
            export_general_weekday_pdf(
                weekday_schedule_path, professionals_path, pdf_output_dir,
                year, selected_months, container=gen_progress_box,
            )
            # Es guarda després del PDF perquè el renderitzat quedi inclòs a
            # la sessió i es restauri en reobrir.
            save_generated_session_folder(session_dir, year, month)

    with calendar_container:
        _redraw_outdated_pdfs(
            weekday_schedule_path, professionals_path, pdf_output_dir,
            year, selected_months, container=gen_progress_box,
        )
        _pdf_dir = pdf_output_dir / "entre_setmana"
        # Tots els mesos de l'àmbit (un trimestre = 3 calendaris, un sota
        # l'altre), no només el «mes a visualitzar».
        _pdfs = [
            p for p in (
                _pdf_dir / f"general_calendar_{year}_{m:02d}.pdf"
                for m in selected_months
            )
            if p.exists() and p.stat().st_size > 0
        ]
        if not _pdfs:
            _cands = sorted(
                _pdf_dir.glob(f"general_calendar_{year}_*.pdf"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            _pdfs = [p for p in _cands[:1] if p.stat().st_size > 0]
        if not _pdfs:
            st.info("Encara no hi ha cap calendari generat. Prem **Generar**.")
        for _general_pdf in _pdfs:
            try:
                # Renderitzem el PDF a imatge (PyMuPDF): fiable a l'app, sense
                # dependre del visualitzador natiu ni d'iframes.
                _stat = _general_pdf.stat()
                for _png in _pdf_page_pngs(
                    str(_general_pdf), _stat.st_mtime_ns, _stat.st_size,
                ):
                    st.image(_png, width="stretch")
            except Exception:
                st.info(
                    f"No s'ha pogut mostrar «{_general_pdf.name}». Torna a "
                    "generar o exporta'l de nou."
                )

    # NOTA: l'antic expander "Afegir guàrdia, permís o canvi d'activitat"
    # s'ha eliminat. Guàrdies i absències s'editen a Mètriques i canvis
    # finals (sub-pestanya Guàrdies i expander Absències). Els canvis
    # puntuals d'assignació es fan als Ajustos ràpids (quick_add_panels).


def _render_readjustment_report(report_df: pd.DataFrame) -> None:
    if report_df.empty:
        st.info("El solver no ha necessitat moure cap assignació addicional.")
    else:
        st.dataframe(
            report_df,
            hide_index=True,
            width="stretch",
            height=data_editor_height(len(report_df)),
        )
