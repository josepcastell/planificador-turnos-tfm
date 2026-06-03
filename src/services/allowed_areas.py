"""Helpers per traduir `professionals.allowed_areas` en files
d'eligibility (allowed=0) per als slots fora del llistat d'àrees
permeses del facultatiu.

Si un facultatiu té `allowed_areas = "HUB;DELTA"`, no se li pot
assignar cap slot ubicat a una altra àrea (p.ex. DIR). Si el camp
està buit, no s'apliquen restriccions (pot anar a qualsevol lloc).

S'invoca des de `src/modules/weekday_solver.py` per estendre la
taula d'eligibility abans de passar-la al solver."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


_ELIG_COLS = ["professional_id", "slot_id", "allowed"]


def _parse_areas(value) -> set[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return set()
    return {
        part.strip().upper()
        for part in str(value).split(";")
        if part.strip()
    }


def allowed_areas_eligibility_blocks(
    professionals_df: pd.DataFrame,
    slot_catalog_path: Path | str = "data/slot_catalog.csv",
) -> pd.DataFrame:
    """Per cada facultatiu amb `allowed_areas` no buit, retorna files
    (professional_id, slot_id, allowed=0) per a tots els slots del
    catàleg ubicats fora de les àrees permeses.

    Es concatena amb la taula d'eligibility de l'usuari abans de
    passar-la al solver. Si la mateixa parella ja existeix amb un
    valor d'allowed concret, l'usuari guanya (es deduplica deixant
    el primer)."""
    if (
        professionals_df is None or professionals_df.empty
        or "allowed_areas" not in professionals_df.columns
    ):
        return pd.DataFrame(columns=_ELIG_COLS)

    cat_path = Path(slot_catalog_path)
    if not cat_path.exists():
        return pd.DataFrame(columns=_ELIG_COLS)
    try:
        cat = pd.read_csv(cat_path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame(columns=_ELIG_COLS)
    if "slot_id" not in cat.columns or "area" not in cat.columns:
        return pd.DataFrame(columns=_ELIG_COLS)

    cat["_sid"] = cat["slot_id"].astype(str).str.strip().str.upper()
    cat["_area"] = cat["area"].astype(str).str.strip().str.upper()
    cat = cat[cat["_sid"] != ""].copy()
    # Els slots sense àrea definida (p.ex. revisions REV TC/REV RM) NO
    # tenen ubicació física: `allowed_areas` només limita on es desplaça
    # el facultatiu, així que no poden quedar bloquejats per àrea (i, ara
    # que el bloqueig és HARD, podrien fer la cobertura infeasible).
    cat = cat[~cat["_area"].isin({"", "NAN", "NONE"})].copy()

    rows = []
    for prof_row in professionals_df.itertuples(index=False):
        pid = str(getattr(prof_row, "professional_id", "") or "").strip().upper()
        if not pid or pid == "NONE":
            continue
        allowed = _parse_areas(getattr(prof_row, "allowed_areas", ""))
        if not allowed:
            continue
        blocked = cat[~cat["_area"].isin(allowed)]
        for sid in blocked["_sid"].unique():
            rows.append({
                "professional_id": pid,
                "slot_id": str(sid),
                "allowed": 0,
            })
    return pd.DataFrame(rows, columns=_ELIG_COLS)
