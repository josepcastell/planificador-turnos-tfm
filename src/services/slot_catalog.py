"""Master slot catalog: declarative list of slot IDs with auto-sync into weekday/weekend templates."""

from pathlib import Path

import pandas as pd

from src.domain.constants import (
    CORE_SLOT_IDS,
    GUARDS_RESERVED_SLOT_IDS,
)
from src.services.table_io import read_table, save_table

# Inert leftover: the catalog still carries a `weekend` column (kept for
# backwards-compatibility / forward use), so the seeding/sync helpers keep
# working even though no caller passes a weekend templates path anymore.
WEEKEND_SLOT_IDS: list[str] = []  # buit: cap nom de màquina real per defecte
WEEKEND_TEMPLATE_COLUMNS = [
    "weekday_name",
    "franja",
    "slot_id",
    "reporting_machine",
    "presentiality",
    "work_mode",
    "required_staff",
    "is_active",
    "doubled",
]


SLOT_CATALOG_COLUMNS = [
    "slot_id", "weekday", "weekend", "linked_to", "doubled",
    "review", "area", "metric_family", "assignee", "notes",
]
# NOTA: la columna `rotation` s'ha eliminat del catàleg. No tenia cap
# efecte real al solver (la funció `rotation_slot_ids` no es cridava).
# L'equitat de revisions (la "roda" real) s'aplica automàticament a
# tots els slots amb `review=1` sense `assignee` fix — vegeu core.py.

METRIC_FAMILY_VALUES = ("", "TC", "RM")


def _infer_metric_family_from_name(slot_id: str) -> str:
    s = str(slot_id).strip().upper()
    if "TC" in s:
        return "TC"
    if "RM" in s:
        return "RM"
    return ""


def slot_metric_family_map(catalog_df) -> dict:
    """{slot_id_upper: 'TC'|'RM'|''} a partir de la columna 'metric_family'.
    Si no existeix o és buida per a un slot, s'infereix del nom (compat)."""
    if catalog_df is None or catalog_df.empty or "slot_id" not in catalog_df.columns:
        return {}
    out: dict = {}
    has_col = "metric_family" in catalog_df.columns
    for row in catalog_df.itertuples(index=False):
        sid = str(getattr(row, "slot_id", "") or "").strip().upper()
        if not sid:
            continue
        raw = str(getattr(row, "metric_family", "") or "").strip().upper() if has_col else ""
        out[sid] = raw if raw in {"TC", "RM"} else _infer_metric_family_from_name(sid)
    return out

# La columna 'area' del catàleg és LLIURE: l'usuari hi posa l'àrea que vulgui.
# El programa no predefineix cap àrea (es mostra i s'agrupa verbatim).
AREA_VALUES = ("",)


def slot_area_map(catalog_df) -> dict:
    """{slot_id_upper: àrea} a partir de la columna 'area' del catàleg (el
    valor que hi posa l'usuari, verbatim, en majúscules). Sense columna o
    valor buit → ''. No s'infereix cap àrea del nom de l'slot."""
    if catalog_df is None or catalog_df.empty or "slot_id" not in catalog_df.columns:
        return {}
    out: dict = {}
    has_col = "area" in catalog_df.columns
    for row in catalog_df.itertuples(index=False):
        sid = str(getattr(row, "slot_id", "") or "").strip().upper()
        if not sid:
            continue
        out[sid] = str(getattr(row, "area", "") or "").strip().upper() if has_col else ""
    return out


def review_slot_ids(catalog_df) -> set:
    """Slots marcats com a revisió al catàleg (columna `review=1`). El
    catàleg és l'única font de veritat: NO s'usen prefixos de nom (REV*)
    com a fallback. Si el catàleg no té cap fila amb review=1, el conjunt
    retornat és buit i la resta del sistema tractarà tots els slots com
    a no-revisió."""
    import pandas as _pd
    if catalog_df is None or catalog_df.empty or "slot_id" not in catalog_df.columns:
        return set()
    if "review" not in catalog_df.columns:
        return set()
    ids = catalog_df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    flag = _pd.to_numeric(catalog_df["review"], errors="coerce").fillna(0).astype(int)
    return set(ids[flag == 1]) - {""}


# NOTA: `rotation_slot_ids` s'ha eliminat. El flag `rotation` al catàleg
# era mort (no es feia servir enlloc al solver). L'equitat de revisions
# l'aplica el bloc "Roda" de core.py per a tot slot amb `review=1` sense
# `assignee` fix, sense necessitat d'un flag addicional.


def doubled_extras_by_slot(catalog_df: pd.DataFrame) -> dict[str, int]:
    """Return {slot_id: doubled} (extra facultatius added on top of the global
    default, 0–2). Empty/invalid values → 0.
    """
    if catalog_df is None or catalog_df.empty or "doubled" not in catalog_df.columns:
        return {}
    out: dict[str, int] = {}
    for row in catalog_df.itertuples(index=False):
        slot_id = str(getattr(row, "slot_id", "") or "").strip().upper()
        if not slot_id:
            continue
        raw = getattr(row, "doubled", 0)
        try:
            n = int(raw) if not isinstance(raw, bool) else (1 if raw else 0)
        except (TypeError, ValueError):
            n = 1 if str(raw).strip().lower() in {"true", "yes", "1", "si", "sí"} else 0
        out[slot_id] = max(0, min(2, n))
    return out


def fixed_assignments_from_catalog(catalog_df: pd.DataFrame) -> dict[str, str]:
    """Return {slot_id: professional_id} for catalog rows with an assignee set."""
    if catalog_df is None or catalog_df.empty or "assignee" not in catalog_df.columns:
        return {}
    out: dict[str, str] = {}
    for row in catalog_df.itertuples(index=False):
        slot_id = str(getattr(row, "slot_id", "") or "").strip().upper()
        assignee = str(getattr(row, "assignee", "") or "").strip().upper()
        if slot_id and assignee:
            out[slot_id] = assignee
    return out


def slot_secondary_ids(catalog_df: pd.DataFrame) -> set[str]:
    """[LEGACY] Slot_ids que apareixen com a "màquina secundària" al
    camp `linked_to` del catàleg. La nova font de vinculació són els
    templates — vegeu `slot_linked_ids_from_templates`."""
    if "linked_to" not in catalog_df.columns or catalog_df.empty:
        return set()
    valid_ids = set(catalog_df["slot_id"].fillna("").astype(str).str.strip().str.upper()) - {""}
    out: set[str] = set()
    for row in catalog_df.itertuples(index=False):
        b = str(getattr(row, "linked_to", "") or "").strip().upper()
        if b and b in valid_ids:
            out.add(b)
    return out


def slot_linked_ids_from_templates(templates_df: pd.DataFrame) -> set[str]:
    """Slot_ids que apareixen com a **part d'alguna vinculació** als
    templates setmanals (`linked_to`). Inclou TANT el primari (slot_id
    amb linked_to no buit) com el secundari (valor de linked_to).

    Aquest conjunt s'usa per excloure tots dos costats de la parella
    del conjunt elegible de peonades (la regla diu: peonades només a
    màquines NP, no doblades i NO vinculades)."""
    if templates_df is None or templates_df.empty:
        return set()
    if "linked_to" not in templates_df.columns:
        return set()
    out: set[str] = set()
    _EMPTY = {"", "NAN", "NONE"}
    for row in templates_df.itertuples(index=False):
        a = str(getattr(row, "slot_id", "") or "").strip().upper()
        b = str(getattr(row, "linked_to", "") or "").strip().upper()
        if a in _EMPTY or b in _EMPTY:
            continue
        out.add(a)
        out.add(b)
    return out


def slot_link_pairs(catalog_df: pd.DataFrame) -> list[tuple[str, str]]:
    """[LEGACY] Pairs des del camp `linked_to` del catàleg. Es manté per
    compat però la nova UI escriu la vinculació al template per
    (dia, franja). Vegeu `slot_link_pairs_from_templates`."""
    if "linked_to" not in catalog_df.columns or catalog_df.empty:
        return []
    valid_ids = set(catalog_df["slot_id"].fillna("").astype(str).str.strip().str.upper()) - {""}
    pairs: set[tuple[str, str]] = set()
    for row in catalog_df.itertuples(index=False):
        a = str(getattr(row, "slot_id", "") or "").strip().upper()
        b = str(getattr(row, "linked_to", "") or "").strip().upper()
        if not a or not b or a == b:
            continue
        if b not in valid_ids:
            continue
        pairs.add(tuple(sorted((a, b))))
    return sorted(pairs)


# Nombre màxim de màquines per bloc vinculat (1 persona cobreix el bloc).
MAX_LINKED_GROUP = 5


def linked_groups(catalog_df: pd.DataFrame) -> list[list[str]]:
    """BLOCS de màquines vinculades (una sola persona les cobreix, compten
    com 1). Es deriven del camp `linked_to` del catàleg fent el tancament
    TRANSITIU: si B→A i C→A, el bloc és [A, B, C]. Retorna la llista de blocs
    (cada bloc = llista ordenada d'slot_ids, mida ≥ 2)."""
    if catalog_df is None or catalog_df.empty or "linked_to" not in catalog_df.columns:
        return []
    valid = {
        str(s).strip().upper()
        for s in catalog_df["slot_id"].fillna("").astype(str)
    } - {""}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for row in catalog_df.itertuples(index=False):
        a = str(getattr(row, "slot_id", "") or "").strip().upper()
        b = str(getattr(row, "linked_to", "") or "").strip().upper()
        if a and b and a != b and b in valid:
            union(a, b)

    groups: dict[str, list[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    return sorted([sorted(g) for g in groups.values() if len(g) >= 2])


def set_linked_group(catalog_df: pd.DataFrame, members) -> pd.DataFrame:
    """Vincula `members` (2..MAX_LINKED_GROUP) com un BLOC: tots apunten al
    primer (representant) via `linked_to`. Neteja vinculacions prèvies dels
    membres. Retorna el catàleg modificat (còpia)."""
    df = catalog_df.copy()
    if "linked_to" not in df.columns:
        df["linked_to"] = ""
    mem: list[str] = []
    for m in members or []:
        u = str(m).strip().upper()
        if u and u not in mem:
            mem.append(u)
    mem = mem[:MAX_LINKED_GROUP]
    if len(mem) < 2:
        return df
    rep = mem[0]
    # Dissol primer QUALSEVOL bloc previ que contingui algun membre (així un
    # slot que apuntava a un membre no queda enganxat al bloc nou).
    to_clear: set = set(mem)
    for g in linked_groups(df):
        if any(x in mem for x in g):
            to_clear.update(g)
    upper = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df.loc[upper.isin(to_clear), "linked_to"] = ""
    df.loc[upper.isin(mem[1:]), "linked_to"] = rep      # tots → representant
    return df


def clear_linked_group(catalog_df: pd.DataFrame, member: str) -> pd.DataFrame:
    """Desvincula el BLOC que conté `member` (neteja `linked_to` de tots els
    membres del bloc). Retorna el catàleg modificat (còpia)."""
    df = catalog_df.copy()
    if "linked_to" not in df.columns:
        return df
    m = str(member).strip().upper()
    target = next((g for g in linked_groups(df) if m in g), None)
    if not target:
        return df
    upper = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df.loc[upper.isin(target), "linked_to"] = ""
    return df


def slot_link_pairs_from_templates(templates_df: pd.DataFrame) -> list[tuple[str, str]]:
    """Pairs únics des del camp `linked_to` dels templates setmanals.
    Cada fila template (`weekday_name, franja, slot_id`) pot tenir el
    seu propi partner. La unió retorna la llista de pairs únics."""
    if templates_df is None or templates_df.empty:
        return []
    if "linked_to" not in templates_df.columns or "slot_id" not in templates_df.columns:
        return []
    pairs: set[tuple[str, str]] = set()
    for row in templates_df.itertuples(index=False):
        a = str(getattr(row, "slot_id", "") or "").strip().upper()
        b = str(getattr(row, "linked_to", "") or "").strip().upper()
        if not a or not b or a == b or b in {"NAN", "NONE"}:
            continue
        pairs.add(tuple(sorted((a, b))))
    return sorted(pairs)


def slot_link_pairs_by_weekday_franja(templates_df: pd.DataFrame) -> dict:
    """{(weekday_name, franja): [(slot_a, slot_b), ...]} des del camp
    `linked_to` dels templates setmanals, PER (dia-setmana, franja). Així una
    vinculació pot existir un dia/franja i no un altre. Les claus estan en
    MAJÚSCULES."""
    out: dict = {}
    if templates_df is None or templates_df.empty:
        return out
    if "linked_to" not in templates_df.columns or "slot_id" not in templates_df.columns:
        return out
    _EMPTY = {"", "NAN", "NONE"}
    for row in templates_df.itertuples(index=False):
        a = str(getattr(row, "slot_id", "") or "").strip().upper()
        b = str(getattr(row, "linked_to", "") or "").strip().upper()
        if a in _EMPTY or b in _EMPTY or a == b:
            continue
        wd = str(getattr(row, "weekday_name", "") or "").strip().upper()
        fr = str(getattr(row, "franja", "") or "").strip().upper()
        out.setdefault((wd, fr), set()).add(tuple(sorted((a, b))))
    return {k: sorted(v) for k, v in out.items()}


def _groups_from_pairs(pairs) -> list[list[str]]:
    """Tancament transitiu d'un conjunt de parelles → llista de grups."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, list[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    return sorted([sorted(g) for g in groups.values() if len(g) >= 2])


def linked_groups_in_template(templates_df, weekday_name, franja) -> list[list[str]]:
    """BLOCS de màquines vinculades en un (dia-setmana, franja) concret del
    template (una sola persona cobreix el bloc aquell dia/franja)."""
    wf = slot_link_pairs_by_weekday_franja(templates_df)
    key = (str(weekday_name).strip().upper(), str(franja).strip().upper())
    return _groups_from_pairs(wf.get(key, []))


def _template_wf_mask(df, weekday_name, franja, slot_ids):
    wd = str(weekday_name).strip().upper()
    fr = str(franja).strip().upper()
    up_wd = df["weekday_name"].fillna("").astype(str).str.strip().str.upper()
    up_fr = df["franja"].fillna("").astype(str).str.strip().str.upper()
    up_sid = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    return (up_wd == wd) & (up_fr == fr) & (up_sid.isin(set(slot_ids)))


def set_linked_group_in_template(templates_df, weekday_name, franja, members):
    """Vincula `members` (2..MAX_LINKED_GROUP) com un BLOC NOMÉS en aquest
    (dia-setmana, franja): tots apunten al primer (representant) via
    `linked_to`. Dissol qualsevol bloc previ d'aquell dia/franja que contingui
    algun membre. Retorna el template modificat (còpia)."""
    df = templates_df.copy()
    if "linked_to" not in df.columns:
        df["linked_to"] = ""
    mem: list[str] = []
    for m in members or []:
        u = str(m).strip().upper()
        if u and u not in mem:
            mem.append(u)
    mem = mem[:MAX_LINKED_GROUP]
    if len(mem) < 2:
        return df
    to_clear = set(mem)
    for g in linked_groups_in_template(df, weekday_name, franja):
        if any(x in mem for x in g):
            to_clear.update(g)
    df.loc[_template_wf_mask(df, weekday_name, franja, to_clear), "linked_to"] = ""
    df.loc[_template_wf_mask(df, weekday_name, franja, mem[1:]), "linked_to"] = mem[0]
    return df


def clear_linked_group_in_template(templates_df, weekday_name, franja, member):
    """Desvincula el BLOC que conté `member` en aquest (dia-setmana, franja).
    Retorna el template modificat (còpia)."""
    df = templates_df.copy()
    if "linked_to" not in df.columns:
        return df
    m = str(member).strip().upper()
    target = next(
        (g for g in linked_groups_in_template(df, weekday_name, franja) if m in g),
        None,
    )
    if target:
        df.loc[_template_wf_mask(df, weekday_name, franja, target), "linked_to"] = ""
    return df


# Weekly templates store the same columns as defined by services.input_tables.
# Kept local to avoid a cross-module import cycle.
_WEEKDAY_TEMPLATE_FULL_COLS = [
    "weekday_name", "franja", "slot_id", "presentiality", "work_mode",
    "required_staff", "is_active",
]
_WEEKEND_TEMPLATE_FULL_COLS = [
    "weekday_name", "franja", "slot_id", "reporting_machine",
    "presentiality", "work_mode", "required_staff", "is_active",
]


def _coerce_bool_column(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "yes", "si", "sí", "y", "x", "weekday", "weekend", "both"})


def _coerce_doubled(series: pd.Series) -> pd.Series:
    """Accept bool (legacy True→1, False→0) or int 0..2. Output int clipped to [0, 2]."""
    out_series = pd.Series(0, index=series.index, dtype=int)
    for idx, value in series.items():
        if isinstance(value, bool):
            out_series.at[idx] = 1 if value else 0
            continue
        try:
            n = int(value) if pd.notna(value) else 0
        except (TypeError, ValueError):
            text = str(value).strip().lower()
            n = 1 if text in {"1", "true", "yes", "si", "sí", "y", "x"} else 0
        out_series.at[idx] = max(0, min(2, n))
    return out_series


def load_slot_catalog(path: Path) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path)
    else:
        df = pd.DataFrame(columns=SLOT_CATALOG_COLUMNS)

    # Backwards-compat: convert old `applies_to` column (WEEKDAY/WEEKEND/BOTH).
    if "applies_to" in df.columns and "weekday" not in df.columns:
        upper = df["applies_to"].fillna("").astype(str).str.strip().str.upper()
        df["weekday"] = upper.isin({"WEEKDAY", "BOTH"})
        df["weekend"] = upper.isin({"WEEKEND", "BOTH"})
        df = df.drop(columns=["applies_to"])

    _text_cols = {"slot_id", "linked_to", "area", "metric_family", "assignee", "notes"}

    for col in SLOT_CATALOG_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in _text_cols else (0 if col == "doubled" else False)

    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df["weekday"] = _coerce_bool_column(df["weekday"])
    df["weekend"] = _coerce_bool_column(df["weekend"])
    df["linked_to"] = df["linked_to"].fillna("").astype(str).str.strip().str.upper()
    df["doubled"] = _coerce_doubled(df["doubled"])
    df["review"] = pd.to_numeric(df["review"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    # Localització i família admeten qualsevol valor (etiquetes lliures); el
    # solver només interpreta TC/RM per a l'equilibri de famílies, la resta
    # passen com a etiqueta descriptiva sense efecte funcional.
    df["area"] = df["area"].fillna("").astype(str).str.strip().str.upper()
    df["metric_family"] = df["metric_family"].fillna("").astype(str).str.strip().str.upper()
    df["assignee"] = df["assignee"].fillna("").astype(str).str.strip().str.upper()
    df["notes"] = df["notes"].fillna("").astype(str)
    df = df[df["slot_id"] != ""].drop_duplicates(subset=["slot_id"], keep="last")
    df = df[~df["slot_id"].isin(GUARDS_RESERVED_SLOT_IDS)]
    return df[SLOT_CATALOG_COLUMNS].reset_index(drop=True)


def save_slot_catalog(path: Path, df: pd.DataFrame) -> None:
    _text_cols = {"slot_id", "linked_to", "area", "metric_family", "assignee", "notes"}
    out = df.copy()
    for col in SLOT_CATALOG_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col in _text_cols else (0 if col == "doubled" else False)
    out["slot_id"] = out["slot_id"].fillna("").astype(str).str.strip().str.upper()
    out["weekday"] = _coerce_bool_column(out["weekday"]).astype(int)
    out["weekend"] = _coerce_bool_column(out["weekend"]).astype(int)
    out["linked_to"] = out["linked_to"].fillna("").astype(str).str.strip().str.upper()
    out["doubled"] = pd.to_numeric(out["doubled"], errors="coerce").fillna(0).astype(int).clip(0, 2)
    out["review"] = pd.to_numeric(out["review"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    out["area"] = out["area"].fillna("").astype(str).str.strip().str.upper()
    out["metric_family"] = out["metric_family"].fillna("").astype(str).str.strip().str.upper()
    out["assignee"] = out["assignee"].fillna("").astype(str).str.strip().str.upper()
    out["notes"] = out["notes"].fillna("").astype(str)
    out = out[out["slot_id"] != ""].drop_duplicates(subset=["slot_id"], keep="last")
    save_table(path, out, SLOT_CATALOG_COLUMNS)


def default_slot_catalog(
    weekday_templates_df: pd.DataFrame | None = None,
    weekend_templates_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a default catalog.

    Strategy: preserve current state when migrating an existing project.
      • If weekday_templates has rows → mark weekday=True only for slots already there.
      • Otherwise → mark CORE_SLOT_IDS as weekday=True (fresh install defaults).
      • Same logic for weekend (using WEEKEND_SLOT_IDS as defaults when empty).

    All known slot IDs (CORE+WEEKEND+template entries) appear in the catalog so the
    user can later toggle them on without retyping. Unmarked slots are visible but
    not implemented in any calendar.
    """
    rows: dict[str, dict] = {}

    def _ensure(slot_id: str) -> dict:
        slot_id = slot_id.strip().upper()
        if not slot_id or slot_id in GUARDS_RESERVED_SLOT_IDS:
            return {}
        if slot_id not in rows:
            rows[slot_id] = {
                "slot_id": slot_id, "weekday": False, "weekend": False,
                "linked_to": "", "doubled": 0, "review": 0,
                "area": "", "metric_family": "", "assignee": "", "notes": "",
            }
        return rows[slot_id]

    for slot_id in CORE_SLOT_IDS:
        _ensure(slot_id)
    for slot_id in WEEKEND_SLOT_IDS:
        _ensure(slot_id)

    has_weekday = weekday_templates_df is not None and not weekday_templates_df.empty and "slot_id" in weekday_templates_df.columns
    has_weekend = weekend_templates_df is not None and not weekend_templates_df.empty and "slot_id" in weekend_templates_df.columns

    if has_weekday:
        for raw in weekday_templates_df["slot_id"].dropna().astype(str).str.strip().str.upper().unique():
            entry = _ensure(raw)
            if entry:
                entry["weekday"] = True
    else:
        for slot_id in CORE_SLOT_IDS:
            if slot_id in rows:
                rows[slot_id]["weekday"] = True

    if has_weekend:
        for raw in weekend_templates_df["slot_id"].dropna().astype(str).str.strip().str.upper().unique():
            entry = _ensure(raw)
            if entry:
                entry["weekend"] = True
    else:
        for slot_id in WEEKEND_SLOT_IDS:
            if slot_id in rows:
                rows[slot_id]["weekend"] = True

    return pd.DataFrame(list(rows.values()), columns=SLOT_CATALOG_COLUMNS)


def seed_slot_catalog_if_missing(
    path: Path,
    weekday_templates_path: Path | None = None,
    weekend_templates_path: Path | None = None,
) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        return load_slot_catalog(path)

    weekday_templates = None
    if weekday_templates_path is not None:
        weekday_templates = read_table(weekday_templates_path, _WEEKDAY_TEMPLATE_FULL_COLS)
    weekend_templates = None
    if weekend_templates_path is not None:
        weekend_templates = read_table(weekend_templates_path, list(WEEKEND_TEMPLATE_COLUMNS))

    df = default_slot_catalog(weekday_templates, weekend_templates)
    save_slot_catalog(path, df)
    return df


def weekday_slot_ids(catalog_df: pd.DataFrame) -> list[str]:
    if catalog_df.empty:
        return []
    mask = catalog_df["weekday"].astype(bool)
    return sorted(set(catalog_df.loc[mask, "slot_id"].dropna().astype(str)))


def weekend_slot_ids(catalog_df: pd.DataFrame) -> list[str]:
    if catalog_df.empty:
        return []
    mask = catalog_df["weekend"].astype(bool)
    return sorted(set(catalog_df.loc[mask, "slot_id"].dropna().astype(str)))


# ─── Template sync ──────────────────────────────────────────────────────────

def sync_weekday_templates_with_catalog(
    catalog_df: pd.DataFrame,
    templates_df: pd.DataFrame,
) -> pd.DataFrame:
    """Prune-only: drop template rows whose slot_id no longer is active in the
    weekday catalog. Els slots de revisió s'EXCLOUEN de l'estat actiu: no es
    poden assignar a franges (s'apliquen al dia sencer des del catàleg)."""
    active = {str(s).strip().upper() for s in weekday_slot_ids(catalog_df)}
    review = {str(s).strip().upper() for s in review_slot_ids(catalog_df)}
    active = active - review
    df = templates_df.copy()
    if "slot_id" not in df.columns:
        df["slot_id"] = ""
    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df = df[df["slot_id"].isin(active) | (df["slot_id"] == "")].copy()
    return df.reset_index(drop=True)


def fill_weekday_templates_with_defaults(
    catalog_df: pd.DataFrame,
    templates_df: pd.DataFrame,
) -> pd.DataFrame:
    """Add a default Monday-MATI row per active catalog slot not yet present."""
    active = set(weekday_slot_ids(catalog_df))
    df = templates_df.copy()
    if "slot_id" not in df.columns:
        df["slot_id"] = ""
    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    existing = set(df["slot_id"]) - {""}
    missing = sorted(active - existing)
    new_rows = [
        {
            "weekday_name": "MONDAY",
            "franja": "MATI",
            "slot_id": slot_id,
            "presentiality": "PRESENCIAL",
            "work_mode": "NORMAL",
            "required_staff": 1,
            "is_active": 1,
        }
        for slot_id in missing
    ]
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    return df.reset_index(drop=True)


def persist_slot_catalog_with_templates(
    draft_df: pd.DataFrame,
    catalog_path: Path,
    weekday_templates_path: Path | None,
    weekend_templates_path: Path | None,
) -> None:
    """Save the slot catalog draft and synchronise weekday/weekend templates
    so newly-added slots get a default row and removed slots are dropped."""
    save_slot_catalog(catalog_path, draft_df)
    catalog_df = load_slot_catalog(catalog_path)

    if weekday_templates_path is not None:
        weekday_templates_df = read_table(weekday_templates_path, _WEEKDAY_TEMPLATE_FULL_COLS)
        weekday_templates_df = sync_weekday_templates_with_catalog(
            catalog_df, weekday_templates_df
        )
        save_table(weekday_templates_path, weekday_templates_df, _WEEKDAY_TEMPLATE_FULL_COLS)

    if weekend_templates_path is not None:
        weekend_templates_df = read_table(weekend_templates_path, _WEEKEND_TEMPLATE_FULL_COLS)
        weekend_templates_df = sync_weekend_templates_with_catalog(
            catalog_df, weekend_templates_df
        )
        save_table(weekend_templates_path, weekend_templates_df, _WEEKEND_TEMPLATE_FULL_COLS)


def sync_weekend_templates_with_catalog(
    catalog_df: pd.DataFrame,
    templates_df: pd.DataFrame,
) -> pd.DataFrame:
    """Prune-only equivalent for the weekend templates."""
    active = set(weekend_slot_ids(catalog_df))
    df = templates_df.copy()
    if "slot_id" not in df.columns:
        df["slot_id"] = ""
    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df = df[df["slot_id"].isin(active) | (df["slot_id"] == "")].copy()
    return df.reset_index(drop=True)


def fill_weekend_templates_with_defaults(
    catalog_df: pd.DataFrame,
    templates_df: pd.DataFrame,
) -> pd.DataFrame:
    """Add a default Saturday-12H row per active weekend catalog slot."""
    active = set(weekend_slot_ids(catalog_df))
    df = templates_df.copy()
    if "slot_id" not in df.columns:
        df["slot_id"] = ""
    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    existing = set(df["slot_id"]) - {""}
    missing = sorted(active - existing)
    new_rows = [
        {
            "weekday_name": "SATURDAY",
            "franja": "12H",
            "slot_id": slot_id,
            "reporting_machine": slot_id,
            "presentiality": "NO_PRESENCIAL",
            "work_mode": "NORMAL",
            "required_staff": 1,
            "is_active": 1,
        }
        for slot_id in missing
    ]
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    return df.reset_index(drop=True)
