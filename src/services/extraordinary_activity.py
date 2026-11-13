"""Cap (màxim) mensual de peonades per facultatiu (jornada completa),
editable per l'usuari a la pestanya Activitat. El solver permet com a
molt N peonades/mes proporcional a la jornada — round(N * capacity_pct
/ 100) — als slots NO_PRESENCIAL no-revisió. Les peonades emergeixen
NATURALMENT per absorbir l'excedent de NP sobre el target setmanal
(`target_NP_ord = target_machines − target_presential`). Vegeu
`_add_peonada_monthly_cap`."""
from pathlib import Path


DEFAULT_EXTRAORDINARY_CAP = 3


def load_extraordinary_cap(path: Path) -> int:
    try:
        v = int(Path(path).read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return DEFAULT_EXTRAORDINARY_CAP
    return max(0, v)


def save_extraordinary_cap(path: Path, value) -> None:
    try:
        v = max(0, int(value))
    except (TypeError, ValueError):
        v = DEFAULT_EXTRAORDINARY_CAP
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(v))
