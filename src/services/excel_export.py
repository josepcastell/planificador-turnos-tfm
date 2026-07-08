"""Exportació de l'schedule a un fitxer Excel (.xlsx).

Una única fulla «Calendari» amb la vista en quadrícula setmana × dia
(mimica del PDF setmanal). Cada dia té sub-columnes per màquina i
files [Header / Abs / Àrea / Màquina / Matí / Tarda / Nit / Revisió].
Cel·les verdes = presencial, blaves = no presencial, grogues =
peonada, gris = festiu. Prefix «T-» als slots flipats (NP→PRES
forçats)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.domain.schedule_format import (
    calendar_display_slot_area,
    calendar_display_slot_sort_key,
    is_review_slot,
)


_BASE_COLS = [
    "day", "franja", "slot_id", "presentiality", "work_mode",
]

# Estils visuals (fons + colors de text consistents amb el PDF).
_FILL_HEADER = PatternFill("solid", fgColor="334155")
# Paleta estable per àrea (mateixos colors/ordre que _AREA_PDF_PALETTE i les
# classes CSS .schedule-area-c1..c6).
_AREA_FILL_PALETTE = (
    PatternFill("solid", fgColor="DBEAFE"),
    PatternFill("solid", fgColor="DCFCE7"),
    PatternFill("solid", fgColor="EDE9FE"),
    PatternFill("solid", fgColor="FEF3C7"),
    PatternFill("solid", fgColor="FCE7F3"),
    PatternFill("solid", fgColor="CCFBF1"),
)
_FILL_AREA_OTHER = PatternFill("solid", fgColor="F8FAFC")
_FILL_PEONADA = PatternFill("solid", fgColor="FFF0C2")
_FILL_FESTIU = PatternFill("solid", fgColor="E5E7EB")
_FILL_LABEL = PatternFill("solid", fgColor="F1F5F9")
_BORDER_THIN = Border(*[Side(style="thin", color="CBD5E1")] * 4)
_FONT_HEADER = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
_FONT_LABEL = Font(name="Calibri", size=9, bold=True, color="334155")
_FONT_PRES = Font(name="Calibri", size=9, color="15803D")
_FONT_NP = Font(name="Calibri", size=9, color="1D4ED8")
_FONT_MIXED = Font(name="Calibri", size=9, color="334155")
_FONT_GUARD = Font(name="Calibri", size=9, bold=True, color="B91C1C")
_FONT_DEFAULT = Font(name="Calibri", size=9, color="334155")
_ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _area_fill(area: str) -> PatternFill:
    a = (area or "").strip().upper()
    if not a or a == "ALTRES":
        return _FILL_AREA_OTHER
    idx = sum((i + 1) * ord(c) for i, c in enumerate(a)) % len(_AREA_FILL_PALETTE)
    return _AREA_FILL_PALETTE[idx]


def _read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def _is_reforc(kind: str) -> bool:
    return str(kind or "").strip().lower().startswith(("refuerzo", "reforc", "reforç"))


def _guard_index(year: int | None, months: list[int] | None) -> dict:
    """Indexa guàrdies per dia (YYYY-MM-DD): {day: [(prof, kind)]}."""
    if year is None:
        return {}
    df = _read_csv_safe(Path("data/guards/assignments.csv"))
    if df.empty:
        return {}
    df = df.copy()
    df["_day"] = pd.to_datetime(df["day"], errors="coerce")
    df = df.dropna(subset=["_day"])
    out: dict = {}
    for _, row in df.iterrows():
        d = row["_day"].strftime("%Y-%m-%d")
        out.setdefault(d, []).append(
            (str(row["professional_id"]), str(row["guard_kind"]))
        )
    return out


def _abs_index(year: int | None, months: list[int] | None) -> dict:
    """Indexa absències per dia (YYYY-MM-DD): {day: [prof,...]}."""
    df = _read_csv_safe(Path("data/absences/assignments.csv"))
    if df.empty:
        return {}
    df = df.copy()
    df["_start"] = pd.to_datetime(df.get("start_day"), errors="coerce")
    df["_end"] = pd.to_datetime(df.get("end_day"), errors="coerce")
    df = df.dropna(subset=["_start", "_end"])
    out: dict = {}
    for _, row in df.iterrows():
        days = pd.date_range(row["_start"], row["_end"], freq="D")
        for d in days:
            out.setdefault(d.strftime("%Y-%m-%d"), []).append(
                str(row["professional_id"])
            )
    return out


def _post_guard_days(year: int | None) -> dict:
    """Dia → llista de facultatius en postguàrdia. Es deriva: post[d+1] = guards[d]."""
    if year is None:
        return {}
    df = _read_csv_safe(Path(f"data/derived/guard_constraints_{year}.csv"))
    if df.empty or "constraint_type" not in df.columns:
        return {}
    df = df[df["constraint_type"] == "post_guard_free"].copy()
    df["_day"] = pd.to_datetime(df["day"], errors="coerce")
    out: dict = {}
    for _, row in df.dropna(subset=["_day"]).iterrows():
        d = row["_day"].strftime("%Y-%m-%d")
        out.setdefault(d, []).append(str(row["professional_id"]))
    return out


_WEEKDAY_LABELS_CA = ["Dl", "Dm", "Dc", "Dj", "Dv"]


def _scope_title(year: int | None, months: list[int] | None) -> str:
    """Etiqueta del període per al títol (p.ex. «juny 2026» o
    «juny–juliol 2026»). Buida si no hi ha any."""
    from src.domain.month_scope import catalan_month_name
    if not year:
        return ""
    ms = [int(m) for m in (months or []) if 1 <= int(m) <= 12]
    if not ms:
        return str(year)
    if len(ms) == 1:
        return f"{catalan_month_name(ms[0])} {year}"
    return f"{catalan_month_name(ms[0])}–{catalan_month_name(ms[-1])} {year}"


def _cell_text_and_style(rows: pd.DataFrame) -> tuple[str, Font, PatternFill | None]:
    """Donat un DataFrame amb les files assignades a (day, franja, slot),
    retorna (text, font, fill_bg)."""
    if rows.empty:
        return "", _FONT_DEFAULT, None
    # Ordena: no-flipats primer, després flipats (perquè T- surt al segon).
    rows = rows.copy()
    rows["_flip"] = pd.to_numeric(rows.get("is_flipped", 0), errors="coerce").fillna(0).astype(int)
    rows = rows.sort_values(["_flip", "professional"]).reset_index(drop=True)
    parts = []
    has_pres = False
    has_np = False
    has_peonada = False
    for _, r in rows.iterrows():
        name = str(r.get("professional") or "").strip()
        if not name:
            continue
        if int(r["_flip"]) == 1:
            name = f"T-{name}"
        parts.append(name)
        pres = str(r.get("presentiality", "")).upper()
        if pres == "PRESENCIAL":
            has_pres = True
        elif pres == "NO_PRESENCIAL":
            has_np = True
        if str(r.get("work_mode", "")).upper() == "PEONADA":
            has_peonada = True
    text = "/".join(parts)
    if has_pres and not has_np:
        font = _FONT_PRES
    elif has_np and not has_pres:
        font = _FONT_NP
    else:
        font = _FONT_MIXED
    fill = _FILL_PEONADA if has_peonada else None
    return text, font, fill


def _area_sort_key(area: str) -> tuple[int, str]:
    """Ordre de les àrees: alfabètic, amb 'ALTRES' (sense àrea) al final."""
    a = str(area).strip().upper()
    return (1, "") if (not a or a == "ALTRES") else (0, a)


def _machines_for_day(week_df: pd.DataFrame, dstr: str) -> list[str]:
    """Llista ordenada (per àrea i slot) de màquines amb assignació un dia."""
    sub = week_df[week_df["day"] == dstr]
    if sub.empty:
        return []
    machines = sorted(set(sub["_sid"].tolist()))
    return sorted(
        machines,
        key=lambda m: (
            _area_sort_key(calendar_display_slot_area(m)),
            calendar_display_slot_sort_key(m),
            m,
        ),
    )


def _write_week_block(
    ws,
    week_days: list[pd.Timestamp],
    schedule_df: pd.DataFrame,
    guards_idx: dict,
    abs_idx: dict,
    post_idx: dict,
    festiu_days: set[str],
    start_row: int,
) -> int:
    """Escriu un bloc setmanal a `ws` amb el layout del PDF setmanal:
    cada dia té sub-columnes (una per màquina), i les files són
    [Header / Abs / Àrea / Màquina / Matí / Tarda / Nit]. Retorna la
    fila següent disponible després del bloc."""
    days_str = [d.strftime("%Y-%m-%d") for d in week_days]
    # Files de màquina (sense revisió/guàrdia/sense facultatiu) per al
    # bloc principal de franges.
    week_df = schedule_df[schedule_df["day"].isin(days_str)].copy()
    if "is_flipped" not in week_df.columns:
        week_df["is_flipped"] = 0
    week_df["_sid"] = week_df["slot_id"].astype(str).str.strip().str.upper()
    week_df["_pid"] = week_df["professional"].astype(str).str.strip().str.upper()
    week_df["_franja"] = week_df["franja"].astype(str).str.strip().str.upper()
    week_df = week_df[
        ~week_df["_sid"].isin(GUARDS_RESERVED_SLOT_IDS)
        & ~week_df["_pid"].isin({"", "NONE", "NAN"})
        & (week_df["_franja"].isin({"MATI", "TARDA", "NIT"}))
    ].copy()

    # Slots de revisió (dia sencer): files separades sota les franges.
    review_rows = schedule_df[
        schedule_df["day"].isin(days_str)
        & schedule_df["slot_id"].astype(str).map(is_review_slot)
        & ~schedule_df["professional"].astype(str).str.upper().isin({"", "NONE", "NAN"})
    ].copy()

    # Màquines per dia (només dies del bloc; festius queden sense
    # màquines però mantenim la columna).
    machines_per_day = {d: _machines_for_day(week_df, d.strftime("%Y-%m-%d")) for d in week_days}

    # Rang de columnes per dia (mínim 1 col, ampliada segons #màquines).
    day_ranges: dict = {}
    col = 2  # col 1 = etiqueta de fila
    for d in week_days:
        n = max(1, len(machines_per_day[d]))
        day_ranges[d] = (col, col + n - 1)
        col += n
    total_cols = col - 1
    n_cols = total_cols  # per a estendre fills

    def _set_label(r: int, label: str) -> None:
        c = ws.cell(row=r, column=1, value=label)
        c.fill = _FILL_LABEL
        c.font = _FONT_LABEL
        c.alignment = _ALIGN_CENTER
        c.border = _BORDER_THIN

    # ── Row 1: capçaleres dels dies (amb guàrdia/reforç en vermell).
    r = start_row
    # Etiqueta buida a la col 1.
    head_label = ws.cell(row=r, column=1, value="")
    head_label.fill = _FILL_HEADER
    head_label.border = _BORDER_THIN
    for d in week_days:
        c0, c1 = day_ranges[d]
        dstr = d.strftime("%Y-%m-%d")
        label = f"{_WEEKDAY_LABELS_CA[d.weekday()]} {d.day}"
        g = guards_idx.get(dstr) or []
        if g:
            gtxt = " · " + " ".join(
                f"{p} ({'R' if _is_reforc(k) else 'G'})" for p, k in g
            )
            label = label + gtxt
        cell = ws.cell(row=r, column=c0, value=label)
        cell.fill = _FILL_HEADER
        cell.font = _FONT_GUARD if g else _FONT_HEADER
        cell.alignment = _ALIGN_CENTER
        cell.border = _BORDER_THIN
        if c1 > c0:
            ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c1)
    r += 1

    # ── Row 2: absències (per dia, amb postguàrdia (PG)).
    _set_label(r, "Abs.")
    for d in week_days:
        c0, c1 = day_ranges[d]
        dstr = d.strftime("%Y-%m-%d")
        items = list(abs_idx.get(dstr, []))
        items += [f"{p} (PG)" for p in post_idx.get(dstr, [])]
        cell = ws.cell(row=r, column=c0, value=" ".join(items))
        cell.font = _FONT_DEFAULT
        cell.alignment = _ALIGN_CENTER
        cell.border = _BORDER_THIN
        if dstr in festiu_days:
            cell.fill = _FILL_FESTIU
        if c1 > c0:
            ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c1)
    r += 1

    # ── Row 3: ÀREA. Per a cada dia, fusiona màquines consecutives
    #          de la mateixa àrea amb el fons corresponent.
    _set_label(r, "Àrea")
    for d in week_days:
        c0, c1 = day_ranges[d]
        machines = machines_per_day[d]
        if not machines:
            # Cel·la buida (festiu o dia sense màquines).
            cell = ws.cell(row=r, column=c0, value="")
            cell.border = _BORDER_THIN
            if d.strftime("%Y-%m-%d") in festiu_days:
                cell.fill = _FILL_FESTIU
            continue
        # Agrupa per àrea (consecutives).
        i = 0
        while i < len(machines):
            cur_area = calendar_display_slot_area(machines[i])
            j = i
            while j < len(machines) and calendar_display_slot_area(machines[j]) == cur_area:
                j += 1
            cs = c0 + i
            ce = c0 + j - 1
            cell = ws.cell(row=r, column=cs, value=cur_area)
            cell.fill = _area_fill(cur_area)
            cell.font = _FONT_LABEL
            cell.alignment = _ALIGN_CENTER
            cell.border = _BORDER_THIN
            if ce > cs:
                ws.merge_cells(start_row=r, start_column=cs, end_row=r, end_column=ce)
            i = j
    r += 1

    # ── Row 4: MÀQUINA (una etiqueta per columna).
    _set_label(r, "Màquina")
    for d in week_days:
        c0, _c1 = day_ranges[d]
        machines = machines_per_day[d]
        dstr = d.strftime("%Y-%m-%d")
        if not machines:
            cell = ws.cell(row=r, column=c0, value="")
            cell.border = _BORDER_THIN
            if dstr in festiu_days:
                cell.fill = _FILL_FESTIU
            continue
        for i, m in enumerate(machines):
            cell = ws.cell(row=r, column=c0 + i, value=m)
            cell.font = _FONT_LABEL
            cell.alignment = _ALIGN_CENTER
            cell.border = _BORDER_THIN
            cell.fill = _area_fill(calendar_display_slot_area(m))
    r += 1

    # ── Rows 5,6,7: Matí, Tarda, Nit. Una cel·la per (dia, màquina).
    for franja in ("MATI", "TARDA", "NIT"):
        _set_label(r, franja.title())
        for d in week_days:
            c0, _c1 = day_ranges[d]
            dstr = d.strftime("%Y-%m-%d")
            machines = machines_per_day[d]
            if not machines:
                cell = ws.cell(row=r, column=c0, value="")
                cell.border = _BORDER_THIN
                if dstr in festiu_days:
                    cell.fill = _FILL_FESTIU
                continue
            for i, m in enumerate(machines):
                rows = week_df[
                    (week_df["day"] == dstr)
                    & (week_df["_sid"] == m)
                    & (week_df["_franja"] == franja)
                ]
                text, font, fill = _cell_text_and_style(rows)
                cell = ws.cell(row=r, column=c0 + i, value=text)
                cell.font = font
                cell.alignment = _ALIGN_CENTER
                cell.border = _BORDER_THIN
                if dstr in festiu_days and not text:
                    cell.fill = _FILL_FESTIU
                elif fill is not None:
                    cell.fill = fill
        r += 1

    # ── Revisions: una fila per slot de revisió. Span per dia
    #              (s'aplica al dia sencer; mostrem el facultatiu
    #              fusionant les màquines del dia).
    review_slots = sorted(
        {str(rr.slot_id).strip().upper() for rr in review_rows.itertuples(index=False)},
        key=calendar_display_slot_sort_key,
    )
    for sid in review_slots:
        _set_label(r, f"Rev. {sid}")
        for d in week_days:
            c0, c1 = day_ranges[d]
            dstr = d.strftime("%Y-%m-%d")
            rev_rows = review_rows[
                (review_rows["day"] == dstr)
                & (review_rows["slot_id"].astype(str).str.strip().str.upper() == sid)
            ]
            text, font, fill = _cell_text_and_style(rev_rows)
            cell = ws.cell(row=r, column=c0, value=text)
            cell.font = font
            cell.alignment = _ALIGN_CENTER
            cell.border = _BORDER_THIN
            if dstr in festiu_days and not text:
                cell.fill = _FILL_FESTIU
            if c1 > c0:
                ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c1)
        r += 1

    # Track max cols per a freeze i autosize aproximat
    ws._pdf_like_max_col = max(getattr(ws, "_pdf_like_max_col", 0), n_cols)
    return r + 1  # fila buida com a separador entre setmanes


def _non_working_days(year: int) -> set[str]:
    path = Path(f"data/base_calendar_{year}.csv")
    if not path.exists() or path.stat().st_size == 0:
        return set()
    df = pd.read_csv(path)
    if not {"day", "is_working_day"}.issubset(df.columns):
        return set()
    df["day"] = pd.to_datetime(df["day"], errors="coerce")
    df["is_working_day"] = pd.to_numeric(df["is_working_day"], errors="coerce").fillna(1).astype(int)
    return set(
        df.loc[df["is_working_day"] == 0, "day"]
        .dt.strftime("%Y-%m-%d")
    )


def _write_calendari_grid(
    writer,
    schedule_df: pd.DataFrame,
    year: int | None,
    months: list[int] | None,
) -> None:
    """Escriu la fulla «Calendari» com a quadrícula setmanal (mimica PDF)."""
    if "Calendari" in writer.book.sheetnames:
        del writer.book["Calendari"]
    ws = writer.book.create_sheet("Calendari", 0)

    # Carrega dades operatives (per a Abs i Guàrdia a la capçalera)
    guards_idx = _guard_index(year, months)
    abs_idx = _abs_index(year, months)
    post_idx = _post_guard_days(year) if year else {}
    festiu_days = _non_working_days(year) if year else set()

    # Determinar les setmanes del scope (només dilluns dins el mes lògic).
    df = schedule_df.copy()
    df["day"] = df["day"].astype(str)
    df["_day_dt"] = pd.to_datetime(df["day"], errors="coerce")
    if year is not None and months:
        from src.domain.month_scope import in_logical_months
        df = df[in_logical_months(df["_day_dt"], year, months)]
    df = df.dropna(subset=["_day_dt"]).copy()
    if df.empty:
        ws.cell(row=1, column=1, value="(sense assignacions per al scope)")
        return

    # Conjunt de dilluns únics al scope.
    df["_monday"] = df["_day_dt"] - pd.to_timedelta(df["_day_dt"].dt.weekday, unit="D")
    mondays = sorted(set(df["_monday"].dt.normalize()))

    # Amplada de columnes: col 1 = etiqueta de fila (Abs/Àrea/Màquina/
    # Matí/Tarda/Nit), cols 2+ = sub-columnes per (dia, màquina).
    ws.column_dimensions["A"].width = 10
    # Amplada per defecte de les sub-columnes (es pot ajustar més).
    for i in range(1, 50):
        ws.column_dimensions[get_column_letter(1 + i)].width = 9

    # Reservem la fila 1 per al títol; els blocs setmanals comencen a la 2.
    current_row = 2
    for mon in mondays:
        week_days = [mon + pd.Timedelta(days=k) for k in range(5)]
        # Salta setmanes sense cap assignació.
        days_str = {d.strftime("%Y-%m-%d") for d in week_days}
        if not (df["day"].isin(days_str)).any():
            continue
        current_row = _write_week_block(
            ws,
            week_days,
            df,
            guards_idx,
            abs_idx,
            post_idx,
            festiu_days,
            current_row,
        )

    max_col = max(2, getattr(ws, "_pdf_like_max_col", 2))

    # ── Títol (fila 1), fusionat sobre tota l'amplada del calendari.
    title = "Calendari entre setmana"
    period = _scope_title(year, months)
    if period:
        title = f"{title} · {period}"
    tcell = ws.cell(row=1, column=1, value=title)
    tcell.font = Font(name="Calibri", size=14, bold=True, color="1E293B")
    tcell.alignment = Alignment(horizontal="center", vertical="center")
    if max_col > 1:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    ws.row_dimensions[1].height = 30

    # Files de contingut més altes: amb el fit-to-page (escala uniforme),
    # unes files més altes fan que el calendari OMPLI tota l'alçada de
    # l'A4 apaïsat en lloc de quedar arraconat a dalt.
    for rr in range(2, current_row):
        ws.row_dimensions[rr].height = 30

    # Congela el títol i la columna d'etiquetes.
    ws.freeze_panes = "B2"

    # Impressió: HORITZONTAL (landscape) en A4, ajustada a UNA pàgina
    # (amplada i alçada) i centrada perquè aprofiti tota la pàgina.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9  # A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_options.horizontalCentered = True
    ws.print_options.verticalCentered = True
    ws.page_margins = PageMargins(
        left=0.3, right=0.3, top=0.4, bottom=0.4, header=0.2, footer=0.2,
    )


def _register_catalog_overrides() -> None:
    """Registra els overrides del catàleg (àrea/família/revisió) perquè
    la classificació de slots a l'Excel coincideixi amb la del PDF."""
    try:
        from src.services.slot_catalog import (
            load_slot_catalog, slot_area_map,
            slot_metric_family_map, review_slot_ids,
        )
        from src.domain.schedule_format import (
            set_slot_area_overrides, set_slot_metric_overrides,
            set_slot_review_overrides,
        )
        cat_path = Path("data/slot_catalog.csv")
        if cat_path.exists():
            cat = load_slot_catalog(cat_path)
            set_slot_area_overrides(slot_area_map(cat))
            set_slot_metric_overrides(slot_metric_family_map(cat))
            set_slot_review_overrides(review_slot_ids(cat))
    except (OSError, ImportError, AttributeError):
        pass


def export_schedule_to_excel(
    schedule_csv: Path,
    output_xlsx: Path,
    selected_months: list[int] | None = None,
    year: int | None = None,
) -> int:
    """Genera l'Excel amb la quadrícula PDF-like + fulles auxiliars.
    Retorna el nombre de files de l'schedule processades."""
    _register_catalog_overrides()
    schedule_csv = Path(schedule_csv)
    output_xlsx = Path(output_xlsx)
    if not schedule_csv.exists() or schedule_csv.stat().st_size == 0:
        return 0
    df = pd.read_csv(schedule_csv)
    if df.empty:
        return 0

    if year is not None or selected_months:
        from src.domain.month_scope import in_logical_months
        df = df.copy()
        df["_day_dt"] = pd.to_datetime(df["day"], errors="coerce")
        if year is not None and selected_months:
            df = df[in_logical_months(df["_day_dt"], year, selected_months)]
        elif year is not None:
            df = df[df["_day_dt"].dt.year == year]
        df = df.drop(columns=["_day_dt"])
        if df.empty:
            return 0

    cols_present = [c for c in _BASE_COLS if c in df.columns]
    df = df.sort_values(cols_present).reset_index(drop=True)

    output_xlsx.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        # Única fulla «Calendari» amb la quadrícula PDF-like.
        _write_calendari_grid(writer, df, year, selected_months)
    return int(len(df))
