from pathlib import Path
import sys
import pandas as pd


def split_unavailability_layer(
    unavailability_csv: str,
    base_calendar_csv: str,
    weekday_output_csv: str,
    weekend_output_csv: str | None = None,
) -> None:
    unav = pd.read_csv(unavailability_csv)
    base = pd.read_csv(base_calendar_csv)

    required_unav = {"professional_id", "day", "reason", "source", "notes"}
    required_base = {"day", "is_working_day"}

    missing_unav = required_unav - set(unav.columns)
    missing_base = required_base - set(base.columns)

    if missing_unav:
        raise ValueError(f"Faltan columnas en unavailability: {missing_unav}")
    if missing_base:
        raise ValueError(f"Faltan columnas en base_calendar: {missing_base}")

    for col in ("franja", "presentiality"):
        if col not in unav.columns:
            unav[col] = ""

    base["day"] = base["day"].astype(str)
    unav["day"] = unav["day"].astype(str)

    merged = unav.merge(
        base[["day", "is_working_day"]],
        on="day",
        how="left",
    )

    missing_days = merged.loc[merged["is_working_day"].isna(), "day"].drop_duplicates().tolist()
    if missing_days:
        raise ValueError(f"Hay días de indisponibilidad que no existen en base_calendar: {missing_days}")

    out_cols = ["professional_id", "day", "franja", "presentiality", "reason", "source", "notes"]
    sort_cols = ["day", "professional_id", "franja", "presentiality", "reason", "source"]

    weekday_df = merged.loc[merged["is_working_day"] == 1, out_cols].copy()
    weekday_df = weekday_df.sort_values(sort_cols).reset_index(drop=True)
    Path(weekday_output_csv).parent.mkdir(parents=True, exist_ok=True)
    weekday_df.to_csv(weekday_output_csv, index=False)
    print(f"Generado: {weekday_output_csv} ({len(weekday_df)} filas)")

    if weekend_output_csv:
        weekend_df = merged.loc[merged["is_working_day"] == 0, out_cols].copy()
        weekend_df = weekend_df.sort_values(sort_cols).reset_index(drop=True)
        Path(weekend_output_csv).parent.mkdir(parents=True, exist_ok=True)
        weekend_df.to_csv(weekend_output_csv, index=False)
        print(f"Generado: {weekend_output_csv} ({len(weekend_df)} filas)")


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        print(
            "Uso: python -m src.tools.split_unavailability_layer "
            "<unavailability_csv> <base_calendar_csv> <weekday_output_csv> [weekend_output_csv]"
        )
        sys.exit(1)

    split_unavailability_layer(
        unavailability_csv=sys.argv[1],
        base_calendar_csv=sys.argv[2],
        weekday_output_csv=sys.argv[3],
        weekend_output_csv=sys.argv[4] if len(sys.argv) == 5 else None,
    )
