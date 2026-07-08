from pathlib import Path
import sys
import pandas as pd


from src.domain.constants import ABSENCE_TYPES

VALID_ABSENCE_TYPES = set(ABSENCE_TYPES)

# Maps both current Catalan values and legacy Spanish values to canonical Catalan
_ABSENCE_ALIASES: dict[str, str] = {
    # Catalan (canonical)
    "vacances": "vacances",
    "baixa": "baixa",
    "permis": "permis",
    "assumptes_propis": "assumptes_propis",
    "maternitat_paternitat": "maternitat_paternitat",
    "formacio": "formacio",
    "formació": "formacio",
    "vaga": "vaga",
    "altres_absencies": "altres_absencies",
    "altres_absències": "altres_absencies",
    # Legacy Spanish → Catalan
    "vacaciones": "vacances",
    "baja": "baixa",
    "permiso": "permis",
    "asuntos_propios": "assumptes_propis",
    "maternidad_paternidad": "maternitat_paternitat",
    "formacion": "formacio",
    "formación": "formacio",
    "congreso": "formacio",
    "huelga": "vaga",
    "huelga_total": "vaga",
    "otras_ausencias": "altres_absencies",
    "otras ausencias": "altres_absencies",
    "otra_ausencia": "altres_absencies",
}


def normalize_absence_type(value: str) -> str:
    s = str(value).strip().lower()
    return _ABSENCE_ALIASES.get(s, "altres_absencies")


def apply_absences_to_calendar(
    base_calendar_csv: str,
    absences_csv: str,
    output_unavailability_csv: str,
) -> None:
    base = pd.read_csv(base_calendar_csv)
    absences = pd.read_csv(absences_csv)

    required_base = {"day"}
    required_abs = {"professional_id", "start_day", "end_day", "absence_type"}

    missing_base = required_base - set(base.columns)
    missing_abs = required_abs - set(absences.columns)

    if missing_base:
        raise ValueError(f"Faltan columnas en base_calendar: {missing_base}")
    if missing_abs:
        raise ValueError(f"Faltan columnas en absences: {missing_abs}")

    if absences.empty:
        out = pd.DataFrame(columns=["professional_id", "day", "reason", "source", "notes"])
        Path(output_unavailability_csv).parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(output_unavailability_csv, index=False)
        print(f"Sin ausencias. Archivo generado vacío: {output_unavailability_csv}")
        return

    base["day"] = pd.to_datetime(base["day"], errors="coerce")
    base = base.dropna(subset=["day"]).copy()
    valid_days = set(base["day"])

    absences["start_day"] = pd.to_datetime(absences["start_day"], errors="coerce")
    absences["end_day"] = pd.to_datetime(absences["end_day"], errors="coerce")
    absences = absences.dropna(subset=["start_day", "end_day"]).copy()

    absences["absence_type"] = absences["absence_type"].apply(normalize_absence_type)

    if "notes" not in absences.columns:
        absences["notes"] = ""

    rows = []

    for row in absences.itertuples(index=False):
        if row.end_day < row.start_day:
            raise ValueError(
                f"Rango inválido para {row.professional_id}: "
                f"{row.start_day.date()} > {row.end_day.date()}"
            )

        days = pd.date_range(start=row.start_day, end=row.end_day, freq="D")

        for day in days:
            if day not in valid_days:
                continue

            rows.append(
                {
                    "professional_id": row.professional_id,
                    "day": day.strftime("%Y-%m-%d"),
                    "reason": row.absence_type,
                    "source": "absences",
                    "notes": row.notes,
                }
            )

    out = pd.DataFrame(rows).sort_values(["day", "professional_id", "reason"]).reset_index(drop=True)

    Path(output_unavailability_csv).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_unavailability_csv, index=False)

    print(f"Indisponibilidades derivadas generadas en: {output_unavailability_csv}")
    print(f"Total filas: {len(out)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Uso: python -m src.tools.apply_absences_to_calendar "
            "<base_calendar_csv> <absences_csv> <output_unavailability_csv>"
        )
        sys.exit(1)

    apply_absences_to_calendar(
        base_calendar_csv=sys.argv[1],
        absences_csv=sys.argv[2],
        output_unavailability_csv=sys.argv[3],
    )
