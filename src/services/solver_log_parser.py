"""Parser del log del solver (outputs/solver_log.txt) per extreure els
valors residuals de shortfall/overage per tram. S'utilitza a la UI per
notificar quan el solver no ha pogut assolir el target setmanal."""
from __future__ import annotations

import re
from pathlib import Path


_TIER_HEADER_RE = re.compile(
    r"\[Tram (\d+): (\w+)\]\s+status=(\w+)\s+obj=([^\s]+)"
)
_TERM_RE = re.compile(
    r"^\s*·\s+(\w+)\s*=\s*(-?\d+)\s+\(pes\s+([\d,]+)\)"
)


def parse_solver_log(
    path: Path | None = None,
) -> dict:
    """Llegeix el log del solver i retorna un dict per tier:
        {
            "tiers": [
                {"name": "presencial", "status": "OPTIMAL", "obj": 0.0,
                 "terms": {"total_weekly_presential_shortfall": 2, ...}},
                ...
            ]
        }
    Si el fitxer no existeix, retorna {"tiers": []}."""
    p = Path(path) if path is not None else Path("outputs/solver_log.txt")
    if not p.exists() or p.stat().st_size == 0:
        return {"tiers": []}
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return {"tiers": []}

    tiers: list[dict] = []
    current: dict | None = None
    for line in content.splitlines():
        m = _TIER_HEADER_RE.search(line)
        if m:
            if current is not None:
                tiers.append(current)
            obj_str = m.group(4).strip()
            try:
                obj_val = float(obj_str) if obj_str not in ("N/A",) else None
            except ValueError:
                obj_val = None
            current = {
                "n": int(m.group(1)),
                "name": m.group(2),
                "status": m.group(3),
                "obj": obj_val,
                "terms": {},
            }
            continue
        if current is None:
            continue
        m2 = _TERM_RE.match(line)
        if m2:
            term_name = m2.group(1)
            try:
                value = int(m2.group(2))
            except ValueError:
                value = 0
            current["terms"][term_name] = value
    if current is not None:
        tiers.append(current)
    return {"tiers": tiers}


def collect_target_violations(summary: dict) -> dict[str, int]:
    """Extreu els valors de shortfall i overage dels tiers PRES i NP_ord.
    Retorna un dict pla amb 4 claus (0 si no apareixen al log)."""
    terms_all: dict[str, int] = {}
    for tier in summary.get("tiers", []):
        terms_all.update(tier.get("terms", {}))
    return {
        "pres_shortfall": int(terms_all.get(
            "total_weekly_presential_shortfall", 0
        )),
        "pres_overage": int(terms_all.get(
            "total_weekly_presential_overage", 0
        )),
        "np_shortfall": int(terms_all.get(
            "total_weekly_np_ord_shortfall", 0
        )),
        "np_overage": int(terms_all.get(
            "total_weekly_np_ord_overage", 0
        )),
    }
