import calendar
import html
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.domain.constants import (
    CATALAN_MONTHS,
    GUARDS_RESERVED_SLOT_IDS,
    WEEKDAY_LABELS,
)
from src.domain.schedule_format import (
    calendar_display_area_class,
    calendar_display_assignment_class,
    calendar_display_compact_slot_label,
    calendar_display_day_status,
    calendar_display_franja_label,
    calendar_display_professional_label,
    calendar_display_slot_area,
    calendar_display_slot_sort_key,
    clean_display_value,
    franja_sort_key,
    is_review_slot,
)
from src.services.calendar_inputs import (
    load_absences_by_day,
    load_guard_schedule_by_day,
    load_public_holidays_table,
)


def _fallback_professional_ids() -> set[str]:
    """IDs (en majúscules) dels facultatius comodí (professionals.csv
    fallback=1), p.ex. TLD. Es marquen en vermell al calendari perquè
    ressaltin de cara als canvis manuals."""
    pp = Path("data/professionals.csv")
    if not pp.exists() or pp.stat().st_size == 0:
        return set()
    try:
        pdf = pd.read_csv(pp)
    except Exception:
        return set()
    if not {"professional_id", "fallback"}.issubset(pdf.columns):
        return set()
    fb = pd.to_numeric(pdf["fallback"], errors="coerce").fillna(0).astype(int)
    return {str(p).strip().upper() for p in pdf.loc[fb == 1, "professional_id"]}


def non_working_days_for_calendar(year: int, base_calendar_path: Path, public_holidays_path: Path) -> set[str]:
    if base_calendar_path.exists() and base_calendar_path.stat().st_size > 0:
        try:
            base = pd.read_csv(base_calendar_path)
            if {"day", "is_working_day"}.issubset(base.columns):
                base["day"] = pd.to_datetime(base["day"], errors="coerce")
                base["is_working_day"] = pd.to_numeric(base["is_working_day"], errors="coerce").fillna(1).astype(int)
                return set(
                    base.loc[
                        (base["day"].dt.year == year) & (base["is_working_day"] == 0),
                        "day",
                    ].dt.strftime("%Y-%m-%d")
                )
        except Exception:
            pass

    non_working = set()
    for day_num in range(1, 367):
        try:
            current = date(year, 1, 1) + timedelta(days=day_num - 1)
        except ValueError:
            continue
        if current.year != year:
            break
        if current.weekday() >= 5:
            non_working.add(current.strftime("%Y-%m-%d"))

    holidays = load_public_holidays_table(public_holidays_path)
    if not holidays.empty:
        holiday_days = pd.to_datetime(holidays["day"], errors="coerce")
        non_working.update(holiday_days.dropna().dt.strftime("%Y-%m-%d").tolist())
    return non_working


def render_schedule_calendar_html(
    schedule_df: pd.DataFrame,
    year: int,
    month_num: int,
    base_calendar_path: Path,
    public_holidays_path: Path,
    visible_weekdays: list[int] | None = None,
) -> str:
    if schedule_df.empty:
        return "<p>No hi ha calendari definitiu generat.</p>"

    from src.domain.month_scope import in_logical_month
    df = schedule_df.copy()
    df["day_dt"] = pd.to_datetime(df["day"], errors="coerce")
    df = df.dropna(subset=["day_dt"])
    df = df[
        in_logical_month(df["day_dt"], year, month_num)
        & (df["professional"].astype(str) != "NONE")
    ].copy()
    weekday_indices = visible_weekdays or list(range(7))
    df = df[df["day_dt"].dt.weekday.isin(weekday_indices)].copy()
    if df.empty:
        return "<p>No hi ha assignacions per aquest mes.</p>"

    for col in ["franja", "slot_id", "reporting_machine", "professional", "presentiality", "work_mode"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(clean_display_value)
    # is_flipped (0/1): marca slots flipats NP→PRES per al prefix "T-".
    if "is_flipped" not in df.columns:
        df["is_flipped"] = 0
    df["day_key"] = df["day_dt"].dt.strftime("%Y-%m-%d")
    df["franja_order"] = df["franja"].apply(franja_sort_key)
    df["slot_order"] = df["slot_id"].apply(calendar_display_slot_sort_key)
    df = df.sort_values(["day_key", "franja_order", "slot_order", "slot_id", "professional"])

    assignments_by_day: dict[str, list[dict[str, str]]] = {}
    for row in df.itertuples(index=False):
        assignments_by_day.setdefault(str(row.day_key), []).append({
            "franja": str(row.franja),
            "slot_id": str(row.slot_id),
            "reporting_machine": str(row.reporting_machine),
            "professional": str(row.professional),
            "presentiality": str(row.presentiality),
            "work_mode": str(row.work_mode),
            "is_flipped": str(getattr(row, "is_flipped", "") or ""),
        })

    non_working_days = non_working_days_for_calendar(year, base_calendar_path, public_holidays_path)
    fallback_ids = _fallback_professional_ids()

    guard_sched = load_guard_schedule_by_day(year)
    absences_sched = load_absences_by_day(year)

    def _is_reforc(kind: str) -> bool:
        return str(kind or "").strip().lower().startswith(
            ("refuerzo", "reforc", "reforç")
        )

    def guard_block_html(day_key: str) -> str:
        info = guard_sched.get(day_key) or {}
        lines = []
        for prof, kind in info.get("guards", []):
            label = "Reforç" if _is_reforc(kind) else "Guàrdia"
            lines.append(
                '<div class="schedule-guard-line" style="font-size:0.72rem;'
                'font-weight:600;color:#b91c1c;background:#ffedd5;'
                'border-radius:4px;padding:2px 6px;margin:2px 0;">'
                f'{label}: {html.escape(str(prof))}</div>'
            )
        # Absències reals + postguàrdia (marcada PG) en una sola línia.
        abs_items = list(absences_sched.get(day_key, []))
        abs_items += [f"{p} (PG)" for p in info.get("post", [])]
        if abs_items:
            names = ", ".join(html.escape(str(p)) for p in abs_items)
            lines.append(
                '<div class="schedule-absence-line" style="font-size:0.7rem;'
                'color:#475569;background:#f1f5f9;border-radius:4px;'
                'padding:2px 6px;margin:2px 0;">'
                f'Abs.: {names}</div>'
            )
        return "".join(lines)

    excluded_slots = GUARDS_RESERVED_SLOT_IDS
    slots = sorted(
        {
            clean_display_value(row["slot_id"]).upper()
            for rows in assignments_by_day.values()
            for row in rows
            if clean_display_value(row["slot_id"]).upper() not in excluded_slots
        },
        key=calendar_display_slot_sort_key,
    )
    franges = sorted(
        {
            clean_display_value(row["franja"]).upper()
            for rows in assignments_by_day.values()
            for row in rows
        },
        key=franja_sort_key,
    )
    if not franges:
        franges = ["12H"] if set(weekday_indices).issubset({5, 6}) else ["MATI", "TARDA", "NIT"]

    def chip_html(slot: str, rows: list[dict[str, str]]) -> str:
        machine_label = calendar_display_compact_slot_label(slot)
        reporting_labels = sorted({
            calendar_display_compact_slot_label(row["reporting_machine"])
            for row in rows
            if clean_display_value(row.get("reporting_machine"))
            and clean_display_value(row.get("reporting_machine")).upper() != clean_display_value(row.get("slot_id")).upper()
        })
        if reporting_labels:
            machine_label = f"{machine_label} ({'/'.join(reporting_labels)})"
        # Ordena les rows perquè els flips (T-) surtin sempre al final
        # (a una màquina doblada, el segon facultatiu és el que ha rebut
        # la conversió NP→PRES). Conserva l'ordre relatiu d'entrada per
        # als altres camps.
        def _flip_key(r: dict[str, str]) -> int:
            v = str(r.get("is_flipped", "") or "").strip()
            return 1 if v in {"1", "1.0", "True", "true"} else 0
        rows_sorted = sorted(rows, key=_flip_key)
        professionals = "/".join(
            html.escape(calendar_display_professional_label(row))
            for row in rows_sorted
            if clean_display_value(row.get("professional"))
        )
        tooltip_parts = []
        for row in rows:
            tooltip_parts.append(
                " · ".join(
                    part
                    for part in [
                        clean_display_value(row.get("slot_id")),
                        clean_display_value(row.get("reporting_machine")),
                        clean_display_value(row.get("presentiality")).replace("_", " ").title(),
                        "Peonada" if clean_display_value(row.get("work_mode")).upper() == "PEONADA" else "Ordinària",
                    ]
                    if part
                )
            )
        chip_class = calendar_display_assignment_class(rows, slot, fallback_ids)
        title = html.escape(" | ".join(tooltip_parts), quote=True)
        return (
            f'<div class="schedule-assignment-chip {chip_class}" title="{title}">'
            f'<span class="schedule-machine">{html.escape(machine_label)}</span>'
            f' · {professionals}'
            "</div>"
        )

    def day_body_html(day_assignments: list[dict[str, str]]) -> str:
        if not day_assignments:
            return '<div class="schedule-empty-note">Sense assignacions</div>'

        parts = []

        # Slots de revisió: són del DIA SENCER (no tenen franja). Es mostren
        # en un bloc propi, una vegada per slot, fora de les franges.
        review_rows = [
            row for row in day_assignments
            if is_review_slot(clean_display_value(row["slot_id"]))
        ]
        non_review = [
            row for row in day_assignments
            if not is_review_slot(clean_display_value(row["slot_id"]))
        ]
        if review_rows:
            review_slot_ids = sorted(
                {clean_display_value(r["slot_id"]).upper() for r in review_rows},
                key=calendar_display_slot_sort_key,
            )
            chips = []
            for slot in review_slot_ids:
                rows = [
                    r for r in review_rows
                    if clean_display_value(r["slot_id"]).upper() == slot
                ]
                if rows:
                    chips.append(chip_html(slot, rows))
            if chips:
                parts.append(
                    '<div class="schedule-franja-block">'
                    '<div class="schedule-franja-title">Revisió · dia sencer</div>'
                    '<div class="schedule-area-block">'
                    f'<div class="schedule-chip-list">{"".join(chips)}</div>'
                    '</div></div>'
                )

        for franja in franges:
            franja_rows = [
                row for row in non_review
                if clean_display_value(row["franja"]).upper() == franja
            ]
            if not franja_rows:
                continue
            franja_parts = [
                f'<div class="schedule-franja-title">{html.escape(calendar_display_franja_label(franja))}</div>'
            ]
            _areas_present = sorted(
                {calendar_display_slot_area(slot) for slot in slots},
                key=lambda a: (1, "") if a == "ALTRES" else (0, a),
            )
            for area in _areas_present:
                area_slots = [
                    slot for slot in slots
                    if calendar_display_slot_area(slot) == area
                    and any(clean_display_value(row["slot_id"]).upper() == slot for row in franja_rows)
                ]
                if not area_slots:
                    continue
                chips = []
                for slot in area_slots:
                    rows = [
                        row for row in franja_rows
                        if clean_display_value(row["slot_id"]).upper() == slot
                    ]
                    if rows:
                        chips.append(chip_html(slot, rows))
                if chips:
                    area_class = calendar_display_area_class(area)
                    franja_parts.append(
                        '<div class="schedule-area-block">'
                        f'<div class="schedule-area-title {area_class}">{html.escape(area)}</div>'
                        f'<div class="schedule-chip-list">{"".join(chips)}</div>'
                        '</div>'
                    )
            parts.append(f'<div class="schedule-franja-block">{"".join(franja_parts)}</div>')

        if not parts:
            return '<div class="schedule-empty-note">Sense assignacions</div>'
        return "".join(parts)

    import datetime as _dt
    cal = calendar.Calendar(firstweekday=0)
    week_blocks = []
    for week in cal.monthdatescalendar(year, month_num):
        visible_days = [day for day in week if day.weekday() in weekday_indices]
        # Regla "setmana pertany al mes del seu dilluns": només incloem
        # setmanes el dilluns de les quals és al month_num.
        week_monday = week[0] if week else None
        if (
            week_monday is None
            or week_monday.month != month_num
            or week_monday.year != year
        ):
            continue
        day_cards = []
        for current in visible_days:
            # El dilluns ja s'ha verificat que és al mes — els altres
            # dies de la setmana (potencialment de l'altre mes) s'inclouen.
            current_monday = current - _dt.timedelta(days=current.weekday())
            if current_monday.month != month_num or current_monday.year != year:
                day_cards.append('<div class="schedule-day-card empty"></div>')
                continue
            day_key = current.strftime("%Y-%m-%d")
            status = calendar_display_day_status(day_key, current, non_working_days)
            classes = " non-working" if status else ""
            day_assignments = assignments_by_day.get(day_key, [])
            status_html = f'<span class="schedule-day-status">{html.escape(status)}</span>' if status else ""
            guard_html = guard_block_html(day_key)
            body_html = day_body_html(day_assignments)
            if guard_html:
                body_html = guard_html if not day_assignments else guard_html + body_html
            day_cards.append(
                f'<div class="schedule-day-card{classes}">'
                f'<div class="schedule-day-header">{html.escape(WEEKDAY_LABELS[current.weekday()])} {current.day}{status_html}</div>'
                f'<div class="schedule-day-body">{body_html}</div>'
                '</div>'
            )
        week_blocks.append(
            f'<div class="schedule-calendar-week" style="grid-template-columns: repeat({len(visible_days)}, minmax(0, 1fr));">'
            f'{"".join(day_cards)}'
            '</div>'
        )

    # Llegenda d'àrees: dinàmica, a partir de les àrees definides per
    # l'usuari presents al mes (mateixa paleta que els blocs del calendari).
    _legend_areas = sorted(
        {
            calendar_display_slot_area(clean_display_value(r["slot_id"]).upper())
            for rows in assignments_by_day.values()
            for r in rows
        },
        key=lambda a: (1, "") if a == "ALTRES" else (0, a),
    )
    legend_area_items = "".join(
        '<span class="schedule-calendar-legend-item">'
        f'<span class="schedule-calendar-swatch {calendar_display_area_class(a)}"></span>'
        f'{html.escape(a)}</span>'
        for a in _legend_areas
        if a and a != "ALTRES"
    )

    return (
        '<div class="schedule-calendar">'
        f'<div class="schedule-calendar-title">{CATALAN_MONTHS.get(month_num, str(month_num))} {year}</div>'
        '<div class="schedule-calendar-legend">'
        f'{legend_area_items}'
        '<span class="schedule-calendar-legend-item"><span class="schedule-calendar-swatch" style="background:#cfe8d5"></span>Presencial</span>'
        '<span class="schedule-calendar-legend-item"><span class="schedule-calendar-swatch" style="background:#fee2e2;border:1px solid #dc2626"></span><b style="color:#b91c1c">Peonada</b></span>'
        '<span class="schedule-calendar-legend-item"><span class="schedule-calendar-swatch" style="background:#fef3c7;border:1px solid #d97706"></span><b style="color:#b45309">TLD</b></span>'
        '<span class="schedule-calendar-legend-item"><span class="schedule-calendar-swatch" style="background:#ffedd5"></span>'
        '<b style="color:#b91c1c">Guàrdia / Reforç</b></span>'
        '</div>'
        f'{"".join(week_blocks)}'
        "</div>"
    )
