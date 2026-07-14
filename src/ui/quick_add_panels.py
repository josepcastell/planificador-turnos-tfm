"""Ajustos ràpids sota el render del calendari (pestanya Calendari).

TOTS s'apliquen SENSE el solver (el botó és «Introduir», no «Reajustar»):

  • Introduir absència / guàrdia → es registra a les dades (data/absences,
    data/guards; la guàrdia porta la POSTGUÀRDIA de l'endemà) I s'aplica
    DIRECTAMENT al calendari generat: cada casella alliberada passa al
    SUBSTITUT vàlid amb menys càrrega mensual proporcional a la jornada
    (vegeu _cover_professional_cells) — res més no es mou. Sense candidat,
    la casella queda buida. El solver només ho tindrà en compte quan es
    torni a «Generar».

  • Canvi puntual / Ordinària↔peonada / Canvi de presencialitat →
    EDICIÓ DIRECTA del calendari generat (`outputs/schedule_weekday.csv`)
    + re-render a l'instant. NO sobreviuen a una nova «Generació».
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


from src.domain.constants import ABSENCE_TYPES
from src.domain.schedule_format import is_review_slot

_SCHEDULE_PATH = Path("outputs/schedule_weekday.csv")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _profs(all_professional_options) -> list[str]:
    return sorted(
        p for p in (all_professional_options or [])
        if str(p).strip().upper() not in ("", "NONE", "NAN")
    )


def _default_day(year: int, month: int) -> date:
    try:
        return date(year, month, 1)
    except ValueError:
        return date.today()


def _append_row(path: Path, header_cols: list[str], row: dict) -> None:
    """Afegeix una fila a un CSV de dades, creant-lo amb capçalera si cal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path)
    else:
        df = pd.DataFrame(columns=header_cols)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    for c in header_cols:
        if c not in df.columns:
            df[c] = ""
    df = df[header_cols + [c for c in df.columns if c not in header_cols]]
    df.to_csv(path, index=False)


def _row_label(row) -> str:
    return f"{row['day']} · {row['franja']} · {row['slot_id']}  ({row.get('professional', '')})"


_ELIGIBILITY_PATH = Path("data/eligibility.csv")
_REDUCTIONS_PATH = Path("data/reductions/assignments.csv")
_WD_CODES = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY",
             "SATURDAY", "SUNDAY"]


def _read_csv_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def _cover_professional_cells(
    df: pd.DataFrame,
    mask: pd.Series,
    removed: str,
    candidates: list[str],
    absences_path: Path,
    guards_path: Path,
    professionals_path: Path,
) -> tuple[int, int, str]:
    """Cobreix les caselles del facultatiu absent amb un SUBSTITUT
    determinista (SENSE solver): per a cada (dia, franja) afectat, tria
    el candidat vàlid amb MENYS càrrega aquell mes, proporcional a la
    jornada. Vàlid = no és l'absent, no té res aquella franja, no està
    absent/de guàrdia/postguàrdia aquell dia, treballa aquell dia de la
    setmana, és elegible per a les màquines (allowed=0 exclou) i el seu
    mode de presència ho permet. Totes les màquines que l'absent duia en
    una mateixa franja van al MATEIX substitut (preserva blocs vinculats).
    Sense candidat vàlid, la casella queda buida. No toca res més.
    Retorna (cobertes, forats, detall_substituts)."""
    from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
    removed_u = str(removed).strip().upper()
    # Les files de GUÀRDIA del calendari (GD/POST_GUARDIA/REFUERZO) NO se
    # substitueixen: es gestionen des de l'editor de guàrdies (les dades
    # seguirien dient l'altre nom i la capçalera del PDF divergiria).
    if "slot_id" in df.columns:
        mask = mask & ~df["slot_id"].str.strip().str.upper().isin(
            GUARDS_RESERVED_SLOT_IDS
        )

    profd = _read_csv_or_empty(professionals_path)
    presence_mode: dict = {}
    nonw: dict = {}
    fallback_ids: set = set()
    if not profd.empty and "professional_id" in profd.columns:
        for r in profd.itertuples(index=False):
            pid = str(getattr(r, "professional_id", "") or "").strip().upper()
            if not pid:
                continue
            try:
                if int(float(getattr(r, "fallback", 0) or 0)) == 1:
                    fallback_ids.add(pid)
            except (TypeError, ValueError):
                pass
            presence_mode[pid] = str(
                getattr(r, "presence_mode", "") or ""
            ).strip().upper()
            nonw[pid] = {
                c.strip().upper()
                for c in str(getattr(r, "non_working_weekdays", "") or "").split(";")
                if c.strip()
            }

    elig = _read_csv_or_empty(_ELIGIBILITY_PATH)
    elig_block: set = set()
    if not elig.empty and {"professional_id", "slot_id", "allowed"}.issubset(elig.columns):
        blk = elig[pd.to_numeric(elig["allowed"], errors="coerce").fillna(1) == 0]
        elig_block = {
            (str(r.professional_id).strip().upper(), str(r.slot_id).strip().upper())
            for r in blk.itertuples(index=False)
        }

    absd = _read_csv_or_empty(absences_path)
    abs_ranges = []
    if not absd.empty and {"professional_id", "start_day", "end_day"}.issubset(absd.columns):
        for r in absd.itertuples(index=False):
            try:
                abs_ranges.append((
                    str(r.professional_id).strip().upper(),
                    date.fromisoformat(str(r.start_day)[:10]),
                    date.fromisoformat(str(r.end_day)[:10]),
                ))
            except ValueError:
                continue

    guardd = _read_csv_or_empty(guards_path)
    guard_days: set = set()
    post_days: set = set()
    if not guardd.empty and {"day", "professional_id"}.issubset(guardd.columns):
        for r in guardd.itertuples(index=False):
            pid = str(r.professional_id).strip().upper()
            try:
                gd = date.fromisoformat(str(r.day)[:10])
            except ValueError:
                continue
            guard_days.add((pid, gd.isoformat()))
            post_days.add((pid, (gd + timedelta(days=1)).isoformat()))

    redd = _read_csv_or_empty(_REDUCTIONS_PATH)
    reductions = []
    if not redd.empty and {"professional_id", "start_day", "end_day", "reduction_pct"}.issubset(redd.columns):
        for r in redd.itertuples(index=False):
            try:
                reductions.append((
                    str(r.professional_id).strip().upper(),
                    date.fromisoformat(str(r.start_day)[:10]),
                    date.fromisoformat(str(r.end_day)[:10]),
                    float(r.reduction_pct),
                ))
            except (ValueError, TypeError):
                continue

    def _cap_pct(p: str, ym: str) -> float:
        c = 100.0
        c -= 20.0 * len(nonw.get(p, set()) & set(_WD_CODES[:5]))
        m_ini = date.fromisoformat(ym + "-01")
        m_fi = (pd.Timestamp(m_ini) + pd.offsets.MonthEnd(0)).date()
        actives = [
            pct for (pid, s, e, pct) in reductions
            if pid == p and s <= m_fi and e >= m_ini
        ]
        if actives:
            c -= max(actives)
        return max(c, 10.0)

    def _blocked(p: str, day_iso: str, franja: str) -> bool:
        try:
            d = date.fromisoformat(day_iso)
        except ValueError:
            return True
        if _WD_CODES[d.weekday()] in nonw.get(p, set()):
            return True
        for (pid, s, e) in abs_ranges:
            if pid == p and s <= d <= e:
                return True
        if (p, day_iso) in post_days:
            return True
        if (p, day_iso) in guard_days and franja in ("TARDA", "NIT"):
            return True
        return False

    # Càrrega mensual actual (files amb facultatiu real) per (prof, mes).
    loads: dict = {}
    prof_u = df["professional"].str.strip().str.upper()
    ym_col = df["day"].str.slice(0, 7)
    for pu, ym in zip(prof_u, ym_col):
        if pu and pu not in ("NONE", "NAN"):
            loads[(pu, ym)] = loads.get((pu, ym), 0) + 1

    covered = holes = 0
    by_sub: dict = {}
    aff = df.loc[mask]
    for (day, franja), idxs in aff.groupby(["day", "franja"]).groups.items():
        idx_list = list(idxs)
        rows = df.loc[idx_list]
        slots = [str(s).strip().upper() for s in rows["slot_id"]]
        pres_set = {
            str(v).strip().upper() for v in rows.get("presentiality", pd.Series())
        }
        ym = str(day)[:7]
        busy = set(
            df.loc[
                (df["day"] == day) & (df["franja"] == franja), "professional"
            ].str.strip().str.upper()
        ) - {"", removed_u}
        best = None
        for p in candidates:
            pu = str(p).strip().upper()
            if pu in ("", removed_u) or pu in busy:
                continue
            if pu in fallback_ids:
                # El comodí és l'últim recurs del SOLVER, no del substitut
                # ràpid (amb poca càrrega sempre sortiria el primer).
                continue
            if _blocked(pu, str(day), str(franja).strip().upper()):
                continue
            if any((pu, s) in elig_block for s in slots):
                continue
            pm = presence_mode.get(pu, "")
            if pm == "NO_PRESENCIAL" and "PRESENCIAL" in pres_set:
                continue
            if pm == "PRESENCIAL" and "NO_PRESENCIAL" in pres_set:
                continue
            load = loads.get((pu, ym), 0)
            key = (load / (_cap_pct(pu, ym) / 100.0), load, pu)
            if best is None or key < best[0]:
                best = (key, p)
        if best is not None:
            sub = best[1]
            df.loc[idx_list, "professional"] = sub
            su = str(sub).strip().upper()
            loads[(su, ym)] = loads.get((su, ym), 0) + len(idx_list)
            covered += len(idx_list)
            by_sub[sub] = by_sub.get(sub, 0) + len(idx_list)
        else:
            df.loc[idx_list, "professional"] = ""
            holes += len(idx_list)
    detail = ", ".join(f"{s}: {n}" for s, n in sorted(by_sub.items()))
    return covered, holes, detail


def _load_schedule() -> pd.DataFrame | None:
    if not _SCHEDULE_PATH.exists() or _SCHEDULE_PATH.stat().st_size == 0:
        return None
    try:
        return pd.read_csv(_SCHEDULE_PATH, dtype=str).fillna("")
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return None


def _save_and_rerender(
    df: pd.DataFrame, professionals_path: Path, pdf_output_dir: Path,
    year: int, selected_months: list[int], toast_msg: str,
) -> None:
    """Desa el calendari editat DIRECTAMENT, re-renderitza el PDF i refresca."""
    df.to_csv(_SCHEDULE_PATH, index=False)
    from src.ui.planning_calendar_tabs import export_general_weekday_pdf
    export_general_weekday_pdf(
        _SCHEDULE_PATH, professionals_path, pdf_output_dir, year, selected_months,
    )
    st.session_state.pop("weekday_live_schedule", None)
    st.toast(toast_msg, icon="✅")
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 1) Introduir absència  → dades + buidat DIRECTE de les caselles (sense solver)
# ─────────────────────────────────────────────────────────────────────────────
def _quick_add_absence(
    absences_path: Path, guards_path: Path, profs, year, month,
    professionals_path, pdf_output_dir, selected_months,
) -> None:
    with st.expander("➕ Introduir absència", expanded=False):
        st.caption(
            "Es registra a les dades i s'aplica DIRECTAMENT al calendari: "
            "cada casella del facultatiu absent passa al company vàlid amb "
            "**menys càrrega aquell mes (proporcional a la jornada)** — res "
            "més no es mou i el solver NO intervé. Si cap candidat pot, la "
            "casella queda buida (recol·loca-la amb el canvi puntual)."
        )
        with st.form("qa_absence_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            prof = c1.selectbox("Facultatiu", profs, key="qa_abs_prof")
            atype = c2.selectbox("Tipus", ABSENCE_TYPES, key="qa_abs_type")
            c3, c4 = st.columns(2)
            d_ini = c3.date_input("Data inici", value=_default_day(year, month), key="qa_abs_ini")
            d_fi = c4.date_input("Data fi", value=_default_day(year, month), key="qa_abs_fi")
            notes = st.text_input("Notes (opcional)", key="qa_abs_notes")
            submitted = st.form_submit_button("Introduir absència", width="stretch")
        if submitted:
            if d_fi < d_ini:
                st.error("La data fi no pot ser anterior a la d'inici.")
                return
            _append_row(
                absences_path,
                ["absence_type", "professional_id", "start_day", "end_day", "notes"],
                {
                    "absence_type": atype, "professional_id": prof,
                    "start_day": d_ini.isoformat(), "end_day": d_fi.isoformat(),
                    "notes": notes,
                },
            )
            df = _load_schedule()
            affected = 0
            covered = holes = 0
            detail = ""
            if df is not None and not df.empty and {
                "day", "franja", "slot_id", "professional",
            }.issubset(df.columns):
                dd = pd.to_datetime(df["day"], errors="coerce")
                mask = (
                    (df["professional"].str.strip().str.upper() == str(prof).strip().upper())
                    & (dd >= pd.Timestamp(d_ini))
                    & (dd <= pd.Timestamp(d_fi))
                )
                affected = int(mask.sum())
                if affected:
                    covered, holes, detail = _cover_professional_cells(
                        df, mask, prof, profs,
                        absences_path, guards_path, professionals_path,
                    )
            if affected:
                msg = (
                    f"Absència introduïda: {prof} ({atype}) {d_ini}→{d_fi}. "
                    f"{covered} caselles cobertes"
                    + (f" ({detail})" if detail else "")
                    + (f"; {holes} sense candidat (buides)" if holes else "")
                    + "."
                )
                _save_and_rerender(
                    df, professionals_path, pdf_output_dir, year, selected_months, msg,
                )
            else:
                st.toast(
                    f"Absència registrada: {prof} ({atype}) {d_ini}→{d_fi} "
                    "(cap assignació afectada al calendari actual).",
                    icon="✅",
                )
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 2) Introduir guàrdia  → dades + buidat DIRECTE (tarda/nit + postguàrdia)
# ─────────────────────────────────────────────────────────────────────────────
def _quick_add_guard(
    guards_path: Path, profs, year, month,
    professionals_path, pdf_output_dir, selected_months,
) -> None:
    with st.expander("➕ Introduir guàrdia", expanded=False):
        st.caption(
            "Es registra a les dades (amb la **postguàrdia** de l'endemà) i "
            "s'aplica DIRECTAMENT al calendari: la tarda i la nit del dia de "
            "guàrdia i tot l'endemà passen al company vàlid amb **menys "
            "càrrega aquell mes (proporcional a la jornada)** — res més no "
            "es mou i el solver NO intervé. Sense candidat, la casella "
            "queda buida."
        )
        with st.form("qa_guard_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            g_day = c1.date_input("Dia de la guàrdia", value=_default_day(year, month), key="qa_guard_day")
            prof = c2.selectbox("Facultatiu", profs, key="qa_guard_prof")
            notes = st.text_input("Notes (opcional)", key="qa_guard_notes")
            submitted = st.form_submit_button("Introduir guàrdia", width="stretch")
        if submitted:
            _append_row(
                guards_path,
                ["day", "professional_id", "guard_kind", "notes"],
                {
                    "day": g_day.isoformat(), "professional_id": prof,
                    "guard_kind": "guardia", "notes": notes,
                },
            )
            df = _load_schedule()
            affected = 0
            covered = holes = 0
            detail = ""
            if df is not None and not df.empty and {
                "day", "franja", "slot_id", "professional",
            }.issubset(df.columns):
                pmask = (
                    df["professional"].str.strip().str.upper()
                    == str(prof).strip().upper()
                )
                frU = df["franja"].str.strip().str.upper()
                post_day = (g_day + timedelta(days=1)).isoformat()
                # La guàrdia allibera la tarda i la nit del dia; la
                # POSTGUÀRDIA allibera tot l'endemà — tot s'ha de cobrir.
                mask = pmask & (
                    ((df["day"] == g_day.isoformat()) & frU.isin({"TARDA", "NIT"}))
                    | (df["day"] == post_day)
                )
                affected = int(mask.sum())
                if affected:
                    covered, holes, detail = _cover_professional_cells(
                        df, mask, prof, profs,
                        absences_path, guards_path, professionals_path,
                    )
            if affected:
                msg = (
                    f"Guàrdia introduïda: {prof} el {g_day} (postguàrdia "
                    f"{(g_day + timedelta(days=1)).isoformat()}). "
                    f"{covered} caselles cobertes"
                    + (f" ({detail})" if detail else "")
                    + (f"; {holes} sense candidat (buides)" if holes else "")
                    + "."
                )
                _save_and_rerender(
                    df, professionals_path, pdf_output_dir, year, selected_months, msg,
                )
            else:
                st.toast(
                    f"Guàrdia registrada: {prof} el {g_day} (cap assignació "
                    "afectada al calendari actual).",
                    icon="✅",
                )
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# 3) Introduir canvi puntual d'assignació  → edició directa
# ─────────────────────────────────────────────────────────────────────────────
def _quick_add_assignment_change(profs, year, professionals_path, pdf_output_dir, selected_months) -> None:
    with st.expander("➕ Introduir canvi puntual d'assignació", expanded=False):
        st.caption(
            "Canvi manual immediat (sense solver): tries tu el facultatiu. "
            "Serveix també per recol·locar les caselles buidades per una "
            "absència o guàrdia acabada d'introduir."
        )
        df = _load_schedule()
        if df is None or df.empty:
            st.info("Genera primer el calendari per canviar assignacions.")
            return
        if not {"day", "franja", "slot_id", "professional"}.issubset(df.columns):
            st.info("El calendari generat no té el format esperat.")
            return
        labels = {f"{i}: " + _row_label(r): i for i, r in df.iterrows()}
        with st.form("qa_change_form", clear_on_submit=True):
            label = st.selectbox("Assignació a canviar", list(labels.keys()), key="qa_chg_slot")
            new_prof = st.selectbox("Nou facultatiu", [""] + profs, key="qa_chg_prof")
            submitted = st.form_submit_button("Introduir canvi", width="stretch")
        if submitted:
            idx = labels[label]
            old = df.at[idx, "professional"]
            df.at[idx, "professional"] = new_prof
            _save_and_rerender(
                df, professionals_path, pdf_output_dir, year, selected_months,
                f"Canvi aplicat: {df.at[idx, 'slot_id']} el {df.at[idx, 'day']} "
                f"({old or '—'} → {new_prof or '—'}).",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4) Ordinària ↔ peonada  → edició directa (bidireccional)
# ─────────────────────────────────────────────────────────────────────────────
def _quick_toggle_peonada(year, professionals_path, pdf_output_dir, selected_months) -> None:
    with st.expander("🔄 Canviar ordinària ↔ peonada", expanded=False):
        st.caption(
            "Marca manual immediata (sense solver): converteix una NP "
            "ordinària en peonada (extra) o torna una peonada a ordinària."
        )
        df = _load_schedule()
        if df is None or df.empty:
            st.info("Genera primer el calendari per marcar peonades.")
            return
        needed = {"day", "franja", "slot_id", "professional", "presentiality", "work_mode"}
        if not needed.issubset(set(df.columns)):
            st.info("El calendari generat no té el format esperat.")
            return
        slotU = df["slot_id"].str.strip().str.upper()
        wmU = df["work_mode"].str.strip().str.upper()
        presU = df["presentiality"].str.strip().str.upper()
        has_prof = df["professional"].str.strip() != ""
        occ = df.groupby(["day", "franja", "slot_id"])["professional"].transform("size")
        is_peonada = wmU == "PEONADA"
        # Ordinària → peonada: NP, no peonada, un sol facultatiu, no revisió.
        # is_review_slot: la revisió es determina pel CATÀLEG (review=1), mai
        # per la substring "REV" al nom (falsos positius/negatius).
        ord_to_peo = (
            (presU == "NO_PRESENCIAL")
            & ~is_peonada
            & has_prof
            & (~slotU.map(is_review_slot))
            & (occ == 1)
        )
        # Peonada → ordinària: qualsevol fila ja marcada com a peonada.
        peo_to_ord = is_peonada & has_prof
        elig = df[ord_to_peo | peo_to_ord]
        if elig.empty:
            st.info(
                "No hi ha assignacions elegibles (NP ordinària d'un sol "
                "facultatiu i no revisió, o peonades existents)."
            )
            return

        def _lab(i, r):
            direction = (
                "peonada→ordinària"
                if str(r["work_mode"]).strip().upper() == "PEONADA"
                else "ordinària→peonada"
            )
            return (f"{i}: {r['day']} · {r['franja']} · {r['slot_id']} "
                    f"({r['professional']})  [{direction}]")

        labels = {_lab(i, r): i for i, r in elig.iterrows()}
        with st.form("qa_peonada_form", clear_on_submit=True):
            label = st.selectbox(
                "Assignació a convertir", list(labels.keys()), key="qa_peo_slot",
            )
            submitted = st.form_submit_button("Convertir", width="stretch")
        if submitted:
            idx = labels[label]
            to_peonada = str(df.at[idx, "work_mode"]).strip().upper() != "PEONADA"
            df.at[idx, "work_mode"] = "PEONADA" if to_peonada else "NORMAL"
            verb = "Ordinària → peonada" if to_peonada else "Peonada → ordinària"
            _save_and_rerender(
                df, professionals_path, pdf_output_dir, year, selected_months,
                f"{verb}: {df.at[idx, 'professional']} a "
                f"{df.at[idx, 'slot_id']} ({df.at[idx, 'franja']}) el {df.at[idx, 'day']}.",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 5) Canviar presencialitat (PRES ↔ NP)  → edició directa
# ─────────────────────────────────────────────────────────────────────────────
def _quick_toggle_presentiality(year, professionals_path, pdf_output_dir, selected_months) -> None:
    with st.expander("🔁 Canviar presencialitat (PRES ↔ NP)", expanded=False):
        st.caption(
            "Canvi manual immediat (sense solver): gira una màquina de "
            "presencial a no presencial o al revés."
        )
        df = _load_schedule()
        if df is None or df.empty:
            st.info("Genera primer el calendari.")
            return
        needed = {"day", "franja", "slot_id", "professional", "presentiality", "work_mode"}
        if not needed.issubset(set(df.columns)):
            st.info("El calendari generat no té el format esperat.")
            return
        slotU = df["slot_id"].str.strip().str.upper()
        elig = df[
            (df["professional"].str.strip() != "")
            & (~slotU.map(is_review_slot))
            & (df["work_mode"].str.strip().str.upper() != "PEONADA")
        ]
        if elig.empty:
            st.info("No hi ha assignacions de màquina (no revisió, no peonada) per canviar.")
            return

        def _lab(i, r):
            cur = "PRES" if str(r["presentiality"]).strip().upper() == "PRESENCIAL" else "NP"
            new = "NP" if cur == "PRES" else "PRES"
            return (f"{i}: {r['day']} · {r['franja']} · {r['slot_id']} "
                    f"({r['professional']})  [{cur}→{new}]")

        labels = {_lab(i, r): i for i, r in elig.iterrows()}
        with st.form("qa_presflip_form", clear_on_submit=True):
            label = st.selectbox("Assignació a girar", list(labels.keys()), key="qa_presflip_slot")
            submitted = st.form_submit_button("Girar presencialitat", width="stretch")
        if submitted:
            idx = labels[label]
            cur = str(df.at[idx, "presentiality"]).strip().upper()
            new = "NO_PRESENCIAL" if cur == "PRESENCIAL" else "PRESENCIAL"
            df.at[idx, "presentiality"] = new
            if "is_flipped" in df.columns:
                df.at[idx, "is_flipped"] = "0"
            _save_and_rerender(
                df, professionals_path, pdf_output_dir, year, selected_months,
                f"Presencialitat canviada: {df.at[idx, 'slot_id']} "
                f"({df.at[idx, 'franja']}) el {df.at[idx, 'day']} → "
                f"{'NO PRESENCIAL' if new == 'NO_PRESENCIAL' else 'PRESENCIAL'}.",
            )


def render_quick_add_panels(
    year: int,
    month: int,
    selected_months: list[int],
    professional_options: list[str],
    all_professional_options: list[str] | None,
    professionals_path: Path,
    pdf_output_dir: Path,
    absences_path: Path,
    guards_path: Path,
) -> None:
    """Renderitza els 5 desplegables d'ajust ràpid sota el render.
    TOTS actuen SENSE el solver: absència i guàrdia es registren a les
    dades i les seves caselles passen al substitut amb menys càrrega
    mensual proporcional; canvi puntual, peonada i presencialitat editen
    el calendari directament."""
    profs = _profs(all_professional_options or professional_options)
    st.markdown("##### Ajustos ràpids (sense solver)")
    st.caption(
        "Tot s'aplica a l'instant, sense recalcular res: **absència** i "
        "**guàrdia** (amb postguàrdia) passen les caselles alliberades al "
        "company vàlid amb **menys càrrega del mes** (proporcional a la "
        "jornada); **canvi puntual**, **peonada** i **presencialitat** "
        "editen la casella que triïs. El solver només ho tindrà en compte "
        "si tornes a **Generar**."
    )
    _quick_add_absence(
        absences_path, guards_path, profs, year, month,
        professionals_path, pdf_output_dir, selected_months,
    )
    _quick_add_guard(
        guards_path, profs, year, month,
        professionals_path, pdf_output_dir, selected_months,
    )
    _quick_add_assignment_change(profs, year, professionals_path, pdf_output_dir, selected_months)
    _quick_toggle_peonada(year, professionals_path, pdf_output_dir, selected_months)
    _quick_toggle_presentiality(year, professionals_path, pdf_output_dir, selected_months)
