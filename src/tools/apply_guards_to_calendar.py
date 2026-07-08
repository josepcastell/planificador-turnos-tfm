from pathlib import Path
import sys
import pandas as pd


def normalize_guard_kind(value: str) -> str:
    s = str(value).strip().lower()
    if s in {"guardia", "guàrdia", "guardia "}:
        return "guardia"
    if s in {"refuerzo", "reforç", "refuerzo "}:
        return "refuerzo"
    raise ValueError(f"Tipo de guardia no reconocido: {value}")


def apply_guards_to_calendar(
    base_calendar_csv: str,
    guards_csv: str,
    output_constraints_csv: str,
) -> None:
    base = pd.read_csv(base_calendar_csv)
    guards = pd.read_csv(guards_csv)

    required_base = {"day"}
    required_guards = {"professional_id", "day", "guard_kind"}

    missing_base = required_base - set(base.columns)
    missing_guards = required_guards - set(guards.columns)

    if missing_base:
        raise ValueError(f"Faltan columnas en base_calendar: {missing_base}")
    if missing_guards:
        raise ValueError(f"Faltan columnas en guards: {missing_guards}")

    if guards.empty:
        out = pd.DataFrame(columns=["professional_id", "day", "constraint_type", "source_guard_kind", "notes"])
        Path(output_constraints_csv).parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(output_constraints_csv, index=False)
        print(f"Sin guardias. Archivo generado vacío: {output_constraints_csv}")
        return

    base["day"] = pd.to_datetime(base["day"], errors="coerce")
    base = base.dropna(subset=["day"]).copy()
    base_days = set(base["day"])

    guards["day"] = pd.to_datetime(guards["day"], errors="coerce")
    guards = guards.dropna(subset=["day"]).copy()
    guards["guard_kind"] = guards["guard_kind"].apply(normalize_guard_kind)

    if "notes" not in guards.columns:
        guards["notes"] = ""

    rows = []

    for row in guards.itertuples(index=False):
        if row.day not in base_days:
            raise ValueError(f"La guardia cae en un día que no existe en base_calendar: {row.day.date()}")

        # Siempre marcar el día de guardia/refuerzo
        rows.append(
            {
                "professional_id": row.professional_id,
                "day": row.day.strftime("%Y-%m-%d"),
                "constraint_type": "guard_day",
                "source_guard_kind": row.guard_kind,
                "notes": row.notes,
            }
        )

        # Solo guardia con noche -> libra el día siguiente
        if row.guard_kind == "guardia":
            next_day = row.day + pd.Timedelta(days=1)
            if next_day in base_days:
                rows.append(
                    {
                        "professional_id": row.professional_id,
                        "day": next_day.strftime("%Y-%m-%d"),
                        "constraint_type": "post_guard_free",
                        "source_guard_kind": row.guard_kind,
                        "notes": f"Derivado de guardia del {row.day.strftime('%Y-%m-%d')}",
                    }
                )

    out = pd.DataFrame(rows).sort_values(["day", "professional_id", "constraint_type"]).reset_index(drop=True)

    Path(output_constraints_csv).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_constraints_csv, index=False)

    print(f"Restricciones derivadas generadas en: {output_constraints_csv}")
    print(f"Total filas: {len(out)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Uso: python -m src.tools.apply_guards_to_calendar "
            "<base_calendar_csv> <guards_csv> <output_constraints_csv>"
        )
        sys.exit(1)

    apply_guards_to_calendar(
        base_calendar_csv=sys.argv[1],
        guards_csv=sys.argv[2],
        output_constraints_csv=sys.argv[3],
    )
