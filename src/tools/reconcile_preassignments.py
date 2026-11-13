from pathlib import Path
import sys
import pandas as pd


def reconcile_preassignments(
    preassignments_csv: str,
    unavailability_csv: str,
    output_csv: str,
) -> None:
    pre = pd.read_csv(preassignments_csv)
    unav = pd.read_csv(unavailability_csv)

    required_pre = {"professional_id", "day", "slot_id", "fixed"}
    required_unav = {"professional_id", "day"}

    missing_pre = required_pre - set(pre.columns)
    missing_unav = required_unav - set(unav.columns)

    if missing_pre:
        raise ValueError(f"Falten columnes a preassignments: {missing_pre}")
    if missing_unav:
        raise ValueError(f"Falten columnes a unavailability: {missing_unav}")

    pre["professional_id"] = pre["professional_id"].astype(str)
    pre["day"] = pre["day"].astype(str)

    unav["professional_id"] = unav["professional_id"].astype(str)
    unav["day"] = unav["day"].astype(str)
    for col in ("franja", "presentiality"):
        if col not in unav.columns:
            unav[col] = ""
        unav[col] = unav[col].fillna("").astype(str).str.strip().str.upper()
        if col not in pre.columns:
            pre[col] = ""

    pre_franja = pre["franja"].fillna("").astype(str).str.strip().str.upper()
    pre_presentiality = pre["presentiality"].fillna("").astype(str).str.strip().str.upper()

    def _matches(unav_row, p_franja: str, p_presentiality: str) -> bool:
        # Unavailability row blocks a preassignment iff each set filter matches
        # (empty filter on the unavailability side = wildcard).
        if unav_row["franja"] and unav_row["franja"] != p_franja:
            return False
        if unav_row["presentiality"] and unav_row["presentiality"] != p_presentiality:
            return False
        return True

    # Index unavailability by (pid, day) for fast lookup.
    unav_by_pid_day: dict = {}
    for _, row in unav.iterrows():
        unav_by_pid_day.setdefault((row["professional_id"], row["day"]), []).append(row)

    pre["blocked"] = [
        any(_matches(u, f, p) for u in unav_by_pid_day.get((pid, day), []))
        for pid, day, f, p in zip(pre["professional_id"], pre["day"], pre_franja, pre_presentiality)
    ]

    removed = pre.loc[pre["blocked"]].copy()
    keep_columns = [
        col for col in [
            "professional_id", "day", "franja", "slot_id",
            "presentiality", "work_mode", "fixed", "source"
        ]
        if col in pre.columns
    ]
    kept = pre.loc[~pre["blocked"], keep_columns].copy()

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    kept.to_csv(output_csv, index=False)

    print(f"Preassignacions depurades guardades a: {output_csv}")
    print(f"Files conservades: {len(kept)}")
    print(f"Files eliminades per conflicte amb indisponibilitat: {len(removed)}")

    if not removed.empty:
        print("\nPreassignacions eliminades:")
        print(removed[["professional_id", "day", "slot_id", "fixed"]].to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Uso: python -m src.tools.reconcile_preassignments "
            "<preassignments_csv> <unavailability_csv> <output_csv>"
        )
        sys.exit(1)

    reconcile_preassignments(
        preassignments_csv=sys.argv[1],
        unavailability_csv=sys.argv[2],
        output_csv=sys.argv[3],
    )
