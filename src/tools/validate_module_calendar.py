import sys
import pandas as pd


def validate_module_calendar(calendar_slots_csv: str, day_info_csv: str, expected_working_day: int, module_name: str) -> None:
    slots = pd.read_csv(calendar_slots_csv)
    day_info = pd.read_csv(day_info_csv)

    required_slots = {"day"}
    required_day_info = {"day", "is_working_day"}

    missing_slots = required_slots - set(slots.columns)
    missing_day_info = required_day_info - set(day_info.columns)

    if missing_slots:
        raise ValueError(f"[{module_name}] Faltan columnas en calendar_slots: {missing_slots}")
    if missing_day_info:
        raise ValueError(f"[{module_name}] Faltan columnas en day_info: {missing_day_info}")

    slot_days = sorted(set(slots["day"].astype(str)))
    day_map = dict(zip(day_info["day"].astype(str), day_info["is_working_day"]))

    unknown_days = [d for d in slot_days if d not in day_map]
    if unknown_days:
        raise ValueError(f"[{module_name}] Hay días en calendar_slots que no existen en day_info: {unknown_days}")

    wrong_days = [d for d in slot_days if int(day_map[d]) != expected_working_day]
    if wrong_days:
        expected_text = "d'entre setmana" if expected_working_day == 1 else "de cap de setmana"
        raise ValueError(f"[{module_name}] Estos días no son {expected_text} según day_info: {wrong_days}")

    print(f"[{module_name}] Validación correcta. {len(slot_days)} días revisados.")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "Uso: python -m src.tools.validate_module_calendar "
            "<calendar_slots_csv> <day_info_csv> <expected_working_day:0|1> <module_name>"
        )
        sys.exit(1)

    validate_module_calendar(
        calendar_slots_csv=sys.argv[1],
        day_info_csv=sys.argv[2],
        expected_working_day=int(sys.argv[3]),
        module_name=sys.argv[4],
    )
