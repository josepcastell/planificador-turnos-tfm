from datetime import date
from pathlib import Path

import pandas as pd

from src.domain.constants import (
    CORE_SLOT_IDS,
    FRANJA_ORDER,
    PRESENTIALITY_ORDER,
    WEEKDAY_NAMES_BY_INDEX,
    WORK_MODE_ORDER,
)
from src.services.table_io import read_table, save_table


def work_slots_for_weekday_and_franja(templates_df: pd.DataFrame, weekday_name: str, franja: str) -> pd.DataFrame:
    if templates_df.empty:
        return pd.DataFrame(columns=["weekday_name", "franja", "slot_id", "presentiality", "work_mode", "required_staff", "is_active"])
    df = templates_df.copy()
    for col in ["weekday_name", "franja", "slot_id", "presentiality", "work_mode"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
    if "is_active" not in df.columns:
        df["is_active"] = 1
    if "required_staff" not in df.columns:
        df["required_staff"] = 1
    df["is_active"] = pd.to_numeric(df["is_active"], errors="coerce").fillna(1).astype(int)
    df["required_staff"] = pd.to_numeric(df["required_staff"], errors="coerce").fillna(1).astype(int).clip(lower=1, upper=6)
    out = df[
        (df["weekday_name"] == weekday_name)
        & (df["franja"] == franja)
        & (df["is_active"] == 1)
    ].copy()
    out["slot_order"] = out["slot_id"].map(
        {slot_id: idx for idx, slot_id in enumerate(CORE_SLOT_IDS)}
    ).fillna(len(CORE_SLOT_IDS)).astype(int)
    out["presentiality_order"] = out["presentiality"].map(PRESENTIALITY_ORDER).fillna(99).astype(int)
    out["work_mode_order"] = out["work_mode"].map(WORK_MODE_ORDER).fillna(99).astype(int)
    return out.sort_values(
        ["slot_order", "slot_id", "presentiality_order", "work_mode_order"]
    ).drop(columns=["slot_order", "presentiality_order", "work_mode_order"])


def ensure_all_active_weekday_template_rows(
    active_slot_ids: list[str],
    templates_path: Path,
) -> int:
    """Per cada slot a active_slot_ids sense files al template, hi afegeix
    files per defecte (MON-FRI MATI). Retorna quants slots s'han sembrat."""
    seeded = 0
    for slot_id in active_slot_ids:
        if ensure_default_weekday_template_rows(slot_id, templates_path):
            seeded += 1
    return seeded


def ensure_default_weekday_template_rows(
    slot_id: str,
    templates_path: Path,
    franja: str = "MATI",
    presentiality: str = "PRESENCIAL",
    work_mode: str = "NORMAL",
) -> bool:
    """Si el slot encara no té cap fila al template, n'afegeix una per cada
    dia laborable (MON-FRI) a la franja indicada. Retorna True si s'ha
    modificat el fitxer."""
    from src.services.input_tables import save_weekly_slot_templates

    slot_norm = str(slot_id).strip().upper()
    if not slot_norm:
        return False
    cols = [
        "weekday_name", "franja", "slot_id",
        "presentiality", "work_mode", "required_staff", "is_active", "doubled",
    ]
    df = read_table(templates_path, cols)
    existing = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    if (existing == slot_norm).any():
        return False
    new_rows = pd.DataFrame([
        {
            "weekday_name": d,
            "franja": franja,
            "slot_id": slot_norm,
            "presentiality": presentiality,
            "work_mode": work_mode,
            "required_staff": 1,
            "is_active": 1,
            "doubled": 0,
        }
        for d in WEEKDAY_NAMES_BY_INDEX[:5]
    ])
    df = pd.concat([df, new_rows], ignore_index=True)
    save_weekly_slot_templates(df, templates_path)
    return True


def add_work_slot_template(
    templates_df: pd.DataFrame,
    weekday_name: str,
    franja: str,
    slot_id: str,
    presentiality: str,
    work_mode: str,
    required_staff: int = 1,
    doubled: int = 0,
) -> pd.DataFrame:
    """Afegeix una fila al template. Si ja existeix una fila idèntica a
    la clau (weekday, franja, slot, presencialitat, work_mode),
    **incrementa el seu `required_staff`** enlloc d'afegir una fila
    duplicada. Així es poden tenir N instàncies idèntiques (p.ex. 2
    PRES per a la mateixa màquina/franja, que el solver assignarà a 2
    facultatius diferents)."""
    df = templates_df.copy()
    if "required_staff" not in df.columns:
        df["required_staff"] = 1
    if "is_active" not in df.columns:
        df["is_active"] = 1
    if "doubled" not in df.columns:
        df["doubled"] = 0
    mask = (
        (df["weekday_name"].astype(str) == str(weekday_name))
        & (df["franja"].astype(str) == str(franja))
        & (df["slot_id"].astype(str) == str(slot_id))
        & (df["presentiality"].astype(str) == str(presentiality))
        & (df["work_mode"].astype(str) == str(work_mode))
    )
    if mask.any():
        current = pd.to_numeric(
            df.loc[mask, "required_staff"], errors="coerce"
        ).fillna(1).astype(int)
        df.loc[mask, "required_staff"] = current + max(1, int(required_staff))
        df.loc[mask, "is_active"] = 1
        return df.reset_index(drop=True)
    new_row = {
        "weekday_name": weekday_name,
        "franja": franja,
        "slot_id": slot_id,
        "presentiality": presentiality,
        "work_mode": work_mode,
        "required_staff": max(1, int(required_staff)),
        "is_active": 1,
        "doubled": int(bool(doubled)),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    return df.reset_index(drop=True)


def remove_work_slot_template(
    templates_df: pd.DataFrame,
    weekday_name: str,
    franja: str,
    slot_id: str,
    presentiality: str,
    work_mode: str,
) -> pd.DataFrame:
    """Si el `required_staff` és >1, decrementa'l. Si val 1 (o no hi és),
    elimina la fila."""
    df = templates_df.copy()
    if "required_staff" not in df.columns:
        df["required_staff"] = 1
    for col in ["weekday_name", "franja", "slot_id", "presentiality", "work_mode"]:
        df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
    mask = (
        (df["weekday_name"] == weekday_name)
        & (df["franja"] == franja)
        & (df["slot_id"] == slot_id)
        & (df["presentiality"] == presentiality)
        & (df["work_mode"] == work_mode)
    )
    if not mask.any():
        return df.reset_index(drop=True)
    current = pd.to_numeric(
        df.loc[mask, "required_staff"], errors="coerce"
    ).fillna(1).astype(int)
    if (current > 1).any():
        # Decrement (mantenint mínim 1; si arriba a 0 → eliminem)
        new_vals = (current - 1).clip(lower=0)
        df.loc[mask, "required_staff"] = new_vals
        # Files amb required_staff=0 → eliminem
        zero_mask = mask & (
            pd.to_numeric(df["required_staff"], errors="coerce").fillna(1).astype(int) == 0
        )
        df = df.loc[~zero_mask]
        return df.reset_index(drop=True)
    # required_staff=1 a totes → eliminar la fila sencera
    return df.loc[~mask].reset_index(drop=True)


def load_template_overrides(path: Path) -> pd.DataFrame:
    columns = ["day", "franja", "slot_id", "presentiality", "work_mode", "action", "required_staff", "notes"]
    df = read_table(path, columns)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns].copy()


def save_template_overrides(path: Path, df: pd.DataFrame) -> None:
    out = df.copy()
    for col in ["franja", "slot_id", "presentiality", "work_mode", "action"]:
        out[col] = out[col].fillna("").astype(str).str.strip().str.upper()
    out["action"] = out["action"].str.lower()
    out["notes"] = out["notes"].fillna("").astype(str)
    if "required_staff" not in out.columns:
        out["required_staff"] = 1
    out["required_staff"] = pd.to_numeric(out["required_staff"], errors="coerce").fillna(1).astype(int).clip(lower=1)
    out["day"] = pd.to_datetime(out["day"], errors="coerce")
    out = out.dropna(subset=["day"]).copy()
    out["day"] = out["day"].dt.strftime("%Y-%m-%d")
    out = out[
        out["franja"].isin(["MATI", "TARDA", "NIT"])
        & (out["slot_id"] != "")
        & out["presentiality"].isin(["PRESENCIAL", "NO_PRESENCIAL"])
        & out["work_mode"].isin(["NORMAL", "PEONADA"])
        & out["action"].isin(["add", "remove"])
    ].copy()
    out = out.drop_duplicates(
        subset=["day", "franja", "slot_id", "presentiality", "work_mode", "action"],
        keep="last",
    ).sort_values(["day", "franja", "slot_id", "action"])
    save_table(path, out, ["day", "franja", "slot_id", "presentiality", "work_mode", "action", "required_staff", "notes"])


def add_template_override(
    overrides_df: pd.DataFrame,
    day_key: str,
    franja: str,
    slot_id: str,
    presentiality: str,
    work_mode: str,
    action: str,
    required_staff: int = 1,
) -> pd.DataFrame:
    df = overrides_df.copy()
    opposite = "remove" if action == "add" else "add"
    for col in ["day", "franja", "slot_id", "presentiality", "work_mode", "action"]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    same_slot = (
        (df["day"] == day_key)
        & (df["franja"].str.upper() == franja)
        & (df["slot_id"].str.upper() == slot_id)
        & (df["presentiality"].str.upper() == presentiality)
        & (df["work_mode"].str.upper() == work_mode)
    )
    df = df.loc[~(same_slot & (df["action"].str.lower() == opposite))].copy()
    new_row = pd.DataFrame([{
        "day": day_key,
        "franja": franja,
        "slot_id": slot_id,
        "presentiality": presentiality,
        "work_mode": work_mode,
        "action": action,
        "required_staff": int(required_staff),
        "notes": "",
    }])
    return pd.concat([df, new_row], ignore_index=True)


def slots_for_day_with_overrides(templates_df: pd.DataFrame, overrides_df: pd.DataFrame, current_day: date) -> pd.DataFrame:
    weekday_name = WEEKDAY_NAMES_BY_INDEX[current_day.weekday()]
    rows = work_slots_for_weekday_and_franja(templates_df, weekday_name, "MATI")
    rows = pd.concat(
        [
            rows,
            work_slots_for_weekday_and_franja(templates_df, weekday_name, "TARDA"),
            work_slots_for_weekday_and_franja(templates_df, weekday_name, "NIT"),
        ],
        ignore_index=True,
    )
    if not rows.empty:
        if "doubled" not in rows.columns:
            rows["doubled"] = 0
        rows = rows[["franja", "slot_id", "presentiality", "work_mode", "required_staff", "is_active", "doubled"]].copy()
    else:
        rows = pd.DataFrame(columns=["franja", "slot_id", "presentiality", "work_mode", "required_staff", "is_active", "doubled"])

    day_key = current_day.strftime("%Y-%m-%d")
    overrides = overrides_df.copy()
    if not overrides.empty:
        overrides["day"] = pd.to_datetime(overrides["day"], errors="coerce").dt.strftime("%Y-%m-%d")
        overrides = overrides[overrides["day"] == day_key].copy()
        for ov in overrides.itertuples(index=False):
            mask = (
                (rows["franja"].astype(str).str.upper() == str(ov.franja).upper())
                & (rows["slot_id"].astype(str).str.upper() == str(ov.slot_id).upper())
                & (rows["presentiality"].astype(str).str.upper() == str(ov.presentiality).upper())
                & (rows["work_mode"].astype(str).str.upper() == str(ov.work_mode).upper())
            )
            if str(ov.action).lower() == "remove":
                rows = rows.loc[~mask].copy()
            elif str(ov.action).lower() == "add" and not mask.any():
                rows = pd.concat([
                    rows,
                    pd.DataFrame([{
                        "franja": str(ov.franja).upper(),
                        "slot_id": str(ov.slot_id).upper(),
                        "presentiality": str(ov.presentiality).upper(),
                        "work_mode": str(ov.work_mode).upper(),
                        "required_staff": int(getattr(ov, "required_staff", 1) or 1),
                        "is_active": 1,
                        "doubled": 0,
                    }]),
                ], ignore_index=True)

    rows["franja_order"] = rows["franja"].map(FRANJA_ORDER).fillna(99).astype(int)
    rows["slot_order"] = rows["slot_id"].map(
        {slot_id: idx for idx, slot_id in enumerate(CORE_SLOT_IDS)}
    ).fillna(len(CORE_SLOT_IDS)).astype(int)
    rows["presentiality_order"] = rows["presentiality"].map(PRESENTIALITY_ORDER).fillna(99).astype(int)
    rows["work_mode_order"] = rows["work_mode"].map(WORK_MODE_ORDER).fillna(99).astype(int)
    return rows.sort_values(
        ["franja_order", "slot_order", "slot_id", "presentiality_order", "work_mode_order"]
    ).drop(
        columns=["franja_order", "slot_order", "presentiality_order", "work_mode_order"]
    ).reset_index(drop=True)


def known_slot_ids(*dfs: pd.DataFrame) -> list[str]:
    slots = set(CORE_SLOT_IDS)
    for df in dfs:
        if df is not None and not df.empty and "slot_id" in df.columns:
            values = df["slot_id"].dropna().astype(str).str.strip()
            slots.update(value for value in values if value)
    slot_order = {slot_id: idx for idx, slot_id in enumerate(CORE_SLOT_IDS)}
    return sorted(slots, key=lambda slot_id: (slot_order.get(slot_id, len(CORE_SLOT_IDS)), slot_id))


