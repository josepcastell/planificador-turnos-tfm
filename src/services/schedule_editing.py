from pathlib import Path

import pandas as pd

from src.services.input_tables import (
    save_absences,
    save_guards,
    save_manual_assignments,
)
from src.services.metrics_summary import load_schedule_for_display
from src.services.table_io import read_table


def save_planning_editor_changes(
    original_df: pd.DataFrame,
    edited_df: pd.DataFrame,
    manual_assignments_path: Path,
    year: int,
    month: int,
    months: list[int] | None = None,
) -> tuple[int, pd.DataFrame]:
    key_cols = ["day", "franja", "slot_id", "presentiality", "work_mode"]
    original = original_df[key_cols + ["professional"]].copy()
    edited = edited_df[key_cols + ["professional"]].copy()

    for df in [original, edited]:
        df["day"] = pd.to_datetime(df["day"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["franja"] = df["franja"].fillna("").astype(str).str.strip().str.upper()
        df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip()
        df["presentiality"] = df["presentiality"].fillna("").astype(str).str.strip().str.upper()
        df["work_mode"] = df["work_mode"].fillna("").astype(str).str.strip().str.upper()
        df["professional"] = df["professional"].fillna("").astype(str).str.strip().str.upper()

    # Discriminador d'ocurrència: amb required_staff ≥ 2 hi ha 2+ files amb
    # la MATEIXA clau (day, franja, slot, pres, work_mode) i persones
    # diferents; sense l'_occ el merge seria cartesià (files duplicades i
    # canvis espuris que esborren un facultatiu).
    for df in [original, edited]:
        df["_occ"] = df.groupby(key_cols).cumcount()
    merged = original.merge(
        edited,
        on=key_cols + ["_occ"],
        how="inner",
        suffixes=("_old", "_new"),
    )
    changed = merged[
        (merged["professional_new"] != "")
        & (merged["professional_new"] != "NONE")
        & (merged["professional_new"] != merged["professional_old"])
    ].copy()

    months = months or [month]
    month_prefixes = tuple(f"{year}-{month_num:02d}" for month_num in months)
    existing = read_table(
        manual_assignments_path,
        ["professional_id", "day", "franja", "slot_id", "presentiality", "work_mode", "fixed", "source"],
    )
    existing["day"] = existing["day"].astype(str)
    existing["source"] = existing["source"].fillna("").astype(str)
    keep_existing = existing[
        ~(
            existing["day"].str.startswith(month_prefixes)
            & (existing["source"] == "planning_editor")
        )
    ].copy()

    new_rows = pd.DataFrame({
        "professional_id": changed["professional_new"],
        "day": changed["day"],
        "franja": changed["franja"],
        "slot_id": changed["slot_id"],
        "presentiality": changed["presentiality"],
        "work_mode": changed["work_mode"],
        "fixed": 1,
        "source": "planning_editor",
    })

    combined = pd.concat([keep_existing, new_rows], ignore_index=True)
    save_manual_assignments(combined, manual_assignments_path, set(combined["professional_id"].dropna().astype(str)))
    return len(new_rows), changed


def schedule_readjustment_report(
    before_path: Path,
    after_path: Path,
    key_cols: list[str],
    fixed_changes: pd.DataFrame,
) -> pd.DataFrame:
    if not before_path.exists() or not after_path.exists():
        return pd.DataFrame()
    before = load_schedule_for_display(str(before_path))
    after = load_schedule_for_display(str(after_path))
    if before is None or after is None or before.empty or after.empty:
        return pd.DataFrame()

    required = key_cols + ["professional"]
    for df in [before, after]:
        for col in required:
            if col not in df.columns:
                df[col] = ""
        df["day"] = pd.to_datetime(df["day"], errors="coerce").dt.strftime("%Y-%m-%d")
        for col in key_cols:
            df[col] = df[col].fillna("").astype(str).str.strip().str.upper()
        df["professional"] = df["professional"].fillna("NONE").astype(str).str.strip().str.upper()

    merged = before[required].merge(
        after[required],
        on=key_cols,
        how="inner",
        suffixes=("_abans", "_despres"),
    )
    changed = merged[
        merged["professional_abans"].astype(str) != merged["professional_despres"].astype(str)
    ].copy()
    if changed.empty:
        return pd.DataFrame()

    fixed_lookup = {}
    if fixed_changes is not None and not fixed_changes.empty:
        fixed = fixed_changes.copy()
        for col in key_cols:
            if col not in fixed.columns:
                fixed[col] = ""
            fixed[col] = fixed[col].fillna("").astype(str).str.strip().str.upper()
        fixed["professional_new"] = fixed["professional_new"].fillna("").astype(str).str.strip().str.upper()
        fixed_lookup = {
            tuple(str(row[col]) for col in key_cols): str(row.professional_new)
            for row in fixed.itertuples(index=False)
        }

    rows = []
    for row in changed.itertuples(index=False):
        key = tuple(str(getattr(row, col)) for col in key_cols)
        requested = fixed_lookup.get(key)
        professional_after = str(row.professional_despres)
        if requested and professional_after == requested:
            reason = "Canvi fixat manualment per l'usuari."
        elif requested:
            reason = "El solver ha reajustat la solució al voltant d'un canvi manual fixat."
        else:
            reason = "Reajust automàtic del solver per mantenir restriccions i minimitzar canvis globals."
        rows.append({
            "dia": row.day,
            "franja": row.franja,
            "slot": row.slot_id,
            "maquina_real": getattr(row, "reporting_machine", ""),
            "abans": row.professional_abans,
            "despres": row.professional_despres,
            "motiu": reason,
        })

    report = pd.DataFrame(rows)
    visible_cols = ["dia", "franja", "slot", "abans", "despres", "motiu"]
    if "maquina_real" in report.columns and report["maquina_real"].fillna("").astype(str).str.strip().any():
        visible_cols.insert(3, "maquina_real")
    return report[visible_cols].sort_values(["dia", "franja", "slot"]).reset_index(drop=True)


def write_edited_schedule(schedule_df: pd.DataFrame, path: Path, columns: list[str]) -> None:
    out = schedule_df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    out = out[columns].copy()
    if "day" in out.columns:
        out["day"] = pd.to_datetime(out["day"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in [c for c in columns if c != "day"]:
        out[col] = out[col].fillna("").astype(str).str.strip()

    if path.exists() and path.stat().st_size > 0:
        original = pd.read_csv(path)
        key_cols = [col for col in columns if col != "professional" and col in original.columns]
        if key_cols and "professional" in original.columns and "professional" in out.columns:
            for df in [original, out]:
                if "day" in df.columns:
                    df["day"] = pd.to_datetime(df["day"], errors="coerce").dt.strftime("%Y-%m-%d")
                for col in key_cols + ["professional"]:
                    df[col] = df[col].fillna("").astype(str).str.strip()
            original_cols = original.columns.tolist()
            # _occ: mateixa clau repetida (required_staff ≥ 2) → el merge
            # aparella la n-èsima ocurrència amb la n-èsima, mai cartesià.
            original["_occ"] = original.groupby(key_cols).cumcount()
            out["_occ"] = out.groupby(key_cols).cumcount()
            original = original.drop(columns=["professional"]).merge(
                out[key_cols + ["_occ", "professional"]],
                on=key_cols + ["_occ"],
                how="left",
            )
            original["professional"] = original["professional"].fillna("NONE").replace("", "NONE")
            out = original[original_cols].copy()

    sort_cols = [col for col in ["day", "franja", "slot_id", "reporting_machine", "professional"] if col in out.columns]
    out = out.sort_values(sort_cols).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)


