def months_for_scope(scope: str, selected_month: int, selected_quarter: int, selected_semester: int) -> list[int]:
    if scope == "Tot l'any":
        return list(range(1, 13))
    if scope == "Semestre":
        return list(range(1, 7)) if selected_semester == 1 else list(range(7, 13))
    if scope == "Trimestre":
        start = (selected_quarter - 1) * 3 + 1
        return list(range(start, start + 3))
    return [selected_month]


def planning_scope_label(scope: str, selected_year: int, selected_months: list[int]) -> str:
    if scope == "Tot l'any":
        return f"{selected_year}"
    if len(selected_months) == 1:
        return f"{selected_year}-{selected_months[0]:02d}"
    return f"{selected_year}-{selected_months[0]:02d} a {selected_year}-{selected_months[-1]:02d}"


def clamp_month(value, fallback: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(12, max(1, parsed))
