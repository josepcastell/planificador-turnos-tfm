from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS
from src.domain.month_scope import in_logical_months
from src.domain.schedule_format import is_review_slot, slot_metric_family

_SCOPED_COLS = ["day", "day_dt", "slot_id", "professional", "presentiality", "work_mode"]


import re as _re
_SUFFIX_RE = _re.compile(r"_\d+$")


def _base_pid(pid: str) -> str:
    """Treu el sufix `_N` de duplicats (XX, XX_2 → XX). Per a mètriques
    els duplicats es comporten com el mateix facultatiu."""
    return _SUFFIX_RE.sub("", str(pid).strip().upper())


def _slot_link_pairs() -> list[tuple[str, str]]:
    """Parelles d'slots vinculats del catàleg (compten com 1 màquina)."""
    cat = Path("data/slot_catalog.csv")
    if not cat.exists() or cat.stat().st_size == 0:
        return []
    try:
        from src.services.slot_catalog import load_slot_catalog, slot_link_pairs
        return slot_link_pairs(load_slot_catalog(cat))
    except Exception:
        return []


def _collapse_linked(df: pd.DataFrame) -> pd.DataFrame:
    """Treu la fila duplicada de cada parella vinculada: si el mateix
    facultatiu té els dos slots vinculats el mateix dia, compten com 1
    màquina. Es conserva el membre PRESENCIAL (com fa el solver)."""
    pairs = _slot_link_pairs()
    if not pairs or df.empty:
        return df
    df = df.copy()
    df["_sid"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df["_pro"] = df["professional"].fillna("").astype(str).str.strip().str.upper()
    df["_day"] = df["day"].astype(str)
    df["_pres"] = df.get(
        "presentiality", pd.Series("", index=df.index)
    ).fillna("").astype(str).str.upper().eq("PRESENCIAL")
    drop_idx: list = []
    for (_pro, _day), g in df.groupby(["_pro", "_day"], sort=False):
        for a, b in pairs:
            ga = g[g["_sid"] == a]
            gb = g[g["_sid"] == b]
            if ga.empty or gb.empty:
                continue
            n = min(len(ga), len(gb))
            if bool(ga["_pres"].any()) and not bool(gb["_pres"].any()):
                drop_from = gb
            elif bool(gb["_pres"].any()) and not bool(ga["_pres"].any()):
                drop_from = ga
            else:
                drop_from = gb
            drop_idx.extend(list(drop_from.index[:n]))
    return df.drop(index=drop_idx).drop(
        columns=["_sid", "_pro", "_day", "_pres"], errors="ignore"
    )


def _live_schedule_df() -> pd.DataFrame | None:
    """Calendari editat en sessió (canvis manuals encara no regenerats),
    si n'hi ha. Així les mètriques queden sincronitzades amb el que es
    veu i s'edita al visualitzador."""
    live = st.session_state.get("weekday_live_schedule")
    if isinstance(live, pd.DataFrame) and not live.empty:
        return live
    return None


def _preferred_schedule_path() -> Path | None:
    """Retorna el path de l'únic calendari (`schedule_weekday.csv`),
    o None si encara no s'ha generat."""
    path = Path("outputs/schedule_weekday.csv")
    return path if (path.exists() and path.stat().st_size > 0) else None


def _scoped_machine_rows(year: int, metric_months: list[int]) -> pd.DataFrame:
    """Files de MÀQUINA dins l'àmbit: pren els canvis manuals en sessió
    (visualitzador) si n'hi ha; si no, el calendari generat. Filtra per
    (any, mesos), neteja facultatiu/slot, exclou revisió i guàrdies i
    col·lapsa els parells vinculats."""
    live = _live_schedule_df()
    if live is not None:
        df = live.copy()
    else:
        path = _preferred_schedule_path()
        if path is None:
            return pd.DataFrame(columns=_SCOPED_COLS)
        df = pd.read_csv(path)
    if not {"day", "slot_id", "professional"}.issubset(df.columns):
        return pd.DataFrame(columns=_SCOPED_COLS)
    for c in ("presentiality", "work_mode"):
        if c not in df.columns:
            df[c] = ""
    df["day_dt"] = pd.to_datetime(df["day"], errors="coerce")
    df = df[in_logical_months(df["day_dt"], year, metric_months)].copy()
    if df.empty:
        return pd.DataFrame(columns=_SCOPED_COLS)
    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df["professional"] = (
        df["professional"].fillna("").astype(str).str.strip().str.upper()
        .map(_base_pid)
    )
    df["presentiality"] = df["presentiality"].fillna("").astype(str).str.upper()
    df["work_mode"] = df["work_mode"].fillna("").astype(str).str.upper()
    mask = (
        ~df["slot_id"].map(is_review_slot)
        & ~df["slot_id"].isin(GUARDS_RESERVED_SLOT_IDS)
        & ~df["professional"].isin(["", "NONE", "NAN"])
    )
    df = df[mask].copy()
    if df.empty:
        return pd.DataFrame(columns=_SCOPED_COLS)
    df = _collapse_linked(df)
    return df[_SCOPED_COLS].reset_index(drop=True)


def _scoped_review_rows(year: int, metric_months: list[int]) -> pd.DataFrame:
    """Files de REVISIÓ dins l'àmbit (any, mesos), per comptar quantes
    revisions de cada tipus fa cada facultatiu. Pren els canvis en sessió
    (visualitzador) si n'hi ha; si no, el calendari generat. Columnes:
    slot_id, professional."""
    cols = ["slot_id", "professional"]
    live = _live_schedule_df()
    if live is not None:
        df = live.copy()
    else:
        path = _preferred_schedule_path()
        if path is None:
            return pd.DataFrame(columns=cols)
        df = pd.read_csv(path)
    if not {"day", "slot_id", "professional"}.issubset(df.columns):
        return pd.DataFrame(columns=cols)
    df["day_dt"] = pd.to_datetime(df["day"], errors="coerce")
    df = df[in_logical_months(df["day_dt"], year, metric_months)].copy()
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["slot_id"] = df["slot_id"].fillna("").astype(str).str.strip().str.upper()
    df["professional"] = (
        df["professional"].fillna("").astype(str).str.strip().str.upper()
        .map(_base_pid)
    )
    mask = df["slot_id"].map(is_review_slot) & ~df["professional"].isin(["", "NONE", "NAN"])
    return df[mask][cols].reset_index(drop=True)


def _fallback_ids() -> set[str]:
    """IDs (en majúscules) dels facultatius comodí (professionals.csv
    fallback=1)."""
    pp = Path("data/professionals.csv")
    if not pp.exists() or pp.stat().st_size == 0:
        return set()
    pdf = pd.read_csv(pp)
    if not {"professional_id", "fallback"}.issubset(pdf.columns):
        return set()
    fb = pd.to_numeric(pdf["fallback"], errors="coerce").fillna(0).astype(int)
    return {_base_pid(p) for p in pdf.loc[fb == 1, "professional_id"]}


def _capacity_by_prof(year: int, selected_months: list[int]) -> dict[str, float]:
    """% de jornada efectiu per facultatiu (100 − reducció), de la
    comptabilitat del solver (outputs/metrics_weekday.csv). Buit = 100."""
    path = Path("outputs/metrics_weekday.csv")
    if not path.exists() or path.stat().st_size == 0:
        return {}
    df = pd.read_csv(path)
    if not {"year_month", "professional", "workday_reduction_pct"}.issubset(df.columns):
        return {}
    scope = {f"{year}-{mm:02d}" for mm in selected_months}
    df = df[df["year_month"].astype(str).isin(scope)].copy()
    if df.empty:
        return {}
    df["professional"] = (
        df["professional"].fillna("").astype(str).str.strip().str.upper()
        .map(_base_pid)
    )
    df["r"] = pd.to_numeric(df["workday_reduction_pct"], errors="coerce").fillna(0)
    red = df.groupby("professional")["r"].mean()
    return {p: max(1.0, 100.0 - float(v)) for p, v in red.items()}


def _effective_capacity_by_prof(year: int, selected_months: list[int]) -> dict[str, float]:
    """% de DISPONIBILITAT EFECTIVA per facultatiu (jornada × dies presents
    − absències − postguàrdies), de la comptabilitat del solver
    (outputs/metrics_weekday.csv, columna `effective_capacity_pct`). És el
    denominador real amb què el solver reparteix màquines/presencials. Buit
    si la columna no existeix (calendaris generats abans d'aquesta versió)."""
    path = Path("outputs/metrics_weekday.csv")
    if not path.exists() or path.stat().st_size == 0:
        return {}
    df = pd.read_csv(path)
    if not {"year_month", "professional", "effective_capacity_pct"}.issubset(df.columns):
        return {}
    scope = {f"{year}-{mm:02d}" for mm in selected_months}
    df = df[df["year_month"].astype(str).isin(scope)].copy()
    if df.empty:
        return {}
    df["professional"] = (
        df["professional"].fillna("").astype(str).str.strip().str.upper()
        .map(_base_pid)
    )
    df["e"] = pd.to_numeric(df["effective_capacity_pct"], errors="coerce")
    df = df.dropna(subset=["e"])
    if df.empty:
        return {}
    eff = df.groupby("professional")["e"].mean()
    return {p: max(1.0, float(v)) for p, v in eff.items()}


def _scoped_solver_metrics(
    year: int, selected_months: list[int], fallback_ids: set[str],
    m: pd.DataFrame,
) -> pd.DataFrame:
    """Càrrega per facultatiu calculada des de les MATEIXES files de
    màquina que la resta de mètriques (exclou TOTA la revisió —inclòs
    revisa TC— i guàrdies, col·lapsa parells vinculats). El % de jornada
    surt de la comptabilitat del solver. Inclou el comodí (fallback,
    p.ex. TLD) com a fila extra.
    Columnes: professional, is_fallback, capacity_pct, machine_load,
    presential, no_pres_ord, no_pres_peo, family_diff."""
    cols = ["professional", "is_fallback", "capacity_pct", "machine_load",
            "ordinary_load", "presential", "no_pres_ord", "no_pres_peo",
            "family_diff"]
    if m is None or m.empty:
        return pd.DataFrame(columns=cols)
    g = m.copy()
    g["_fam"] = g["slot_id"].map(slot_metric_family)
    g["_pres"] = (g["presentiality"] == "PRESENCIAL").astype(int)
    g["_npo"] = ((g["presentiality"] == "NO_PRESENCIAL") & (g["work_mode"] == "NORMAL")).astype(int)
    g["_peo"] = (g["work_mode"] == "PEONADA").astype(int)
    g["_tc"] = (g["_fam"] == "TC").astype(int)
    g["_rm"] = (g["_fam"] == "RM").astype(int)
    agg = g.groupby("professional", as_index=False).agg(
        machine_load=("slot_id", "size"),
        presential=("_pres", "sum"),
        no_pres_ord=("_npo", "sum"),
        no_pres_peo=("_peo", "sum"),
        tc=("_tc", "sum"),
        rm=("_rm", "sum"),
    )
    agg["family_diff"] = (agg["tc"] - agg["rm"]).abs()
    # Màquines ORDINÀRIES = PRES + NO_PRES ORD (sense peonades). És el que
    # el solver equilibra (`_add_ordinary_machine_balance`); les peonades
    # estan a part amb cap dur de 3/facultatiu.
    agg["ordinary_load"] = agg["presential"] + agg["no_pres_ord"]
    cap = _capacity_by_prof(year, selected_months)
    agg["capacity_pct"] = agg["professional"].map(lambda p: cap.get(p, 100.0))
    agg["is_fallback"] = agg["professional"].isin(fallback_ids)
    return agg[cols]


def _render_accumulated_metrics(
    year: int, selected_months: list[int], fallback_ids: set[str],
    m: pd.DataFrame,
) -> None:
    """Acumulat entre mesos que el solver arrossega per muntar el mes
    següent: per facultatiu, presencials i no presencials ordinàries
    acumulades a l'àmbit, més la dispersió (CV) que el solver equilibra
    (Tiers 3 i 4), normalitzada per la DISPONIBILITAT EFECTIVA de cada
    facultatiu (jornada − absències − postguàrdies), no només pel % de
    jornada nominal. Així qui fa guàrdies (→ més postguàrdies) no surt com
    a desequilibri.

    És el mateix comptatge que `prior_presential_counts` /
    `prior_no_presential_counts` que el solver passa d'un mes al següent."""
    sm = _scoped_solver_metrics(year, selected_months, fallback_ids, m)
    sm = sm[~sm["is_fallback"]].copy()
    if sm.empty:
        st.info("Encara no hi ha càrrega acumulada a l'àmbit seleccionat.")
        return

    # Denominador = DISPONIBILITAT EFECTIVA (jornada − absències −
    # postguàrdies), exactament el que el solver fa servir per repartir. Si la
    # columna no hi és (calendari generat abans d'aquesta versió), cau a la
    # jornada nominal i s'avisa.
    eff = _effective_capacity_by_prof(year, selected_months)
    using_effective = bool(eff)
    sm["disp"] = sm.apply(
        lambda r: float(eff.get(r["professional"], r["capacity_pct"])), axis=1
    )

    sm["total"] = sm["presential"] + sm["no_pres_ord"]
    view = (
        sm.rename(columns={
            "professional": "Facultatiu",
            "presential": "Presencials",
            "no_pres_ord": "No presencials",
            "total": "Total",
            "disp": "% disponib.",
        })[["Facultatiu", "Presencials", "No presencials", "Total", "% disponib."]]
        .sort_values("Total", ascending=False)
        .reset_index(drop=True)
    )
    view["% disponib."] = view["% disponib."].round(0).astype(int)
    st.dataframe(
        view, width="stretch", hide_index=True,
        height=38 + 35 * (len(view) + 1),
    )

    # Dispersió: el que minimitzen els Tiers 3 (presencials) i 4 (no
    # presencials). Es calcula sobre la càrrega AJUSTADA a la disponibilitat
    # efectiva, que és el que el solver equilibra; així ni la mitja jornada ni
    # les guàrdies/postguàrdies apareixen com a desequilibri fals.
    def _stats(count_col: str) -> tuple[int, int, float]:
        cap = sm["disp"].clip(lower=1.0) / 100.0
        adj = sm[count_col] / cap
        mean = float(adj.mean())
        cv = float(adj.std(ddof=0) / mean * 100.0) if mean > 0 else 0.0
        return int(sm[count_col].min()), int(sm[count_col].max()), cv

    p_min, p_max, p_cv = _stats("presential")
    n_min, n_max, n_cv = _stats("no_pres_ord")
    c1, c2 = st.columns(2)
    with c1:
        st.metric(
            "Presencials · dispersió (CV)", f"{p_cv:.0f}%",
            help="Coeficient de variació de la càrrega presencial ajustada "
                 "a la disponibilitat efectiva. Com més baix, més equitativa.",
        )
        st.caption(f"Rang real: {p_min}–{p_max} per facultatiu.")
    with c2:
        st.metric(
            "No presencials · dispersió (CV)", f"{n_cv:.0f}%",
            help="Coeficient de variació de la càrrega no presencial "
                 "ordinària ajustada a la disponibilitat efectiva.",
        )
        st.caption(f"Rang real: {n_min}–{n_max} per facultatiu.")

    if using_effective:
        st.caption(
            "Acumulat de l'àmbit. La **% disponib.** és la disponibilitat "
            "efectiva (jornada − absències − postguàrdies) amb què el solver "
            "reparteix: qui fa guàrdies en té menys. La dispersió (CV) es "
            "calcula sobre càrrega / disponibilitat (equitat L1 = suma de "
            "desviacions, L∞ = desviació màxima)."
        )
    else:
        st.caption(
            "Acumulat de l'àmbit. La **% disponib.** mostra de moment només la "
            "jornada nominal; **regenera el calendari** per descomptar també "
            "absències i postguàrdies. La dispersió (CV) es calcula sobre "
            "càrrega / disponibilitat."
        )


def render_regenerate_button_for(
    restriction_key: str,
    label: str,
    *,
    year: int,
    month: int,
    scope_start_month: int,
    scope_end_month: int,
    selected_months: list[int],
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    base_calendar_path: Path,
    session_dir: Path,
    save_generated_session_folder,
    pdf_output_dir: Path,
    professionals_path: Path,
) -> None:
    """Parell de botons «Regenerar» + «Desfer» per a una restricció concreta.
    El «Regenerar» aplica NOMÉS aquesta restricció sobre el definitiu
    actual (o l'inicial si encara no n'hi ha); el «Desfer» restaura
    l'estat anterior del definitiu (undo de nivell únic)."""
    from src.ui.planning_calendar_tabs import (
        has_undo_available,
        run_weekday_regenerate,
        run_weekday_undo,
    )
    _col_regen, _col_undo = st.columns([3, 1])
    with _col_regen:
        if st.button(
            label,
            key=f"regenerate_btn_{restriction_key}",
            width="stretch",
            type="primary",
            help=(
                "Aplica NOMÉS aquesta restricció al definitiu actual. Si "
                "encara no hi ha definitiu, parteix del calendari inicial. "
                "Les restriccions aplicades anteriorment es mantenen "
                "perquè ja són al definitiu (estabilitat soft)."
            ),
        ):
            run_weekday_regenerate(
                f"Regenerar amb {restriction_key}",
                year, scope_start_month, scope_end_month, selected_months,
                public_holidays_path, base_calendar_overrides_path,
                base_calendar_path, session_dir, month,
                save_generated_session_folder,
                pdf_output_dir, professionals_path,
                keep_restriction=restriction_key,
            )
            st.rerun()
    with _col_undo:
        _undo_available = has_undo_available()
        if st.button(
            "Desfer",
            key=f"undo_btn_{restriction_key}",
            width="stretch",
            disabled=not _undo_available,
            help=(
                "Restaura el calendari definitiu anterior (abans del "
                "darrer Regenerar). Undo de nivell únic."
            ) if _undo_available else (
                "No hi ha cap regeneració anterior per desfer."
            ),
        ):
            if run_weekday_undo(pdf_output_dir):
                st.toast("Calendari definitiu restaurat.", icon="↩️")
                st.rerun()


def render_last_regeneration_report() -> None:
    """Informe del darrer regenerat: quines assignacions ha canviat el
    solver respecte al punt de partida (definitiu anterior o inicial)."""
    if "weekday_reajust_report" not in st.session_state:
        return
    from src.ui.planning_calendar_tabs import _render_readjustment_report
    _reajust_report = st.session_state["weekday_reajust_report"]
    if _reajust_report is None:
        _reajust_report = pd.DataFrame()
    _n_moved = len(_reajust_report)
    with st.expander(
        f"Assignacions canviades en la darrera regeneració ({_n_moved})",
        expanded=bool(_n_moved),
    ):
        _render_readjustment_report(_reajust_report)


def _machine_crosstab_table(rows: pd.DataFrame) -> pd.DataFrame | None:
    """Matriu facultatiu × màquina (amb columna Total, ordenada desc) a
    partir de files de màquina ja filtrades (ordinàries o peonades).
    Inclou el comodí (fallback). Retorna None si no hi ha cap fila."""
    if rows.empty:
        return None
    profs = sorted(set(rows["professional"]) - {"", "NONE", "NAN"})
    tbl = (
        pd.crosstab(rows["professional"], rows["slot_id"])
        .reindex(profs, fill_value=0)
        .astype(int)
    )
    tbl["Total"] = tbl.sum(axis=1)
    return (
        tbl.sort_values("Total", ascending=False)
        .reset_index()
        .rename(columns={"professional": "Facultatiu"})
    )


def _secondary_slot_ids() -> set[str]:
    """Slot_ids que són la màquina SECUNDÀRIA (vinculada) d'un parell —el
    valor de `linked_to`. Prefereix els templates setmanals; si no, cau al
    catàleg (legacy). En majúscules."""
    tp = Path("data/weekday/weekly_slot_templates.csv")
    if tp.exists() and tp.stat().st_size > 0:
        try:
            t = pd.read_csv(tp)
            if "linked_to" in t.columns:
                vals = t["linked_to"].fillna("").astype(str).str.strip().str.upper()
                out = set(vals) - {"", "NAN", "NONE"}
                if out:
                    return out
        except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
            pass
    try:
        from src.services.slot_catalog import slot_secondary_ids
        return slot_secondary_ids(pd.read_csv("data/slot_catalog.csv"))
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return set()


def _render_machine_table(
    rows: pd.DataFrame, empty_msg: str, *, highlight_red: bool = False,
    caption: str | None = None, secondary_ids: set[str] | None = None,
) -> None:
    """Renderitza una matriu facultatiu × màquina. Si `highlight_red`,
    marca en vermell i negreta les cel·les de màquina amb 4 assignacions
    o més (no «Facultatiu» ni «Total»). Si es passa `secondary_ids`,
    afegeix « (secundària)» a la capçalera de les màquines vinculades."""
    tbl = _machine_crosstab_table(rows)
    if tbl is None:
        st.info(empty_msg)
        return
    if secondary_ids:
        rename = {
            c: f"{c} (secundària)"
            for c in tbl.columns
            if c not in ("Facultatiu", "Total") and c in secondary_ids
        }
        if rename:
            tbl = tbl.rename(columns=rename)
    obj = tbl
    if highlight_red:
        cols = [c for c in tbl.columns if c not in ("Facultatiu", "Total")]
        obj = tbl.style.map(
            lambda v: "color: red; font-weight: bold" if v >= 4 else "",
            subset=cols,
        )
    st.dataframe(
        obj, width="stretch", hide_index=True, height=38 + 35 * (len(tbl) + 1),
    )
    if caption:
        st.caption(caption)


def render_weekday_metrics(
    year: int,
    month: int,
    scope_start_month: int,
    scope_end_month: int,
    selected_months: list[int],
    public_holidays_path: Path,
    base_calendar_overrides_path: Path,
    base_calendar_path: Path,
    session_dir: Path,
    save_generated_session_folder,
    pdf_output_dir: Path,
    professionals_path: Path,
) -> None:
    """Vista de mètriques (càrrega per facultatiu, revisions, etc.). Llegeix
    preferentment el calendari DEFINITIU (`schedule_weekday_final.csv`);
    si no existeix, l'inicial (`schedule_weekday.csv`)."""
    final_path = Path("outputs/schedule_weekday_final.csv")
    initial_path = Path("outputs/schedule_weekday.csv")
    schedule_path = final_path if (
        final_path.exists() and final_path.stat().st_size > 0
    ) else initial_path
    if not (schedule_path.exists() and schedule_path.stat().st_size > 0):
        st.info(
            "Encara no hi ha cap calendari generat. Ves a «Calendari "
            "inicial» i prem **Generar**."
        )
        return

    fallback_ids = _fallback_ids()
    m = _scoped_machine_rows(year, selected_months)

    if schedule_path == final_path:
        st.caption("Mètriques del **calendari definitiu**.")
    else:
        st.caption(
            "Mètriques del **calendari inicial** (no s'ha regenerat encara)."
        )

    st.divider()

    with st.expander("Comptadors per facultatiu (PRES / NP_ord / Peonades)"):
        from src.ui.target_breakdown import render_target_breakdown_per_prof
        render_target_breakdown_per_prof(year=year, months=selected_months)

    with st.expander(
        "📊 Acumulat entre mesos (el que el solver arrossega al mes següent)"
    ):
        _render_accumulated_metrics(year, selected_months, fallback_ids, m)

    # Màquines ORDINÀRIES (work_mode != PEONADA), separades per
    # presencialitat, i PEONADES a part.
    _ord_rows = m[m["work_mode"] != "PEONADA"] if not m.empty else m
    _pres_rows = (
        _ord_rows[_ord_rows["presentiality"] == "PRESENCIAL"]
        if not _ord_rows.empty else _ord_rows
    )
    _np_rows = (
        _ord_rows[_ord_rows["presentiality"] == "NO_PRESENCIAL"]
        if not _ord_rows.empty else _ord_rows
    )
    _peo_rows = m[m["work_mode"] == "PEONADA"] if not m.empty else m

    with st.expander("Màquines presencials ordinàries per facultatiu"):
        _render_machine_table(
            _pres_rows,
            "No hi ha màquines presencials ordinàries a l'àmbit seleccionat.",
            highlight_red=True,
            caption="En vermell: màquines amb 4 assignacions o més.",
        )

    with st.expander("Màquines no presencials ordinàries per facultatiu"):
        _render_machine_table(
            _np_rows,
            "No hi ha màquines no presencials ordinàries a l'àmbit seleccionat.",
            highlight_red=True,
            caption="En vermell: màquines amb 4 assignacions o més.",
            secondary_ids=_secondary_slot_ids(),
        )

    with st.expander("Màquines de peonada per facultatiu"):
        _render_machine_table(
            _peo_rows, "No hi ha peonades assignades a l'àmbit seleccionat.",
        )

    with st.expander("Revisions per facultatiu"):
        rev = _scoped_review_rows(year, selected_months)
        if rev.empty:
            st.info("No hi ha revisions assignades a l'àmbit seleccionat.")
        else:
            # Mostra TOTS els facultatius que treballen a l'àmbit (0 si no fan
            # cap revisió), no només els que en tenen assignada alguna; així es
            # veu qui en fa 0. (Exclou el comodí, que mai cobreix revisions.)
            _working = sorted(
                (set(m["professional"]) | set(rev["professional"]))
                - {str(f).strip().upper() for f in fallback_ids}
                - {"", "NONE", "NAN"}
            )
            tbl = (
                pd.crosstab(rev["professional"], rev["slot_id"])
                .reindex(_working, fill_value=0)
                .astype(int)
            )
            tbl["Total"] = tbl.sum(axis=1)
            tbl = (
                tbl.sort_values("Total", ascending=False)
                .reset_index()
                .rename(columns={"professional": "Facultatiu"})
            )
            st.dataframe(
                tbl, width="stretch", hide_index=True,
                height=38 + 35 * (len(tbl) + 1),
            )
