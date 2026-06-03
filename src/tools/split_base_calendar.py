from pathlib import Path
import sys
import pandas as pd


def split_base_calendar(
    base_calendar_csv: str,
    weekday_output: str,
    weekend_output: str | None = None,
) -> None:
    df = pd.read_csv(base_calendar_csv)

    required = {"day", "is_working_day"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Falten columnes requerides a base_calendar: {missing}")

    weekday_df = df.loc[df["is_working_day"] == 1, ["day", "is_working_day"]].copy()

    Path(weekday_output).parent.mkdir(parents=True, exist_ok=True)
    weekday_df.to_csv(weekday_output, index=False)
    print(f"Generado: {weekday_output}")

    if weekend_output:
        parsed_days = pd.to_datetime(df["day"], errors="coerce")
        is_holiday = pd.Series(False, index=df.index)
        for col in ["is_public_holiday", "is_ics_holiday", "is_extra_holiday"]:
            if col in df.columns:
                is_holiday |= df[col].fillna(0).astype(int) == 1
        force_working = pd.Series(False, index=df.index)
        if "force_working_day" in df.columns:
            force_working = df["force_working_day"].fillna(0).astype(int) == 1
        weekend_mask = (parsed_days.dt.weekday >= 5) & (~is_holiday | force_working)
        weekend_df = df.loc[weekend_mask, ["day"]].copy()
        weekend_df["is_working_day"] = 0
        Path(weekend_output).parent.mkdir(parents=True, exist_ok=True)
        weekend_df.to_csv(weekend_output, index=False)
        print(f"Generado: {weekend_output}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("Uso: python -m src.tools.split_base_calendar <base_calendar_csv> <weekday_output> [weekend_output]")
        sys.exit(1)

    split_base_calendar(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3] if len(sys.argv) == 4 else None,
    )
