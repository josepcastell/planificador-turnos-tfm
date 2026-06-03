"""Tolerància setmanal del target presencial (±ε): editable per
l'usuari a la pestanya Generar. Si en una setmana un facultatiu té
fins a ε presencials per sota o per sobre del target setmanal, no es
penalitza (i el solver no flipa per arreglar-ho).

Default 0: per defecte el solver intenta assolir el target EXACTE.
L'usuari pot pujar ε si vol relaxar el target i estalviar temps de
càlcul (menys flips, menys spread)."""
from pathlib import Path


DEFAULT_TOLERANCE = 0


def load_presential_tolerance(path: Path) -> int:
    try:
        v = int(Path(path).read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return DEFAULT_TOLERANCE
    return max(0, v)


def save_presential_tolerance(path: Path, value) -> None:
    try:
        v = max(0, int(value))
    except (TypeError, ValueError):
        v = DEFAULT_TOLERANCE
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(v))
