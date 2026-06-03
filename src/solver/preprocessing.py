"""Input validation, scaling, and DataFrame preparation for the CP-SAT model."""

import pandas as pd

from src.core.utils import normalize_slot
from src.domain.constants import COMITE_TYPES, WEEKDAY_CODES
from src.solver.normalize import (
    normalize_presentiality,
    normalize_work_mode,
)


def expand_comite_to_days(
    comite_df: pd.DataFrame,
    unique_days: list[str],
) -> list[tuple[str, str, str]]:
    """Returns list of (professional_id, day_str, comite_type)."""
    if comite_df is None or comite_df.empty:
        return []

    weekday_to_index = {code: idx for idx, code in enumerate(WEEKDAY_CODES)}
    unique_days_set = set(unique_days)
    days_by_weekday: dict[int, list[str]] = {}
    for day_str in unique_days:
        try:
            wd = pd.Timestamp(day_str).weekday()
        except (TypeError, ValueError):
            continue
        days_by_weekday.setdefault(wd, []).append(day_str)

    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for row in comite_df.itertuples(index=False):
        comite_type = str(getattr(row, "comite_type", "") or "").strip().upper()
        if comite_type not in COMITE_TYPES:
            continue
        professional_id = str(getattr(row, "professional_id", "") or "").strip().upper()
        if not professional_id:
            continue
        specific_day = getattr(row, "specific_day", None)
        weekday_code = str(getattr(row, "weekday", "") or "").strip().upper()

        if pd.notna(specific_day) and specific_day != "":
            try:
                day_str = pd.Timestamp(specific_day).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                continue
            if day_str in unique_days_set:
                key = (professional_id, day_str, comite_type)
                if key not in seen:
                    out.append(key)
                    seen.add(key)
            continue

        if weekday_code in weekday_to_index:
            target_idx = weekday_to_index[weekday_code]
            for day_str in days_by_weekday.get(target_idx, ()):
                key = (professional_id, day_str, comite_type)
                if key not in seen:
                    out.append(key)
                    seen.add(key)

    return out


def _matching_preassignment_keys(row, slot_keys) -> list[tuple]:
    day = str(row.day)
    slot_id = normalize_slot(str(row.slot_id))
    franja = str(getattr(row, "franja", "") or "").upper()
    presentiality = str(getattr(row, "presentiality", "") or "").upper()
    work_mode = str(getattr(row, "work_mode", "") or "").upper()

    matches = [
        sk for sk in slot_keys
        if sk[0] == day and sk[2] == slot_id
    ]
    if franja:
        matches = [sk for sk in matches if sk[1] == franja]
    if presentiality:
        matches = [sk for sk in matches if sk[3] == normalize_presentiality(presentiality)]
    if work_mode:
        matches = [sk for sk in matches if sk[4] == normalize_work_mode(work_mode)]
    return matches


def _norm_unavailability_value(value) -> str:
    """NaN/None/''/'NAN'/'NONE' → '' (camp buit, sense filtre). Igual que
    el `_norm` intern de `_add_unavailability_constraints`."""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    s = str(value).strip().upper()
    return "" if s in ("", "NAN", "NONE") else s


# Indisponibilitats autogenerades pel propi pipeline (no per absències de
# l'usuari): conviuen amb slots preassignats coherents (p.ex. la guàrdia
# preassigna GD i alhora bloqueja la TARDA d'aquell dia). No s'han de fer
# servir per validar xocs amb preassignacions — donarien falsos positius.
_AUTOGEN_UNAVAILABILITY_REASONS = {"guardia_day_tarda", "post_guard_free"}


def _build_unavailability_index(unavailability_df):
    """Index {(prof, day): [(franja, presentiality, slot_id), …]} per
    comprovar ràpidament si un slot està bloquejat. Camps buits = comodí
    (bloqueja tot el dia / tota la franja / tota la presencialitat).
    Exclou les indisponibilitats autogenerades (vegeu la constant)."""
    index: dict = {}
    if unavailability_df is None or unavailability_df.empty:
        return index
    has_franja = "franja" in unavailability_df.columns
    has_pres = "presentiality" in unavailability_df.columns
    has_slot = "slot_id" in unavailability_df.columns
    has_reason = "reason" in unavailability_df.columns
    for row in unavailability_df.itertuples(index=False):
        if has_reason:
            reason = str(getattr(row, "reason", "") or "").strip().lower()
            if reason in _AUTOGEN_UNAVAILABILITY_REASONS:
                continue
        pid = str(getattr(row, "professional_id", "") or "").strip()
        day = str(getattr(row, "day", "") or "").strip()
        if not pid or not day:
            continue
        franja = _norm_unavailability_value(getattr(row, "franja", "")) if has_franja else ""
        pres = _norm_unavailability_value(getattr(row, "presentiality", "")) if has_pres else ""
        slot = _norm_unavailability_value(getattr(row, "slot_id", "")) if has_slot else ""
        index.setdefault((pid.upper(), day), []).append((franja, pres, slot))
    return index


def _day_fully_blocked(pid: str, day: str, unav_index) -> bool:
    """True si el facultatiu té una indisponibilitat de DIA SENCER (vacances,
    baixa…) aquell dia — cap franja/slot/presencialitat especificada. Es fa
    servir per relaxar la continuïtat de revisió (H7) quan cap facultatiu pot
    cobrir els dos dies enllaçats."""
    rules = unav_index.get((str(pid).strip().upper(), str(day).strip()))
    if not rules:
        return False
    return any((not f and not p and not s) for f, p, s in rules)


def _preassignment_blocked(row, unav_index) -> bool:
    """True si la preassignació (prof, day, franja, slot, presentiality) cau
    sobre una indisponibilitat que la bloquejaria (mateixa lògica que
    `_add_unavailability_constraints`)."""
    pid = str(getattr(row, "professional_id", "") or "").strip().upper()
    day = str(getattr(row, "day", "") or "").strip()
    rules = unav_index.get((pid, day))
    if not rules:
        return False
    pa_franja = _norm_unavailability_value(getattr(row, "franja", ""))
    pa_pres = _norm_unavailability_value(getattr(row, "presentiality", ""))
    pa_slot = _norm_unavailability_value(getattr(row, "slot_id", ""))
    for u_franja, u_pres, u_slot in rules:
        if u_slot and u_slot == pa_slot:
            return True
        # franja/presentiality buides al rule = comodí (bloqueja tot)
        franja_block = (not u_franja) or (u_franja == pa_franja)
        pres_block = (not u_pres) or (u_pres == pa_pres)
        if not u_slot and franja_block and pres_block:
            return True
    return False


def _validate_preassignments(preassignments_df, professionals, slot_keys,
                             unavailability_df=None) -> None:
    if preassignments_df.empty:
        return

    required_columns = {"professional_id", "day", "slot_id", "fixed"}
    missing_columns = required_columns - set(preassignments_df.columns)
    if missing_columns:
        missing_txt = ", ".join(sorted(missing_columns))
        raise ValueError(f"Preassignments missing required columns: {missing_txt}")

    professional_set = set(professionals)
    unav_index = _build_unavailability_index(unavailability_df)
    errors = []

    for row in preassignments_df.itertuples(index=False):
        if int(row.fixed) != 1:
            continue

        professional_id = str(row.professional_id)
        slot_id = str(row.slot_id)

        if professional_id not in professional_set:
            errors.append(
                f"{row.day} {slot_id}: professional '{professional_id}' does not exist"
            )

        if not _matching_preassignment_keys(row, slot_keys):
            errors.append(
                f"{row.day} {slot_id}: slot does not exist in calendar_slots"
            )

        # H6 vs H3: una preassignació fixa sobre un dia/franja indisponible
        # del facultatiu fa el model infactible sense missatge clar. Detecta-ho
        # aquí amb un error explícit.
        if _preassignment_blocked(row, unav_index):
            errors.append(
                f"{row.day} {slot_id}: '{professional_id}' té una "
                f"indisponibilitat que xoca amb aquesta preassignació fixa"
            )

    if errors:
        preview = "; ".join(errors[:10])
        remaining = len(errors) - 10
        if remaining > 0:
            preview += f"; ... and {remaining} more"
        raise ValueError(f"Invalid fixed preassignments: {preview}")


def _add_missing_slots_from_preassignments(slots_df: pd.DataFrame, preassignments_df: pd.DataFrame) -> pd.DataFrame:
    if preassignments_df.empty:
        return slots_df

    required_columns = {"day", "slot_id", "fixed"}
    if not required_columns.issubset(preassignments_df.columns):
        return slots_df

    out = slots_df.copy()
    # Local import to avoid circular dependency: normalize._make_slot_key needs nothing from here.
    from src.solver.normalize import _make_slot_key
    slot_keys = {_make_slot_key(row) for row in out.itertuples(index=False)}
    new_rows = []

    for row in preassignments_df.itertuples(index=False):
        if int(getattr(row, "fixed", 0)) != 1:
            continue

        day = str(getattr(row, "day", "")).strip()
        slot_id = normalize_slot(str(getattr(row, "slot_id", "")).strip())
        if not day or not slot_id:
            continue

        franja = str(getattr(row, "franja", "") or "").strip().upper() or "MATI"
        presentiality = normalize_presentiality(getattr(row, "presentiality", "PRESENCIAL"))
        work_mode = normalize_work_mode(getattr(row, "work_mode", "NORMAL"))
        slot_key = (day, franja, slot_id, presentiality, work_mode)
        if any(sk[:5] == slot_key for sk in slot_keys):
            continue

        new_row = {
            "day": day,
            "franja": franja,
            "slot_id": slot_id,
            "presentiality": presentiality,
            "work_mode": work_mode,
            "position": max([sk[5] for sk in slot_keys if sk[:5] == slot_key[:5]], default=0) + 1,
        }
        if "reporting_machine" in out.columns:
            new_row["reporting_machine"] = str(getattr(row, "reporting_machine", "") or "").strip().upper()
        for col in out.columns:
            if col not in new_row:
                new_row[col] = ""
        new_rows.append(new_row)
        slot_keys.add((day, franja, slot_id, presentiality, work_mode, int(new_row["position"])))

    if not new_rows:
        return out
    return pd.concat([out, pd.DataFrame(new_rows)], ignore_index=True)


def _stability_by_slot(stability_assignments, professionals, slot_keys) -> dict:
    if stability_assignments is None or stability_assignments.empty:
        return {}

    required = {"day", "slot_id", "professional"}
    if not required.issubset(stability_assignments.columns):
        return {}

    df = stability_assignments.copy()
    df["day"] = df["day"].astype(str)
    df["slot_id"] = df["slot_id"].apply(normalize_slot)
    df["professional"] = df["professional"].astype(str)
    if "franja" in df.columns:
        df["franja"] = df["franja"].fillna("").astype(str).str.upper()
    if "presentiality" in df.columns:
        df["presentiality"] = df["presentiality"].apply(normalize_presentiality)
    if "work_mode" in df.columns:
        df["work_mode"] = df["work_mode"].apply(normalize_work_mode)

    professional_set = set(professionals)
    out = {}

    for sk in slot_keys:
        day, franja, slot_id, presentiality, work_mode = sk[:5]
        candidates = df[(df["day"] == day) & (df["slot_id"] == slot_id)].copy()
        if "franja" in candidates.columns:
            candidates = candidates[candidates["franja"] == franja]
        if "presentiality" in candidates.columns:
            candidates = candidates[candidates["presentiality"] == presentiality]
        if "work_mode" in candidates.columns:
            candidates = candidates[candidates["work_mode"] == work_mode]

        if candidates.empty:
            continue

        professional = str(candidates.iloc[-1]["professional"])
        if professional in professional_set:
            out[sk] = professional

    return out


def _prepare_reductions_df(df: pd.DataFrame, professionals: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["professional_id", "start_day", "end_day", "reduction_pct"])

    out = df.copy()
    required = {"professional_id", "start_day", "end_day", "reduction_pct"}
    for col in required:
        if col not in out.columns:
            out[col] = None

    out["professional_id"] = out["professional_id"].fillna("").astype(str).str.strip().str.upper()
    out["start_day"] = pd.to_datetime(out["start_day"], errors="coerce")
    out["end_day"] = pd.to_datetime(out["end_day"], errors="coerce")
    # Missing dates → sentinel bounds: reduction treated as always-active.
    out["start_day"] = out["start_day"].fillna(pd.Timestamp("2000-01-01"))
    out["end_day"] = out["end_day"].fillna(pd.Timestamp("2099-12-31"))
    out["reduction_pct"] = (
        pd.to_numeric(out["reduction_pct"], errors="coerce")
        .fillna(0)
        .clip(0, 100)
        .astype(int)
    )
    out = out[
        out["professional_id"].isin(set(professionals))
        & (out["end_day"] >= out["start_day"])
    ].copy()
    return out


