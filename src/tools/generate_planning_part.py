from pathlib import Path
import argparse
import pandas as pd

from src.core.data_loader import load_common_data, load_weekday_data
from src.modules.weekday_solver import solve_weekday
from src.services.schedule_io import (
    export_schedule,
    enrich_schedule_with_slot_metadata,
    filter_module_to_month,
    load_stability_assignments,
)


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path)
    return pd.DataFrame()


def _filter_out_generated_months(
    df: pd.DataFrame,
    year: int,
    start_month: int,
    end_month: int,
    date_col: str = "day",
) -> pd.DataFrame:
    """Treu les files generades al scope. El scope segueix la mateixa
    regla que `filter_module_to_month`: una setmana ISO pertany al mes
    del seu DILLUNS. Així una setmana que travessa el límit només es
    regenera quan es regenera el mes del seu dilluns."""
    if df.empty or date_col not in df.columns:
        return pd.DataFrame(columns=df.columns)
    out = df.copy()
    dates = pd.to_datetime(out[date_col], errors="coerce")
    monday_of_week = dates - pd.to_timedelta(dates.dt.weekday, unit="D")
    generated_scope = (
        (monday_of_week.dt.year == year)
        & (monday_of_week.dt.month >= start_month)
        & (monday_of_week.dt.month <= end_month)
    )
    return out.loc[~generated_scope.fillna(False)].copy()


def _filter_metrics_out_generated_months(
    df: pd.DataFrame,
    year: int,
    start_month: int,
    end_month: int,
) -> pd.DataFrame:
    if df.empty or "year_month" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    out = df.copy()
    year_month = pd.to_datetime(out["year_month"].astype(str) + "-01", errors="coerce")
    generated_scope = (
        (year_month.dt.year == year)
        & (year_month.dt.month >= start_month)
        & (year_month.dt.month <= end_month)
    )
    return out.loc[~generated_scope.fillna(False)].copy()


def _write_combined(
    frames: list[pd.DataFrame],
    output_path: str,
    existing_df: pd.DataFrame | None = None,
    year: int | None = None,
    start_month: int | None = None,
    end_month: int | None = None,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    preserved = pd.DataFrame()
    if (
        existing_df is not None
        and year is not None
        and start_month is not None
        and end_month is not None
    ):
        preserved = _filter_out_generated_months(existing_df, year, start_month, end_month)

    all_frames = [frame for frame in [preserved, *frames] if frame is not None and not frame.empty]
    if not all_frames:
        pd.DataFrame(columns=["day", "franja", "slot_id", "professional"]).to_csv(path, index=False)
        return
    out = pd.concat(all_frames, ignore_index=True).drop_duplicates()
    sort_cols = [col for col in ["day", "franja", "slot_id", "professional"] if col in out.columns]
    out = out.sort_values(sort_cols).reset_index(drop=True)
    out.to_csv(path, index=False)


def _solve_month_to_frame(result: dict, temp_output_path: Path) -> pd.DataFrame:
    temp_output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        export_schedule(result["schedule"], str(temp_output_path))
        enrich_schedule_with_slot_metadata(str(temp_output_path))
        return _read_csv_if_exists(temp_output_path)
    finally:
        temp_output_path.unlink(missing_ok=True)


def _accumulate_counts_by_presentiality(
    schedule_frames: list[pd.DataFrame],
    review_slots: set[str],
    target_presentiality: str,
    exclude_work_modes: tuple[str, ...] = (),
) -> dict[str, int]:
    """Comptador per facultatiu d'slots amb la presencialitat indicada,
    col·lapsant parells vinculats com fa la UI (un OR per (dia, parell-
    canònic)). Es fa servir entre mesos perquè el solver del mes N rebi
    l'acumulat dels mesos anteriors."""
    from src.services.slot_catalog import slot_link_pairs, load_slot_catalog
    try:
        catalog = load_slot_catalog(Path("data/slot_catalog.csv"))
        pairs = slot_link_pairs(catalog)
    except Exception:
        pairs = []
    link_partner = {}
    for a, b in pairs:
        link_partner[str(a).strip().upper()] = str(b).strip().upper()
        link_partner[str(b).strip().upper()] = str(a).strip().upper()
    review_upper = {str(s).strip().upper() for s in (review_slots or set())}
    target_upper = str(target_presentiality).strip().upper()
    exclude_wm = {str(w).strip().upper() for w in (exclude_work_modes or ())}
    counts: dict[str, int] = {}
    for df in schedule_frames:
        if df is None or df.empty:
            continue
        cols = set(df.columns)
        if not {"day", "slot_id", "presentiality"}.intersection(cols):
            continue
        prof_col = "professional" if "professional" in cols else "professional_id"
        seen_groups: set = set()
        for _, r in df.iterrows():
            sid = str(r.get("slot_id", "") or "").strip().upper()
            pres = str(r.get("presentiality", "") or "").strip().upper()
            wm = str(r.get("work_mode", "") or "").strip().upper()
            prof = str(r.get(prof_col, "") or "").strip().upper()
            if not prof or prof in {"", "NONE", "NAN"} or pres != target_upper:
                continue
            if sid in review_upper or wm in exclude_wm:
                continue
            partner = link_partner.get(sid)
            canon = min(sid, partner) if partner else sid
            key = (prof, str(r.get("day", "")), canon)
            if key in seen_groups:
                continue
            seen_groups.add(key)
            counts[prof] = counts.get(prof, 0) + 1
    return counts


def _accumulate_presential_counts(
    schedule_frames: list[pd.DataFrame],
    review_slots: set[str],
) -> dict[str, int]:
    """Wrapper compat: presencials. Vegeu _accumulate_counts_by_presentiality."""
    return _accumulate_counts_by_presentiality(schedule_frames, review_slots, "PRESENCIAL")


# Mapatge restriccio_key -> camps a preservar quan es "manté" només
# aquesta restricció. La resta de camps al common/weekday_input es
# blanquejen. Les que no apareixen aquí (guards, template_overrides) es
# preserven sempre perquè es consoliden al pre-procés abans del solver.
#
# Les claus ESTRUCTURALS (eligibility, absences, unavailability per
# guàrdies/postguàrdies) NO surten aquí: s'apliquen SEMPRE (al calendari
# inicial i al definitiu) perquè formen part de la pestanya Estructura.
_KEEP_FIELDS = {
    "comite": {"common.comite"},
    "tolerance": {"common.presential_tolerance"},
    "peonada_cap": {"common.peonada_cap"},
    "preassignments": {"weekday.preassignments"},
    "fixed_machines": {"common.slot_fixed_assignments"},
    "non_working_weekdays": {"professionals.non_working_weekdays"},
    "no_pres_weekdays": {"professionals.no_pres_weekdays"},
    "pres_weekdays": {"professionals.pres_weekdays"},
    "fallback": {"professionals.fallback"},
    "doubled_machines": {"professionals.doubled_machines"},
}


def _strip_optional_restrictions(
    common: dict, weekday_input: dict, keep: str | None = None,
) -> None:
    """NO-OP. Mantingut per compatibilitat amb les CLI flags antigues
    (`--initial`, `--keep-restriction`). Ara totes les restriccions
    s'apliquen sempre — només hi ha UN calendari (el de la pestanya
    «Calendari»). Aquesta funció és ara un placeholder per evitar
    haver de tocar tot el call site."""
    # Intentionally empty: cap restricció es buida.
    _ = (common, weekday_input, keep)


def generate_weekday(
    year: int, start_month: int, end_month: int,
    stability_from: str | None = None,
    initial: bool = False,
    keep_restriction: str | None = None,
    warm_start: bool = False,
) -> None:
    common = load_common_data("data")
    existing_schedule = _read_csv_if_exists(Path("outputs/schedule_weekday.csv"))
    existing_metrics = _read_csv_if_exists(Path("outputs/metrics_weekday.csv"))
    review_slots = common.get("review_slots") or set()
    schedule_frames = []
    metrics_frames = []
    month_count = max(1, end_month - start_month + 1)
    for month in range(start_month, end_month + 1):
        month_common = common.copy()
        weekday = filter_module_to_month(load_weekday_data("data/weekday", year=year), year, month)
        if initial:
            # Calendari INICIAL: ignora totes les restriccions opcionals
            # (s'aplicaran al Regenerar).
            _strip_optional_restrictions(month_common, weekday)
        elif keep_restriction:
            # Regenerar per-desplegable: només aplica la restricció
            # indicada; la resta s'esborra. La continuïtat amb el
            # definitiu actual la dóna el `stability_from`.
            _strip_optional_restrictions(
                month_common, weekday, keep=keep_restriction,
            )
        stability_assignments = load_stability_assignments(stability_from, year, month)
        # Cross-month: counts acumulats fins ara dins l'scope generat
        # (mesos anteriors d'aquesta tanda) per PRESENCIAL i NO_PRESENCIAL.
        # El primer mes rep dicts buits.
        prior_pres = _accumulate_counts_by_presentiality(
            schedule_frames, review_slots, "PRESENCIAL")
        prior_nopres = _accumulate_counts_by_presentiality(
            schedule_frames, review_slots, "NO_PRESENCIAL",
            exclude_work_modes=("PEONADA",),
        )
        month_common["prior_no_presential_counts"] = prior_nopres
        # Warm-start: sembra el solver amb el calendari anterior d'aquest
        # mes (hints, sense forçar) perquè el millori en lloc de recomençar.
        warm_month = None
        if (
            warm_start and existing_schedule is not None
            and not existing_schedule.empty
            and "day" in existing_schedule.columns
        ):
            from src.domain.month_scope import in_logical_month
            _wdays = pd.to_datetime(existing_schedule["day"], errors="coerce")
            warm_month = existing_schedule.loc[
                in_logical_month(_wdays, year, month)
            ].copy()
        result = solve_weekday(
            month_common, weekday,
            stability_assignments=stability_assignments,
            prior_presential_counts=prior_pres,
            warm_start_assignments=warm_month,
        )
        print(result["text"])
        if not result["ok"]:
            raise RuntimeError(f"No s'ha pogut generar el planning laborable de {year}-{month:02d}")
        schedule = _solve_month_to_frame(
            result,
            Path(f"outputs/.schedule_weekday_{year}_{month:02d}.tmp.csv"),
        )
        if not schedule.empty:
            schedule_frames.append(schedule)
        if result["metrics"]:
            metrics = pd.DataFrame(result["metrics"])
            metrics.insert(0, "year_month", f"{year}-{month:02d}")
            metrics_frames.append(metrics)

    _write_combined(
        schedule_frames,
        "outputs/schedule_weekday.csv",
        existing_schedule,
        year,
        start_month,
        end_month,
    )
    preserved_metrics = _filter_metrics_out_generated_months(
        existing_metrics,
        year,
        start_month,
        end_month,
    )
    metric_output_frames = [frame for frame in [preserved_metrics, *metrics_frames] if not frame.empty]
    if metric_output_frames:
        pd.concat(metric_output_frames, ignore_index=True).to_csv("outputs/metrics_weekday.csv", index=False)
    print("Planning laborable generat a outputs/schedule_weekday.csv")


def parse_args():
    parser = argparse.ArgumentParser(description="Genera el planning d'entre setmana.")
    # Es manté el positional `part` (només "weekday") per compatibilitat amb
    # la invocació de l'app. Ja no hi ha altres parts de generació.
    parser.add_argument("part", choices=["weekday"])
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    parser.add_argument("--stability-from", default=None)
    parser.add_argument(
        "--initial", action="store_true",
        help="Mode 'calendari inicial': ignora totes les restriccions "
             "opcionals (absències, guàrdies, comitès, elegibilitat, dies "
             "NP/PRES per facultatiu, indisponibilitats, preassignacions "
             "manuals, màquines fixes; tolerància=0, peonada_cap=3).",
    )
    parser.add_argument(
        "--keep-restriction", default=None,
        help="Quan es regenera, aplica NOMÉS aquesta restricció (la resta "
             "s'esborren com a --initial). Claus vàlides: " + ", ".join(
                 sorted(_KEEP_FIELDS.keys())
             ),
    )
    parser.add_argument(
        "--max-seconds", type=int, default=None,
        help="Pressupost de temps del solver per mes (segons). Més temps = "
             "més convergència (millor equilibri/peonades). Fixa "
             "PLANNER_SOLVER_MAX_SECONDS per a aquesta execució.",
    )
    parser.add_argument(
        "--warm-start", action="store_true",
        help="Parteix del calendari anterior (outputs/schedule_weekday.csv) "
             "com a punt de partida (hints) i el MILLORA, en lloc de "
             "recomençar de zero. Útil per refinar amb clics repetits.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import os
    args = parse_args()
    if args.max_seconds is not None and args.max_seconds > 0:
        os.environ["PLANNER_SOLVER_MAX_SECONDS"] = str(args.max_seconds)
    generate_weekday(
        args.year, args.start_month, args.end_month,
        stability_from=args.stability_from,
        initial=args.initial,
        keep_restriction=args.keep_restriction,
        warm_start=args.warm_start,
    )
