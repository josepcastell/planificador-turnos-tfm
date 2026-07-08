from pathlib import Path
import argparse

from src.tools.export_monthly_pdfs import (
    build_general_calendar_pdf,
    build_individual_calendar_pdfs,
    prepare_month_df,
)


def export_year_pdfs(
    schedule_csv: str,
    professionals_csv: str,
    year: int,
    output_dir: str,
    start_month: int = 1,
    end_month: int = 12,
    professional_id: str | None = None,
    individual_only: bool = False,
    general_only: bool = False,
    weekdays_only: bool = False,
    show_operational_overlays: bool = True,
) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    professional_ids = {professional_id} if professional_id else None

    # Registra els overrides del catàleg (àrea/família/revisió) perquè el
    # PDF multi-mes es comporti igual que el d'un sol mes.
    try:
        from src.services.slot_catalog import (
            load_slot_catalog, review_slot_ids,
            slot_area_map, slot_metric_family_map,
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

    generated = 0
    for month in range(start_month, end_month + 1):
        try:
            prepare_month_df(schedule_csv, year, month)
        except ValueError:
            print(f"Sense dades per {year}-{month:02d}; salto aquest mes.")
            continue

        general_calendar_pdf = out / f"general_calendar_{year}_{month:02d}.pdf"
        individual_calendar_dir = out / f"individual_calendars_{year}_{month:02d}"

        if not individual_only:
            build_general_calendar_pdf(
                schedule_csv,
                professionals_csv,
                year,
                month,
                str(general_calendar_pdf),
                weekdays_only=weekdays_only,
                show_operational_overlays=show_operational_overlays,
            )
        if not general_only:
            build_individual_calendar_pdfs(
                schedule_csv,
                professionals_csv,
                year,
                month,
                str(individual_calendar_dir),
                professional_ids=professional_ids,
                weekdays_only=weekdays_only,
            )
        generated += 1

    if generated == 0:
        raise ValueError(f"No hi ha dades de planning per {year}")

    print(f"PDFs generats per {generated} mesos de {year} a {out}")


def parse_args():
    parser = argparse.ArgumentParser(description="Exporta PDFs anuals del planning.")
    parser.add_argument("schedule_csv")
    parser.add_argument("professionals_csv")
    parser.add_argument("year", type=int)
    parser.add_argument("output_dir")
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-month", type=int, default=12)
    parser.add_argument("--professional", default=None)
    parser.add_argument("--individual-only", action="store_true")
    parser.add_argument("--general-only", action="store_true")
    parser.add_argument("--weekdays-only", action="store_true")
    parser.add_argument(
        "--no-operational-overlays", action="store_true",
        help="Amaga overlays operatius (absències, postguàrdies (PG) i "
             "marques (G)/(R) de guàrdia). S'usa per al calendari inicial.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    export_year_pdfs(
        args.schedule_csv,
        args.professionals_csv,
        args.year,
        args.output_dir,
        start_month=args.start_month,
        end_month=args.end_month,
        professional_id=args.professional,
        individual_only=args.individual_only,
        general_only=args.general_only,
        weekdays_only=args.weekdays_only,
        show_operational_overlays=not args.no_operational_overlays,
    )


if __name__ == "__main__":
    main()
