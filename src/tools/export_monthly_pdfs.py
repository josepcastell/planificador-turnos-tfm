from pathlib import Path
import argparse
import shutil
from collections import defaultdict
import pandas as pd
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Flowable, KeepInFrame,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER


class _VerticalText(Flowable):
    """Text rotat 90° (de baix a dalt). Per a capçaleres de columna molt
    estretes (noms de màquina) on l'horitzontal es solaparia."""

    def __init__(self, text: str, font: str = "Helvetica-Bold", size: float = 4.4):
        super().__init__()
        self.text = str(text)
        self.font = font
        self.size = size

    def wrap(self, avail_w, avail_h):
        self._w, self._h = avail_w, avail_h
        return avail_w, avail_h

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFont(self.font, self.size)
        c.translate(self._w / 2.0 + self.size * 0.36, 1.0)
        c.rotate(90)
        c.drawCentredString(self._h / 2.0, 0, self.text)
        c.restoreState()

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.services.calendar_inputs import load_guard_schedule_by_day
from src.domain.schedule_format import (
    calendar_display_compact_slot_label,
    calendar_display_slot_area,
    calendar_display_slot_sort_key,
    franja_sort_key,
    is_review_slot,
    slot_sort_key,
)

# Inicial d'una franja per a etiquetes compactes (fons buit per a "12H").
FRANJA_INITIAL = {"MATI": "M", "TARDA": "T", "NIT": "N", "12H": ""}


def available_output_path(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        return str(path)

    for version in range(2, 100):
        candidate = path.with_name(f"{path.stem}_v{version}{path.suffix}")
        if not candidate.exists():
            return str(candidate)

    return str(path.with_name(f"{path.stem}_v99{path.suffix}"))


def build_pdf_with_fallback(doc: SimpleDocTemplate, story) -> str:
    try:
        doc.build(story)
        return str(doc.filename)
    except PermissionError:
        fallback = available_output_path(str(doc.filename))
        fallback_doc = SimpleDocTemplate(
            fallback,
            pagesize=doc.pagesize,
            leftMargin=doc.leftMargin,
            rightMargin=doc.rightMargin,
            topMargin=doc.topMargin,
            bottomMargin=doc.bottomMargin,
        )
        fallback_doc.build(story)
        print(f"No s'ha pogut sobreescriure {doc.filename}; generat a {fallback}")
        return fallback


def month_name_es(year: int, month: int) -> str:
    names = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
    }
    return f"{names[month]} {year}"


def month_name_ca(year: int, month: int) -> str:
    names = {
        1: "gener", 2: "febrer", 3: "març", 4: "abril",
        5: "maig", 6: "juny", 7: "juliol", 8: "agost",
        9: "setembre", 10: "octubre", 11: "novembre", 12: "desembre",
    }
    return f"{names[month]} {year}"


def calendar_day_type_label(day_type: str) -> str:
    value = "" if pd.isna(day_type) else str(day_type).strip()
    labels = {
        "fin_de_semana": "cap de setmana",
        "festivo_general": "festiu",
        "festivo_ics": "festiu ICS",
        "festivo_extra": "festiu extra",
        "festiu_general": "festiu",
        "festiu_ics": "festiu ICS",
        "festiu_extra": "festiu extra",
        "laborable": "",
    }
    return labels.get(value, value.replace("_", " "))



def normalize_display_meta(slot_id: str, franja: str, presentiality: str, work_mode: str):
    slot_id = "" if pd.isna(slot_id) else str(slot_id).strip().upper()
    franja = "" if pd.isna(franja) else str(franja).strip().upper()
    presentiality = "" if pd.isna(presentiality) else str(presentiality).strip().upper()
    work_mode = "" if pd.isna(work_mode) else str(work_mode).strip().upper()

    if not franja and slot_id in GUARDS_RESERVED_SLOT_IDS:
        franja = "GUARDIA"

    if presentiality in {"", "NO_DEFINIT"}:
        presentiality = "NO_PRESENCIAL"

    if work_mode in {"", "NO_DEFINIT"}:
        work_mode = "NORMAL"

    return franja, presentiality, work_mode


def short_presentiality(value: str) -> str:
    value = str(value).upper()
    if value == "PRESENCIAL":
        return "P"
    if value == "NO_PRESENCIAL":
        return "NP"
    return value


def short_work_mode(value: str) -> str:
    value = str(value).upper()
    if value == "NORMAL":
        return "N"
    if value == "PEONADA":
        return "PEO"
    return value



def individual_compact_label(slot_id: str) -> str | None:
    """Etiqueta especial per a slots de guàrdia o de revisió (genèric, sense
    noms hardcoded). La resta retornen None (s'usa el slot_id normal)."""
    slot = "" if pd.isna(slot_id) else str(slot_id).strip().upper()
    if slot in GUARDS_RESERVED_SLOT_IDS:
        return slot.replace("_", " ").title()
    if is_review_slot(slot):
        return slot.replace("_", " ").title()
    return None


def calendar_slot_area(slot_id: str) -> str:
    area = calendar_display_slot_area(slot_id)
    return "" if area == "ALTRES" else area


# Paleta estable per àrea (mateixos colors i ordre que les classes CSS
# `.schedule-area-c1..c6` de styles.py, perquè PDF i app coincideixin).
_AREA_PDF_PALETTE = (
    "#DBEAFE", "#DCFCE7", "#EDE9FE", "#FEF3C7", "#FCE7F3", "#CCFBF1",
)


def calendar_slot_area_background(area: str):
    """Color de fons estable per àrea (qualsevol valor que defineixi
    l'usuari), sense àrees predefinides. Sense àrea → gris neutre."""
    a = str(area).strip().upper()
    if not a or a == "ALTRES":
        return colors.HexColor("#F8FAFC")
    idx = sum((i + 1) * ord(c) for i, c in enumerate(a)) % len(_AREA_PDF_PALETTE)
    return colors.HexColor(_AREA_PDF_PALETTE[idx])


def calendar_slot_pdf_sort_key(slot_id: str) -> tuple[int, str]:
    return calendar_display_slot_sort_key(slot_id)


def calendar_slot_area_groups(slots: list[str]) -> list[tuple[str, int, int]]:
    groups = []
    current_area = None
    start = 0
    for index, slot in enumerate(slots):
        area = calendar_slot_area(slot)
        if current_area is None:
            current_area = area
            start = index
            continue
        if area != current_area:
            groups.append((current_area, start, index - 1))
            current_area = area
            start = index
    if current_area is not None:
        groups.append((current_area, start, len(slots) - 1))
    return groups


def calendar_compact_slot_label(slot_id: str) -> str:
    return calendar_display_compact_slot_label(slot_id)


def calendar_compact_line(row) -> str:
    franja = "" if pd.isna(row.franja) else str(row.franja).strip().upper()
    prefix = FRANJA_INITIAL.get(franja, franja[:1])
    slot_label = calendar_compact_slot_label(row.slot_id)
    professional = "" if pd.isna(row.professional) else str(row.professional).strip()
    parts = [part for part in [prefix, slot_label] if part]
    return f"{' '.join(parts)} {professional}".strip()


# Color del text segons presencialitat (el fons de la casella queda
# reservat a peonada/festiu). Sigles en verd = presencial, blau = no
# presencial.
PRESENCIAL_TEXT_COLOR = "#15803D"
NO_PRESENCIAL_TEXT_COLOR = "#1D4ED8"


def calendar_professional_label(row) -> str:
    # La peonada ja es distingeix pel fons groc de la cel·la (sense sufix "+").
    # Si l'assignació prové d'un flip NP→PRES (is_flipped=1), s'afegeix
    # el prefix "T-": el facultatiu informa de presència física a
    # l'hospital, però no necessàriament el dia de l'exploració.
    if pd.isna(row.professional):
        return ""
    name = str(row.professional).strip()
    if not name:
        return name
    flip_val = getattr(row, "is_flipped", None)
    if flip_val is None or (isinstance(flip_val, float) and pd.isna(flip_val)):
        return name
    is_flipped = str(flip_val).strip() in {"1", "1.0", "True", "true"}
    return f"T-{name}" if is_flipped else name


def _presence_markup_lines(rows) -> list[str]:
    """Línies amb les sigles dels facultatius acolorides per presencialitat
    (verd = presencial, blau = no presencial), sense parèntesis. Es retorna
    una línia per grup perquè en slots doblats/vinculats no surtin de la
    casella. Les rows flipades (NP→PRES, marcades amb T-) s'ordenen al
    final de cada llista perquè a una màquina doblada el T- surti sempre
    al segon facultatiu."""
    def _flip_key(r) -> int:
        v = getattr(r, "is_flipped", None)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0
        return 1 if str(v).strip() in {"1", "1.0", "True", "true"} else 0
    rows_sorted = sorted(rows, key=_flip_key)
    pres, nopres = [], []
    for r in rows_sorted:
        name = calendar_professional_label(r)
        if not name:
            continue
        p = str(getattr(r, "presentiality", "") or "").strip().upper()
        (pres if p == "PRESENCIAL" else nopres).append(escape(name))
    lines = []
    if pres:
        lines.append(f'<font color="{PRESENCIAL_TEXT_COLOR}">{"/".join(pres)}</font>')
    if nopres:
        lines.append(f'<font color="{NO_PRESENCIAL_TEXT_COLOR}">{"/".join(nopres)}</font>')
    return lines


def _franja_cell(rows, style):
    """Cel·la d'una franja com a Paragraph (s'ajusta dins l'amplada de la
    columna), amb les sigles acolorides per presencialitat."""
    lines = _presence_markup_lines(rows)
    if not lines:
        return ""
    return Paragraph("<br/>".join(lines), style)


def _assignment_legend_flowables(
    show_operational_overlays: bool = True,
) -> list:
    """Llegenda + nota del conveni: el color de les sigles indica la
    presencialitat i el fons de la casella la peonada / festiu. Quan
    no es mostren overlays operatius (calendari inicial), s'omet la
    nota sobre (G)/(R)/(PG) per evitar confusió."""
    note_style = ParagraphStyle(
        "LegendNote", fontName="Helvetica", fontSize=6, leading=7
    )
    base_note = (
        "Conveni: color de les sigles = presencialitat "
        "(verd = presencial, blau = no presencial); fons de la casella = "
        "peonada (groc) o festiu / no laborable (gris). "
        "Prefix T- davant del facultatiu = activitat originalment "
        "no-presencial forçada a presencial pel solver: el facultatiu "
        "ha d'informar de presència física a l'hospital, però no "
        "necessàriament el mateix dia de l'exploració."
    )
    overlay_note = (
        " Guàrdia (G) i reforç (R): facultatiu en vermell i negreta a "
        "la capçalera del dia. Postguàrdia: a la fila d'absències (PG)."
    )
    initial_note = (
        " Sense overlays operatius: el PDF no mostra fila d'absències "
        "ni marques (G)/(R)/PG. Útil per a revisar només les "
        "assignacions de slots."
    )
    suffix = overlay_note if show_operational_overlays else initial_note
    return [
        _assignment_legend(),
        Spacer(1, 0.8 * mm),
        Paragraph(base_note + suffix, note_style),
    ]


def _assignment_legend() -> Table:
    """Sigles acolorides per presencialitat (verd/blau) i mostres de fons per
    a peonada (groc) i festiu / no laborable (gris)."""
    txt = ParagraphStyle("LegendTxt", fontName="Helvetica", fontSize=6, leading=7)
    row = [
        Paragraph(
            f'<font color="{PRESENCIAL_TEXT_COLOR}"><b>Presencial</b></font>', txt
        ),
        Paragraph(
            f'<font color="{NO_PRESENCIAL_TEXT_COLOR}"><b>No presencial</b></font>',
            txt,
        ),
    ]
    col_widths = [20 * mm, 26 * mm]
    styles_ = [
        ("FONTSIZE", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    bg_items = [
        ("Peonada", colors.HexColor("#FFF0C2")),
        ("Festiu / no laborable", colors.HexColor("#E5E7EB")),
    ]
    base = len(row)
    for i, (label, color) in enumerate(bg_items):
        swatch_col = base + 2 * i
        row.extend(["", label])
        col_widths.extend([5 * mm, (len(label) * 1.7 + 4) * mm])
        styles_.append(("BACKGROUND", (swatch_col, 0), (swatch_col, 0), color))
        styles_.append(("BOX", (swatch_col, 0), (swatch_col, 0), 0.4, colors.grey))
    legend = Table([row], colWidths=col_widths)
    legend.setStyle(TableStyle(styles_))
    return legend


def calendar_assignment_background(rows, slot_id: str):
    if not rows:
        return None

    modes = {
        str(getattr(row, "work_mode", "") or "").strip().upper()
        for row in rows
    }

    if "PEONADA" in modes:
        return colors.HexColor("#FFF0C2")
    return None


def load_unavailability_by_day(year: int, month: int) -> dict:
    candidates = [
        Path(f"data/derived/unavailability_weekday_{year}.csv"),
        Path(f"data/derived/unavailability_{year}.csv"),
    ]
    for path in candidates:
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = pd.read_csv(path)
        if not {"professional_id", "day"}.issubset(df.columns):
            continue
        df["day"] = pd.to_datetime(df["day"], errors="coerce")
        df = df.dropna(subset=["day"]).copy()
        from src.domain.month_scope import in_logical_month
        df = df[in_logical_month(df["day"], year, month)].copy()
        # Les guàrdies (guard_day i post_guard_free) NO van a la fila
        # d'absències: la guàrdia surt a la seva fila pròpia i la
        # postguàrdia s'hi afegeix marcada (PG) a part.
        if "reason" in df.columns:
            guard_reasons = {
                "guardia_day_tarda", "refuerzo_afternoon", "post_guard_free",
            }
            df = df[~df["reason"].astype(str).isin(guard_reasons)].copy()
        grouped = defaultdict(list)
        for row in df.itertuples(index=False):
            professional_id = str(row.professional_id).strip()
            if professional_id and professional_id not in grouped[row.day.date()]:
                grouped[row.day.date()].append(professional_id)
        return {day: sorted(values) for day, values in grouped.items()}
    return {}
def load_professional_names(professionals_csv: str) -> dict:
    path = Path(professionals_csv)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    df = pd.read_csv(path)
    if "professional_id" not in df.columns or "name" not in df.columns:
        return {}
    return dict(zip(df["professional_id"].astype(str), df["name"].astype(str)))


def load_base_calendar_status(year: int) -> dict:
    path = Path(f"data/base_calendar_{year}.csv")
    if not path.exists() or path.stat().st_size == 0:
        return {}

    df = pd.read_csv(path)
    if "day" not in df.columns:
        return {}

    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    df = df.dropna(subset=["day"]).copy()

    status = {}
    for row in df.itertuples(index=False):
        day = row.day.date()
        is_working_day = bool(getattr(row, "is_working_day", 1))
        day_type = str(getattr(row, "day_type", "") or "")
        status[day] = {
            "is_working_day": is_working_day,
            "day_type": day_type,
        }
    return status


def prepare_month_df(schedule_csv: str, year: int, month: int) -> pd.DataFrame:
    df = pd.read_csv(schedule_csv)
    required = {"day", "slot_id", "professional"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas en schedule.csv: {missing}")

    if "franja" not in df.columns:
        df["franja"] = ""
    if "presentiality" not in df.columns:
        df["presentiality"] = "NO_DEFINIT"
    if "work_mode" not in df.columns:
        df["work_mode"] = "NO_DEFINIT"
    if "is_flipped" not in df.columns:
        df["is_flipped"] = 0  # schedules antics: cap flip explícit

    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    df = df.dropna(subset=["day"]).copy()
    from src.domain.month_scope import in_logical_month
    df = df[in_logical_month(df["day"], year, month)].copy()
    if df.empty:
        raise ValueError(f"No hay datos en schedule.csv para {year}-{month:02d}")

    # Files sense assignació real (professional buit / NONE) no s'inclouen,
    # així les màquines sense cap facultatiu assignat no generen columna.
    df["professional"] = df["professional"].fillna("NONE").astype(str).str.strip()
    df = df[~df["professional"].str.upper().isin(["", "NONE", "NAN"])].copy()

    df["franja"] = df["franja"].fillna("").astype(str)
    df["presentiality"] = df["presentiality"].fillna("NO_DEFINIT").astype(str)
    df["work_mode"] = df["work_mode"].fillna("NO_DEFINIT").astype(str)

    normalized = df.apply(
        lambda row: normalize_display_meta(
            row["slot_id"], row["franja"], row["presentiality"], row["work_mode"]
        ),
        axis=1,
        result_type="expand",
    )
    normalized.columns = ["franja", "presentiality", "work_mode"]
    df[["franja", "presentiality", "work_mode"]] = normalized

    df["day_str"] = df["day"].dt.strftime("%Y-%m-%d")
    df["franja_order"] = df["franja"].apply(franja_sort_key)
    df["slot_order"] = df["slot_id"].apply(slot_sort_key)

    return df.sort_values(
        ["day", "franja_order", "slot_order", "slot_id", "professional"]
    ).reset_index(drop=True)


def build_general_pdf(schedule_csv: str, professionals_csv: str, year: int, month: int, output_pdf: str) -> None:
    df = prepare_month_df(schedule_csv, year, month)
    names = load_professional_names(professionals_csv)

    styles = getSampleStyleSheet()
    story = []

    title = f"Planning general - {month_name_es(year, month)}"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 6 * mm))

    days = sorted(df["day_str"].unique())

    for day in days:
        day_df = df[df["day_str"] == day].copy()

        story.append(Paragraph(day, styles["Heading2"]))
        story.append(Spacer(1, 2 * mm))

        table_data = [["Franja", "Màquina", "Profesional", "Nombre", "Presencialidad", "Modo"]]
        for row in day_df.itertuples(index=False):
            pid = str(row.professional)
            table_data.append([
                row.franja,
                row.slot_id,
                pid,
                names.get(pid, ""),
                row.presentiality,
                row.work_mode,
            ])

        table = Table(table_data, colWidths=[22 * mm, 38 * mm, 26 * mm, 78 * mm, 38 * mm, 35 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        story.append(Spacer(1, 6 * mm))

    Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    build_pdf_with_fallback(doc, story)


def build_weekday_grid_calendar_pdf(
    df: pd.DataFrame,
    day_status: dict,
    year: int,
    month: int,
    output_pdf: str,
    show_operational_overlays: bool = True,
) -> None:
    """Genera el PDF setmanal del calendari laborable.

    Si `show_operational_overlays` és False, NO es renderitzen les
    absències, postguàrdies (PG) ni les marques (G)/(R) a la capçalera
    del dia. S'usa per al calendari INICIAL, on el solver no considera
    aquestes restriccions — així evitem mostrar informació visualment
    que no s'ha aplicat al càlcul. Els festius/no laborables sí surten
    sempre (depenen del calendari base, no del solver)."""
    df = df.copy()
    df["day_date"] = pd.to_datetime(df["day_str"]).dt.date

    # Guàrdia i reforç surten a la capçalera del dia, en vermell: el
    # facultatiu de guàrdia amb (G) i el de reforç amb (R).
    def _is_reforc(kind: str) -> bool:
        return str(kind or "").strip().lower().startswith(
            ("refuerzo", "reforc", "reforç")
        )

    weekday_names = ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres"]
    franges = [("MATI", "Matí"), ("TARDA", "Tarda"), ("NIT", "Nit")]

    # Regla del dilluns: una setmana ISO pertany al mes del seu dilluns.
    # Per tant, una setmana al final del mes pot incloure dies del mes
    # següent (i una setmana al començament pot incloure dies del mes
    # anterior). Aquests dies "lògicament del mes" s'han de pintar igual.
    import datetime as _dtmod

    def _in_logical(d) -> bool:
        mon = d - _dtmod.timedelta(days=d.weekday())
        return mon.year == year and mon.month == month

    assignment_map = defaultdict(list)
    slots_by_day: dict = defaultdict(set)
    for row in df.itertuples(index=False):
        day = pd.Timestamp(row.day).date()
        slot = "" if pd.isna(row.slot_id) else str(row.slot_id).strip()
        franja = "" if pd.isna(row.franja) else str(row.franja).strip().upper()
        assignment_map[(day, franja, slot)].append(row)
        prof = calendar_professional_label(row).strip().upper()
        if (
            slot
            and slot.upper() not in GUARDS_RESERVED_SLOT_IDS
            and franja in {"MATI", "TARDA", "NIT"}
            and _in_logical(day)
            and day.weekday() < 5
            and prof
            and prof not in {"NONE", "NAN"}
        ):
            slots_by_day[day].add(slot)

    # Dies laborables: només les màquines realment programades aquell dia
    # (sense columnes buides). Dies festius / no laborables: es mostren
    # igualment amb una columna de marca, encara que no tinguin màquines.
    # Iterem tot el rang lògic del mes (amb overflow de setmana) per
    # detectar festius que cauen a dies fora del mes calendari.
    assigned_days = {d for d, s in slots_by_day.items() if s}
    _first = pd.Timestamp(year=year, month=month, day=1)
    _last = _first + pd.offsets.MonthEnd(0)
    _scan_start = _first - pd.Timedelta(days=int(_first.weekday()))
    _scan_end = _last + pd.Timedelta(days=6 - int(_last.weekday()))
    festiu_days = set()
    for ts in pd.date_range(_scan_start, _scan_end, freq="D"):
        d = ts.date()
        if d.weekday() >= 5 or d in assigned_days or not _in_logical(d):
            continue
        status = day_status.get(d, {})
        if status and not status.get("is_working_day", True):
            festiu_days.add(d)

    if not assigned_days and not festiu_days:
        styles = getSampleStyleSheet()
        story = [Paragraph(
            f"Calendari d'entre setmana general - {month_name_ca(year, month)}",
            styles["Title"],
        ), Paragraph("Sense assignacions per a aquest mes.", styles["BodyText"])]
        Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
        build_pdf_with_fallback(
            SimpleDocTemplate(output_pdf, pagesize=landscape(A4)), story
        )
        return

    # Setmanes de calendari (Dilluns–Divendres) perquè cada dia de la
    # setmana surti SEMPRE a la mateixa columna. Es descarten les setmanes
    # sense cap dia del mes.
    cal_start = (_first - pd.Timedelta(days=int(_first.weekday()))).normalize()
    cal_end = (_last + pd.Timedelta(days=6 - int(_last.weekday()))).normalize()
    all_days = list(pd.date_range(cal_start, cal_end, freq="D"))
    weeks = [all_days[i:i + 7] for i in range(0, len(all_days), 7)]
    bands = []
    for wk in weeks:
        mon_fri = [ts.date() for ts in wk[:5]]
        if any(d.month == month and d.year == year for d in mon_fri):
            bands.append(mon_fri)

    # Compatibilitat: a la resta de la funció es feia servir _in_month
    # per decidir si un dia és "del mes". Ara aplicarem la regla del
    # dilluns (setmanes completes) per coherència amb la resta del
    # programa: el dia s'inclou si la seva setmana pertany al mes lògic.
    def _in_month(d) -> bool:
        return _in_logical(d)

    day_slots = {}
    for band in bands:
        for d in band:
            if d in assigned_days:
                day_slots[d] = sorted(
                    slots_by_day[d], key=calendar_slot_pdf_sort_key
                )
            else:
                day_slots[d] = []  # festiu o buit (fora de mes / sense feina)

    def day_cols(d) -> int:
        return max(1, len(day_slots[d]))  # festiu/buit = 1 columna

    present_franges = [
        (fk, fl) for fk, fl in franges
        if any(
            assignment_map.get((d, fk, sl))
            for d in assigned_days for sl in day_slots[d]
        )
    ] or [("MATI", "Matí")]

    # Mode "initial calendar": no carreguem cap overlay operatiu (absències
    # ni guàrdies/postguàrdies) perquè el solver no les ha considerat.
    if show_operational_overlays:
        unavailability = load_unavailability_by_day(year, month)
    else:
        unavailability = {}

    # Guàrdies / postguàrdies del mes (per data). La guàrdia surt a la
    # capçalera del dia; la postguàrdia, a la fila d'absències (PG).
    # També apliquem la regla del dilluns: si la setmana del dia pertany
    # al mes lògic, la guàrdia/postguàrdia es renderitza al PDF d'aquest
    # mes encara que el dia sigui de juny/juliol per data.
    guards_by_date: dict = {}
    post_by_date: dict = {}
    if show_operational_overlays:
        for _k, _v in load_guard_schedule_by_day(year).items():
            try:
                _dd = pd.to_datetime(_k).date()
            except Exception:
                continue
            if _in_logical(_dd):
                if _v.get("guards"):
                    guards_by_date[_dd] = _v["guards"]
                if _v.get("post"):
                    post_by_date[_dd] = _v["post"]

    # Tots els dies del mes tenen la MATEIXA amplada de bloc (incloent
    # festius). Dins de cada dia, les seves màquines reparteixen aquest
    # ample a parts iguals; un festiu (1 columna) ocupa tot el bloc.
    label_width_mm = 12.5
    available_width_mm = 287
    day_block_mm = (available_width_mm - label_width_mm) / 5
    max_day_slots = max((len(day_slots[d]) for d in assigned_days), default=1)
    assignment_font = (
        6.0 if max_day_slots <= 2 else 5.4 if max_day_slots <= 3 else 4.9
    )
    slot_font = max(4.8, assignment_font - 0.2)

    table_height_mm = 168
    band_height_mm = table_height_mm / max(1, len(bands))
    base_props = [0.12, 0.09, 0.09, 0.22]
    franja_prop = (1.0 - sum(base_props)) / max(1, len(present_franges))
    proportions = base_props + [franja_prop] * len(present_franges)
    _day_sep = colors.HexColor("#334155")

    franja_cell_style = ParagraphStyle(
        "FranjaCell", fontName="Helvetica", fontSize=assignment_font,
        leading=assignment_font + 0.4, alignment=TA_CENTER, wordWrap="CJK",
    )
    header_cell_style = ParagraphStyle(
        "DayHeader", fontName="Helvetica-Bold", fontSize=6.6,
        leading=7.4, alignment=TA_CENTER, textColor=colors.white,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("WeekdayGridTitle")
    title_style.fontSize = 12
    title_style.leading = 13
    title_style.spaceAfter = 0
    story = [
        Paragraph(f"Calendari d'entre setmana general - {month_name_ca(year, month)}", title_style),
        Spacer(1, 1.2 * mm),
    ]

    for band in bands:
        # Rang de columnes per a cada dia (1 = columna d'etiquetes).
        day_span: dict = {}
        col = 1
        for d in band:
            n = day_cols(d)
            day_span[d] = (col, col + n - 1)
            col += n
        total_cols = col - 1
        n_franja_rows = len(present_franges)

        table_data = []
        row_heights = []
        table_style = [
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("BOX", (0, 0), (-1, -1), 1.2, _day_sep),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), assignment_font),
            ("LEADING", (0, 0), (-1, -1), assignment_font + 0.4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0.7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0.7),
            ("TOPPADDING", (0, 0), (-1, -1), 0.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
        ]

        def shade_day(row_idx: int, d) -> None:
            status = day_status.get(d, {})
            if status and not status.get("is_working_day", True):
                s, e = day_span[d]
                table_style.append(
                    ("BACKGROUND", (s, row_idx), (e, row_idx), colors.HexColor("#E5E7EB"))
                )

        # Capçalera de dia. El facultatiu de guàrdia (i reforç, marcat
        # "(R)") surt al costat del dia, en negreta i vermell.
        hidx = len(table_data)
        header = [""] * (total_cols + 1)
        for d in band:
            s, e = day_span[d]
            wd = weekday_names[d.weekday()] if d.weekday() < 5 else ""
            in_m = _in_month(d)
            g_entries = guards_by_date.get(d, []) if in_m else []
            gnames = [
                f"{p} ({'R' if _is_reforc(k) else 'G'})" for p, k in g_entries
            ]
            if in_m and gnames:
                header[s] = Paragraph(
                    f'{escape(f"{wd} {d.day}")} '
                    f'<font color="#FCA5A5"><b>· {escape(" ".join(gnames))}'
                    f'</b></font>',
                    header_cell_style,
                )
            else:
                header[s] = f"{wd} {d.day}" if in_m else ""
            hbg = colors.HexColor("#475569") if in_m else colors.HexColor("#E2E8F0")
            table_style.extend([
                ("SPAN", (s, hidx), (e, hidx)),
                ("BACKGROUND", (s, hidx), (e, hidx), hbg),
                ("TEXTCOLOR", (s, hidx), (e, hidx),
                 colors.white if in_m else colors.HexColor("#94A3B8")),
                ("FONTNAME", (s, hidx), (e, hidx), "Helvetica-Bold"),
                ("FONTSIZE", (s, hidx), (e, hidx), 6.4),
            ])
        table_data.append(header)
        row_heights.append(band_height_mm * proportions[0] * mm)

        # Aus. (indisponibilitats). Per als dies festius/no laborables,
        # aquesta cel·la s'estén per tot el bloc del dia amb la marca.
        aidx = len(table_data)
        last_row = aidx + 2 + n_franja_rows  # Aus, Àrea, Màquina, franges...
        abs_row = ["Abs."] + [""] * total_cols
        for d in band:
            s, e = day_span[d]
            if d in festiu_days:  # festiu / no laborable: marca tot el bloc
                status = day_status.get(d, {})
                label = calendar_day_type_label(status.get("day_type", "")) or "No laborable"
                ptxt = " ".join(f"{p} (PG)" for p in post_by_date.get(d, []))
                if ptxt:
                    label = f"{label} · {ptxt}"
                abs_row[s] = label
                table_style.extend([
                    ("SPAN", (s, aidx), (e, last_row)),
                    ("BACKGROUND", (s, aidx), (e, last_row), colors.HexColor("#E5E7EB")),
                    ("FONTSIZE", (s, aidx), (e, last_row), 5.6),
                    ("TEXTCOLOR", (s, aidx), (e, last_row), colors.HexColor("#475569")),
                ])
                continue
            if not day_slots[d]:  # fora de mes o laborable sense assignació
                table_style.extend([
                    ("SPAN", (s, aidx), (e, last_row)),
                    ("BACKGROUND", (s, aidx), (e, last_row), colors.HexColor("#F8FAFC")),
                ])
                continue
            absences = list(unavailability.get(d, []))
            absences += [f"{p} (PG)" for p in post_by_date.get(d, [])]
            text = " ".join(absences[:8])
            if len(absences) > 8:
                text += f" +{len(absences) - 8}"
            abs_row[s] = text
            table_style.extend([
                ("SPAN", (s, aidx), (e, aidx)),
                ("FONTSIZE", (s, aidx), (e, aidx), 5.1),
            ])
            # Sense fons de color a les absències: el groc es confonia amb
            # la peonada. El text dels facultatius absents ja és prou clar.
            shade_day(aidx, d)
        table_data.append(abs_row)
        row_heights.append(band_height_mm * proportions[1] * mm)

        # Àrea
        arow_idx = len(table_data)
        area_row = ["Àrea"] + [""] * total_cols
        for d in band:
            s, _e = day_span[d]
            for area, g0, g1 in calendar_slot_area_groups(day_slots[d]):
                cs, ce = s + g0, s + g1
                area_row[cs] = area
                table_style.extend([
                    ("SPAN", (cs, arow_idx), (ce, arow_idx)),
                    ("BACKGROUND", (cs, arow_idx), (ce, arow_idx), calendar_slot_area_background(area)),
                    ("BOX", (cs, arow_idx), (ce, arow_idx), 0.35, colors.HexColor("#94A3B8")),
                ])
            shade_day(arow_idx, d)
        table_data.append(area_row)
        row_heights.append(band_height_mm * proportions[2] * mm)
        table_style.extend([
            ("FONTNAME", (0, arow_idx), (-1, arow_idx), "Helvetica-Bold"),
            ("FONTSIZE", (0, arow_idx), (-1, arow_idx), slot_font),
        ])

        # Màquina
        midx = len(table_data)
        mrow = ["Màquina"] + [""] * total_cols
        for d in band:
            s, _e = day_span[d]
            for i, slot in enumerate(day_slots[d]):
                mrow[s + i] = _VerticalText(calendar_compact_slot_label(slot), size=slot_font)
            shade_day(midx, d)
        table_data.append(mrow)
        row_heights.append(band_height_mm * proportions[3] * mm)
        table_style.extend([
            ("BACKGROUND", (0, midx), (-1, midx), colors.HexColor("#F8FAFC")),
            ("FONTNAME", (0, midx), (-1, midx), "Helvetica-Bold"),
            ("FONTSIZE", (0, midx), (-1, midx), slot_font),
        ])

        # Franges. Els slots de revisió apliquen al DIA SENCER: es mostren
        # una sola vegada i la cel·la s'estén (SPAN) per totes les franges.
        first_franja_ridx = len(table_data)
        last_franja_ridx = first_franja_ridx + len(present_franges) - 1
        for fpos, (fk, fl) in enumerate(present_franges):
            ridx = len(table_data)
            row_data = [fl] + [""] * total_cols
            for d in band:
                s, _e = day_span[d]
                for i, slot in enumerate(day_slots[d]):
                    col = s + i
                    if is_review_slot(slot):
                        if fpos != 0:
                            continue  # cobert pel SPAN del dia sencer
                        rows = [
                            r
                            for afk in ("MATI", "TARDA", "NIT")
                            for r in assignment_map.get((d, afk, slot), [])
                        ]
                        if last_franja_ridx > first_franja_ridx:
                            table_style.append(
                                ("SPAN", (col, first_franja_ridx),
                                 (col, last_franja_ridx))
                            )
                    else:
                        rows = assignment_map.get((d, fk, slot), [])
                    row_data[col] = _franja_cell(rows, franja_cell_style)
                    bg = calendar_assignment_background(rows, slot)
                    if bg is not None:
                        end_r = last_franja_ridx if is_review_slot(slot) else ridx
                        table_style.append(("BACKGROUND", (col, ridx), (col, end_r), bg))
                shade_day(ridx, d)
            table_data.append(row_data)
            row_heights.append(band_height_mm * proportions[4 + fpos] * mm)

        # Etiqueta de fila + separadors verticals entre dies
        for r in range(len(table_data)):
            table_style.extend([
                ("BACKGROUND", (0, r), (0, r), colors.HexColor("#F1F5F9")),
                ("FONTNAME", (0, r), (0, r), "Helvetica-Bold"),
                ("FONTSIZE", (0, r), (0, r), 5.6),
            ])
        table_style.append(("LINEAFTER", (0, 0), (0, -1), 1.8, _day_sep))
        for d in band:
            _s, e = day_span[d]
            table_style.append(("LINEAFTER", (e, 0), (e, -1), 1.8, _day_sep))

        col_widths = [label_width_mm * mm]
        for d in band:
            n = day_cols(d)
            col_widths += [(day_block_mm / n) * mm] * n
        table = Table(
            table_data,
            colWidths=col_widths,
            rowHeights=row_heights,
            repeatRows=0,
        )
        table.setStyle(TableStyle(table_style))
        story.append(table)
        story.append(Spacer(1, 0.9 * mm))

    story.extend(_assignment_legend_flowables(
        show_operational_overlays=show_operational_overlays,
    ))

    Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=landscape(A4),
        leftMargin=5 * mm,
        rightMargin=5 * mm,
        topMargin=5 * mm,
        bottomMargin=5 * mm,
    )
    build_pdf_with_fallback(doc, story)


def build_general_calendar_pdf(
    schedule_csv: str,
    professionals_csv: str,
    year: int,
    month: int,
    output_pdf: str,
    weekdays_only: bool = False,
    show_operational_overlays: bool = True,
) -> None:
    df = prepare_month_df(schedule_csv, year, month)
    day_status = load_base_calendar_status(year)
    if weekdays_only:
        build_weekday_grid_calendar_pdf(
            df, day_status, year, month, output_pdf,
            show_operational_overlays=show_operational_overlays,
        )
        return

    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"].clone("GeneralCalendarCell")
    cell_style.fontSize = 4.6
    cell_style.leading = 4.9
    cell_style.spaceAfter = 0
    cell_style.spaceBefore = 0
    header_style = styles["BodyText"].clone("GeneralCalendarHeader")
    header_style.fontSize = 7
    header_style.leading = 7.5
    header_style.fontName = "Helvetica-Bold"
    title_style = styles["Title"].clone("GeneralCalendarTitle")
    title_style.fontSize = 13
    title_style.leading = 15

    import datetime as _dtmod_g

    def _in_logical_g(d) -> bool:
        # Regla del dilluns: el dia s'inclou si la seva setmana pertany
        # al mes lògic (la setmana ISO pertany al mes del seu dilluns).
        mon = d - _dtmod_g.timedelta(days=d.weekday())
        return mon.year == year and mon.month == month

    first_day = pd.Timestamp(year=year, month=month, day=1)
    last_day = first_day + pd.offsets.MonthEnd(0)
    calendar_start = first_day - pd.Timedelta(days=first_day.weekday())
    calendar_end = last_day + pd.Timedelta(days=(6 - last_day.weekday()))
    calendar_days = pd.date_range(calendar_start, calendar_end, freq="D")

    all_weeks = [calendar_days[i:i + 7] for i in range(0, len(calendar_days), 7)]
    # Només les setmanes el dilluns de les quals és al mes lògic.
    weeks = [
        wk for wk in all_weeks
        if len(wk) > 0 and _in_logical_g(wk[0].date())
    ]
    weekday_headers = ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres", "Dissabte", "Diumenge"]
    visible_weekday_indices = list(range(5)) if weekdays_only else list(range(7))
    weekday_headers = [weekday_headers[i] for i in visible_weekday_indices]

    df["day_date"] = pd.to_datetime(df["day_str"]).dt.date

    story = []
    story.append(Paragraph(f"Calendari general - {month_name_es(year, month)}", title_style))
    story.append(Spacer(1, 2 * mm))

    table_data = [[Paragraph(header, header_style) for header in weekday_headers]]
    max_lines_per_day = 22 if weekdays_only else 15

    for week in weeks:
        row_cells = []
        for day in [week[i] for i in visible_weekday_indices]:
            if not _in_logical_g(day.date()):
                row_cells.append("")
                continue

            day_date = day.date()
            day_rows = df[df["day_date"] == day_date].sort_values(["franja_order", "slot_order", "slot_id"])
            status = day_status.get(day_date, {})
            day_type = status.get("day_type", "")

            lines = [f"<b>{day.day}</b>"]
            if day_type and day_type != "laborable":
                lines.append(f"<i>{escape(day_type)}</i>")

            hidden_count = 0
            for idx, row in enumerate(day_rows.itertuples(index=False)):
                if idx >= max_lines_per_day:
                    hidden_count += 1
                    continue

                lines.append(escape(calendar_compact_line(row)))

            if hidden_count:
                lines.append(f"+{hidden_count} al detallat")

            row_cells.append(Paragraph("<br/>".join(lines), cell_style))
        table_data.append(row_cells)

    available_width_mm = 285 - 12
    available_height_mm = 198 - 20
    header_height_mm = 6
    body_row_height_mm = max(20, (available_height_mm - header_height_mm) / max(1, len(weeks)))
    table = Table(
        table_data,
        colWidths=[(available_width_mm / len(weekday_headers)) * mm] * len(weekday_headers),
        rowHeights=[header_height_mm * mm] + [body_row_height_mm * mm] * len(weeks),
    )
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    for week_idx, week in enumerate(weeks, start=1):
        for day_idx, day in enumerate([week[i] for i in visible_weekday_indices]):
            if not _in_logical_g(day.date()):
                table_style.append(("BACKGROUND", (day_idx, week_idx), (day_idx, week_idx), colors.HexColor("#F3F4F6")))
                continue
            status = day_status.get(day.date(), {})
            if status and not status.get("is_working_day", True):
                table_style.append(("BACKGROUND", (day_idx, week_idx), (day_idx, week_idx), colors.HexColor("#E5E7EB")))
            elif day.weekday() >= 5:
                table_style.append(("BACKGROUND", (day_idx, week_idx), (day_idx, week_idx), colors.HexColor("#F8FAFC")))

    table.setStyle(TableStyle(table_style))
    story.append(table)

    Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=landscape(A4),
        leftMargin=6 * mm,
        rightMargin=6 * mm,
        topMargin=6 * mm,
        bottomMargin=6 * mm,
    )
    build_pdf_with_fallback(doc, story)


def build_individual_pdfs(schedule_csv: str, professionals_csv: str, year: int, month: int, output_dir: str) -> None:
    df = prepare_month_df(schedule_csv, year, month)
    names = load_professional_names(professionals_csv)
    styles = getSampleStyleSheet()

    outdir = Path(output_dir)
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for professional_id in sorted(df["professional"].astype(str).unique()):
        pdf_path = outdir / f"individual_{professional_id}_{year}_{month:02d}.pdf"
        prof_df = df[df["professional"].astype(str) == professional_id].copy()

        story = []
        display_name = names.get(professional_id, "")
        title = f"Planning individual - {professional_id}"
        if display_name:
            title += f" - {display_name}"

        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(month_name_es(year, month), styles["Heading2"]))
        story.append(Spacer(1, 4 * mm))

        table_data = [["Día", "Franja", "Màquina", "Presencialidad", "Modo"]]
        for row in prof_df.itertuples(index=False):
            compact = individual_compact_label(row.slot_id)
            if compact is not None:
                table_data.append([
                    row.day_str,
                    "",
                    compact,
                    "",
                    "",
                ])
            else:
                table_data.append([
                    row.day_str,
                    row.franja,
                    row.slot_id,
                    row.presentiality,
                    row.work_mode,
                ])

        table = Table(table_data, colWidths=[35 * mm, 22 * mm, 48 * mm, 42 * mm, 35 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )
        build_pdf_with_fallback(doc, story)



def build_individual_calendar_pdfs(
    schedule_csv: str,
    professionals_csv: str,
    year: int,
    month: int,
    output_dir: str,
    professional_ids: set[str] | None = None,
    weekdays_only: bool = False,
) -> None:
    df = prepare_month_df(schedule_csv, year, month)
    names = load_professional_names(professionals_csv)
    styles = getSampleStyleSheet()
    if professional_ids is not None:
        df = df[df["professional"].astype(str).isin(professional_ids)].copy()
        if df.empty:
            raise ValueError(f"No hi ha dades individuals per {year}-{month:02d}")

    outdir = Path(output_dir)
    if outdir.exists() and professional_ids is None:
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    import datetime as _dtmod_i

    def _in_logical_i(d) -> bool:
        # Regla del dilluns aplicada al PDF individual (coherent amb la
        # resta del programa). Vegeu nota a build_general_calendar_pdf.
        mon = d - _dtmod_i.timedelta(days=d.weekday())
        return mon.year == year and mon.month == month

    first_day = pd.Timestamp(year=year, month=month, day=1)
    last_day = first_day + pd.offsets.MonthEnd(0)
    calendar_start = first_day - pd.Timedelta(days=first_day.weekday())
    calendar_end = last_day + pd.Timedelta(days=(6 - last_day.weekday()))
    calendar_days = pd.date_range(calendar_start, calendar_end, freq="D")

    all_weeks = [calendar_days[i:i+7] for i in range(0, len(calendar_days), 7)]
    weeks = [
        wk for wk in all_weeks
        if len(wk) > 0 and _in_logical_i(wk[0].date())
    ]
    weekday_headers = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    visible_weekday_indices = list(range(5)) if weekdays_only else list(range(7))
    weekday_headers = [weekday_headers[i] for i in visible_weekday_indices]

    for professional_id in sorted(df["professional"].astype(str).unique()):
        pdf_path = outdir / f"individual_calendar_{professional_id}_{year}_{month:02d}.pdf"
        prof_df = df[df["professional"].astype(str) == professional_id].copy()
        prof_df["day_date"] = pd.to_datetime(prof_df["day_str"])

        story = []
        display_name = names.get(professional_id, "")
        title = f"Planning calendario - {professional_id}"
        if display_name:
            title += f" - {display_name}"

        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(month_name_es(year, month), styles["Heading2"]))
        story.append(Spacer(1, 4 * mm))

        table_data = [weekday_headers]

        for week in weeks:
            row_cells = []
            for day in [week[i] for i in visible_weekday_indices]:
                if not _in_logical_i(day.date()):
                    row_cells.append("")
                    continue

                day_rows = prof_df[prof_df["day_date"] == day].copy()
                lines = [f"<b>{day.day}</b>"]
                if not day_rows.empty:
                    day_rows = day_rows.sort_values(["franja_order", "slot_order", "slot_id"])
                    for r in day_rows.itertuples(index=False):
                        compact = individual_compact_label(r.slot_id)
                        if compact is not None:
                            lines.append(compact)
                        else:
                            lines.append(
                                f"{r.franja} | {r.slot_id} | {short_presentiality(r.presentiality)} | {short_work_mode(r.work_mode)}"
                            )

                row_cells.append("<br/>".join(lines))
            table_data.append([Paragraph(cell, styles["BodyText"]) if cell else "" for cell in row_cells])

        table = Table(
            table_data,
            colWidths=[(273 / len(weekday_headers)) * mm] * len(weekday_headers),
            rowHeights=[10 * mm] + [34 * mm] * len(weeks),
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=landscape(A4),
            leftMargin=10 * mm,
            rightMargin=10 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm,
        )
        build_pdf_with_fallback(doc, story)


def build_weekday_by_professional_pdf(
    schedule_csv: str,
    professionals_csv: str,
    year: int,
    month: int,
    output_pdf: str,
) -> None:
    """PDF amb estructura facultatiu × dies: una fila per facultatiu, una
    columna per dia laborable del mes. Cada cel·la mostra l'activitat
    (inicial de franja + nom de l'slot) amb color de fons segons la
    localització (àrea definida per l'usuari). Aprofita tota la pàgina apaïsada."""
    df = prepare_month_df(schedule_csv, year, month)
    df = df[df["day"].dt.weekday < 5].copy()
    if df.empty:
        raise ValueError(f"No hi ha dades d'entre setmana per {year}-{month:02d}")

    weekday_names = ["Dl", "Dm", "Dc", "Dj", "Dv"]

    days = sorted(df["day_str"].unique())
    day_dt = {d: pd.Timestamp(d) for d in days}
    # prepare_month_df ja ha filtrat professionals buits/NONE/NAN.
    profs = sorted(df["professional"].unique())

    # Color del text segons la presencialitat (fons sempre blanc):
    # verd = presencial, blau = no presencial. La peonada
    # (extraordinària) es marca amb la sigla PEO.
    _NEUTRAL_COLOR = "#1F2937"

    # (prof, dia) -> llista de (ordre_franja, html) ordenada. Cada activitat
    # és una línia: "F SLOT [PEO]" amb color segons presencialitat.
    cell_map: dict = {}
    max_chars = 6
    for row in df.itertuples(index=False):
        prof = str(row.professional).strip()
        fr = str(row.franja).strip().upper()
        token_fr = FRANJA_INITIAL.get(fr, fr[:1])
        slot = str(row.slot_id).strip().upper()
        is_peonada = str(row.work_mode).strip().upper() == "PEONADA"
        pres = str(row.presentiality).strip().upper()
        is_presencial = pres == "PRESENCIAL"
        if is_presencial:
            color = PRESENCIAL_TEXT_COLOR
        elif pres == "NO_PRESENCIAL":
            color = NO_PRESENCIAL_TEXT_COLOR
        else:
            color = _NEUTRAL_COLOR
        label = f"{token_fr} {slot}".strip()
        if is_peonada:
            label = f"{label} PEO"
        max_chars = max(max_chars, len(label))
        inner = f"<b>{escape(label)}</b>" if is_presencial else escape(label)
        html = f'<font color="{color}">{inner}</font>'
        cell_map.setdefault((prof, str(row.day_str)), []).append(
            (franja_sort_key(fr), html)
        )

    n_days = len(days)
    n_profs = max(1, len(profs))
    max_lines = max((len(v) for v in cell_map.values()), default=1)

    # Mida de pàgina (A4 apaïsat). La taula s'AJUSTA per omplir tota la
    # pàgina tant si hi ha pocs com molts facultatius: l'alçada de fila i
    # la mida de lletra es deriven de l'espai real disponible.
    page_w, page_h = landscape(A4)
    margin = 5 * mm
    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin

    label_w = 24 * mm
    day_w = (usable_w - label_w) / max(1, n_days)
    col_widths = [label_w] + [day_w] * n_days

    reserve = 24 * mm  # títol + llegenda + espaiats
    table_h = usable_h - reserve
    pad = 3.0  # TOP+BOTTOM padding de cada cel·la (punts)
    # Repartiment vertical: capçalera ≈ 1.4 files.
    row_h = table_h / (n_profs + 1.4)
    header_h = 1.4 * row_h

    # Lletra que cap a la cel·la per alçada (línies) i per amplada (chars).
    font_by_h = (row_h - 2 * pad) / max(1, max_lines) / 1.18
    font_by_w = (day_w - 2 * pad) / (max_chars * 0.55)
    font = max(3.6, min(11.0, font_by_h, font_by_w))
    row_heights = [header_h] + [row_h] * n_profs

    cell_style = ParagraphStyle(
        "ByProfCell", fontName="Helvetica", fontSize=font,
        leading=font * 1.18, alignment=TA_CENTER, wordWrap="CJK",
    )
    hdr_style = ParagraphStyle(
        "ByProfHdr", fontName="Helvetica-Bold", fontSize=min(font + 1, 12),
        leading=(min(font + 1, 12)) * 1.2, alignment=TA_CENTER,
        textColor=colors.white,
    )
    name_style = ParagraphStyle(
        "ByProfName", fontName="Helvetica-Bold", fontSize=min(font + 1.5, 13),
        leading=(min(font + 1.5, 13)) * 1.2, alignment=TA_CENTER,
    )

    header = [Paragraph("Facultatiu", hdr_style)] + [
        Paragraph(f"{weekday_names[day_dt[d].weekday()]} {day_dt[d].day}", hdr_style)
        for d in days
    ]
    table_data = [header]
    style_cmds = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#334155")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    for prof in profs:
        rrow = [Paragraph(escape(prof), name_style)]
        for d in days:
            items = sorted(cell_map.get((prof, d), []))
            if items:
                rrow.append(Paragraph(
                    "<br/>".join(html for _, html in items), cell_style
                ))
            else:
                rrow.append("")
        table_data.append(rrow)

    table = Table(
        table_data, colWidths=col_widths, rowHeights=row_heights, repeatRows=1
    )
    table.setStyle(TableStyle(style_cmds))

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("ByProfTitle")
    title_style.fontSize = 13
    title_style.leading = 14
    title_style.spaceAfter = 0

    # Llegenda: color del text = presencialitat; sigla PEO = peonada;
    # inicials de franja. Fons blanc.
    leg_txt = ParagraphStyle("ByProfLegTxt", fontName="Helvetica", fontSize=7.5, leading=9)
    legend = Paragraph(
        f'<font color="{PRESENCIAL_TEXT_COLOR}"><b>Presencial</b></font> · '
        f'<font color="{NO_PRESENCIAL_TEXT_COLOR}"><b>No presencial</b></font> '
        "&nbsp;|&nbsp; PEO = peonada (extraordinària) &nbsp;|&nbsp; "
        "Franges: M = matí · T = tarda · N = nit",
        leg_txt,
    )

    content = [
        Paragraph(f"Planning per facultatiu - {month_name_ca(year, month)}", title_style),
        Spacer(1, 1.5 * mm),
        table,
        Spacer(1, 2 * mm),
        legend,
    ]
    # Encabir-ho tot en una sola pàgina (escala si cal) aprofitant
    # tota l'àrea útil.
    story = [KeepInFrame(usable_w, usable_h, content, mode="shrink", vAlign="TOP")]

    Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        output_pdf, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
    )
    build_pdf_with_fallback(doc, story)


def parse_args():
    parser = argparse.ArgumentParser(description="Exporta PDFs mensuals del planning.")
    parser.add_argument("schedule_csv")
    parser.add_argument("professionals_csv")
    parser.add_argument("year", type=int)
    parser.add_argument("month", type=int)
    parser.add_argument("output_dir")
    parser.add_argument("--professional", default=None)
    parser.add_argument("--individual-only", action="store_true")
    parser.add_argument("--general-only", action="store_true")
    parser.add_argument("--weekdays-only", action="store_true")
    parser.add_argument("--by-professional", action="store_true",
                        help="Genera només el PDF facultatiu × dies (abreujat).")
    parser.add_argument(
        "--no-operational-overlays", action="store_true",
        help="Amaga overlays operatius (absències, postguàrdies (PG) i "
             "marques (G)/(R) de guàrdia). S'usa per al calendari inicial, "
             "on el solver no ha considerat aquestes restriccions.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        from src.services.slot_catalog import (
            load_slot_catalog, slot_area_map, slot_metric_family_map,
            review_slot_ids,
        )
        from src.domain.schedule_format import (
            set_slot_area_overrides, set_slot_metric_overrides,
            set_slot_review_overrides,
        )
        _cat_path = Path("data/slot_catalog.csv")
        if _cat_path.exists():
            _cat = load_slot_catalog(_cat_path)
            set_slot_area_overrides(slot_area_map(_cat))
            set_slot_metric_overrides(slot_metric_family_map(_cat))
            set_slot_review_overrides(review_slot_ids(_cat))
    except Exception:
        pass

    schedule_csv = args.schedule_csv
    professionals_csv = args.professionals_csv
    year = args.year
    month = args.month
    output_dir = Path(args.output_dir)
    professional_ids = {args.professional} if args.professional else None
    weekdays_only = bool(args.weekdays_only)

    output_dir.mkdir(parents=True, exist_ok=True)

    general_calendar_pdf = output_dir / f"general_calendar_{year}_{month:02d}.pdf"
    individual_calendar_dir = output_dir / f"individual_calendars_{year}_{month:02d}"

    if args.by_professional:
        by_prof_pdf = output_dir / f"by_professional_{year}_{month:02d}.pdf"
        build_weekday_by_professional_pdf(
            schedule_csv, professionals_csv, year, month, str(by_prof_pdf),
        )
        print(f"PDF facultatiu × dies generat a: {by_prof_pdf}")
        return

    if not args.individual_only:
        build_general_calendar_pdf(
            schedule_csv,
            professionals_csv,
            year,
            month,
            str(general_calendar_pdf),
            weekdays_only=weekdays_only,
            show_operational_overlays=not args.no_operational_overlays,
        )
    if not args.general_only:
        build_individual_calendar_pdfs(
            schedule_csv,
            professionals_csv,
            year,
            month,
            str(individual_calendar_dir),
            professional_ids=professional_ids,
            weekdays_only=weekdays_only,
        )

    if not args.individual_only:
        print(f"PDF general tipo calendario generado en: {general_calendar_pdf}")
    if not args.general_only:
        print(f"PDFs individuales tipo calendario generados en: {individual_calendar_dir}")


if __name__ == "__main__":
    main()
