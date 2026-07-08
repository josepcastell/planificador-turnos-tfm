from pathlib import Path
import sys
import pandas as pd


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        c = col.strip().lower()
        if c in {"any calendari", "any", "año", "ano"}:
            rename_map[col] = "year"
        elif c in {"data", "fecha", "date", "day"}:
            rename_map[col] = "date"
        elif c in {"localització", "localizacion", "localització ", "localitat", "localizacion "}:
            rename_map[col] = "location"
    return df.rename(columns=rename_map)


def parse_calendar_dates(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip()
    iso_mask = text.str.match(r"^\d{4}-\d{1,2}-\d{1,2}$", na=False)
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    parsed.loc[iso_mask] = pd.to_datetime(text.loc[iso_mask], format="%Y-%m-%d", errors="coerce")
    parsed.loc[~iso_mask] = pd.to_datetime(text.loc[~iso_mask], dayfirst=True, errors="coerce")
    return parsed


def build_base_calendar(import_csv: str, year: int, overrides_csv: str, output_csv: str) -> None:
    df = pd.read_csv(import_csv)
    df = normalize_columns(df)

    required = {"date"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas requeridas en el CSV importado: {missing}")

    df["date"] = parse_calendar_dates(df["date"])
    df = df.dropna(subset=["date"]).copy()

    if "year" not in df.columns:
        df["year"] = df["date"].dt.year

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df[df["year"] == year].copy()

    if df.empty:
        # Un import sense festius per a l'any NO és fatal: el calendari base
        # es construeix igualment amb els caps de setmana i, sobretot, amb
        # els OVERRIDES (festius extra/ICS, dies forçats). Així la generació
        # no peta encara que `public_holidays_{year}.csv` estigui buit (p. ex.
        # en una sessió nova on només hi ha els overrides).
        print(
            f"AVÍS: cap festiu públic per a l'any {year} a l'import; "
            "es construeix el calendari amb caps de setmana + overrides."
        )

    start = pd.Timestamp(year=year, month=1, day=1)
    end = pd.Timestamp(year=year, month=12, day=31)
    all_days = pd.DataFrame({"day": pd.date_range(start=start, end=end, freq="D")})

    holidays = df[["date"]].drop_duplicates().rename(columns={"date": "day"})
    holidays["is_public_holiday"] = 1

    base = all_days.merge(holidays, on="day", how="left")
    base["is_public_holiday"] = base["is_public_holiday"].fillna(0).astype(int)

    base["year"] = year
    base["is_weekend"] = base["day"].dt.weekday.isin([5, 6]).astype(int)
    base["is_ics_holiday"] = 0
    base["is_extra_holiday"] = 0
    base["force_working_day"] = 0
    base["notes"] = ""

    overrides_path = Path(overrides_csv)
    if overrides_path.exists() and overrides_path.stat().st_size > 0:
        overrides = pd.read_csv(overrides_path)
        if not overrides.empty:
            overrides["day"] = parse_calendar_dates(overrides["day"])
            overrides = overrides.dropna(subset=["day"]).copy()

            for col in ["is_ics_holiday", "is_extra_holiday", "force_working_day", "day_type", "notes"]:
                if col not in overrides.columns:
                    overrides[col] = None

            base = base.merge(
                overrides[["day", "is_ics_holiday", "is_extra_holiday", "force_working_day", "day_type", "notes"]],
                on="day",
                how="left",
                suffixes=("", "_override"),
            )

            for col in ["is_ics_holiday", "is_extra_holiday", "force_working_day"]:
                base[col] = base[f"{col}_override"].combine_first(base[col]).fillna(0).astype(int)
                base.drop(columns=[f"{col}_override"], inplace=True)

            base["notes"] = base["notes_override"].combine_first(base["notes"]).fillna("")
            base.drop(columns=["notes_override"], inplace=True)

            manual_day_type = base["day_type_override"] if "day_type_override" in base.columns else None
            if manual_day_type is not None:
                base.drop(columns=["day_type_override"], inplace=True)
        else:
            manual_day_type = None
    else:
        manual_day_type = None

    holiday_like = (
        (base["is_weekend"] == 1)
        | (base["is_public_holiday"] == 1)
        | (base["is_ics_holiday"] == 1)
        | (base["is_extra_holiday"] == 1)
    )

    base["is_working_day"] = (~holiday_like).astype(int)
    base.loc[base["force_working_day"] == 1, "is_working_day"] = 1

    base["day_type"] = "laborable"
    base.loc[base["is_weekend"] == 1, "day_type"] = "fin_de_semana"
    base.loc[base["is_public_holiday"] == 1, "day_type"] = "festivo_general"
    base.loc[base["is_ics_holiday"] == 1, "day_type"] = "festivo_ics"
    base.loc[base["is_extra_holiday"] == 1, "day_type"] = "festivo_extra"
    base.loc[base["force_working_day"] == 1, "day_type"] = "laborable"

    if manual_day_type is not None:
        mask = manual_day_type.notna() & (manual_day_type.astype(str).str.strip() != "")
        base.loc[mask, "day_type"] = manual_day_type[mask].astype(str)

    base["day"] = base["day"].dt.strftime("%Y-%m-%d")

    final_cols = [
        "day",
        "year",
        "is_weekend",
        "is_public_holiday",
        "is_ics_holiday",
        "is_extra_holiday",
        "is_working_day",
        "day_type",
        "notes",
    ]
    base = base[final_cols].sort_values("day")

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    base.to_csv(output_csv, index=False)
    print(f"Calendario base generado en: {output_csv}")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "Uso: python -m src.tools.build_base_calendar <import_csv> <year> <overrides_csv> <output_csv>"
        )
        sys.exit(1)

    import_csv = sys.argv[1]
    year = int(sys.argv[2])
    overrides_csv = sys.argv[3]
    output_csv = sys.argv[4]

    build_base_calendar(import_csv, year, overrides_csv, output_csv)
