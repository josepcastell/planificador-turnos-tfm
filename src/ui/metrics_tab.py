from pathlib import Path

import pandas as pd
import streamlit as st

from src.domain.constants import GUARDS_RESERVED_SLOT_IDS, UNCOVERED_PROFESSIONAL
from src.domain.month_scope import in_logical_months
from src.domain.schedule_format import is_review_slot, slot_metric_family

# Valors de «professional» que no són cap persona (fora de les mètriques).
_NOT_PEOPLE = {"", "NONE", "NAN", UNCOVERED_PROFESSIONAL}

_SCOPED_COLS = ["day", "day_dt", "slot_id", "professional", "presentiality", "work_mode"]


# Helpers compartits (font única): base_pid a domain, fallback al servei.
from src.services.professionals_info import (  # noqa: E402
    base_pid as _base_pid,
    fallback_professional_ids as _fallback_ids,
)


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
        & ~df["professional"].isin(_NOT_PEOPLE)
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
    mask = df["slot_id"].map(is_review_slot) & ~df["professional"].isin(_NOT_PEOPLE)
    return df[mask][cols].reset_index(drop=True)


# NOTA: `_fallback_ids` és ara `professionals_info.fallback_professional_ids`
# (importat a dalt amb àlies) — mateixa semàntica, font única.


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


def _scoped_schedule_rows(year: int, metric_months: list[int]) -> pd.DataFrame:
    """Totes les files del calendari dins l'àmbit (amb revisions i SENSE
    COBRIR): els canvis en sessió si n'hi ha; si no, el calendari desat."""
    live = _live_schedule_df()
    if live is not None:
        df = live.copy()
    else:
        path = _preferred_schedule_path()
        if path is None:
            return pd.DataFrame()
        df = pd.read_csv(path)
    if not {"day", "slot_id", "professional"}.issubset(df.columns):
        return pd.DataFrame()
    day = pd.to_datetime(df["day"], errors="coerce")
    df = df[in_logical_months(day, year, metric_months)].copy()
    df["professional"] = (
        df["professional"].fillna("").astype(str).str.strip().str.upper().map(_base_pid)
    )
    return df


def _professional_names(professionals_path: Path) -> dict:
    try:
        df = pd.read_csv(professionals_path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return {}
    if not {"professional_id", "name"}.issubset(df.columns):
        return {}
    return {
        str(p).strip().upper(): ("" if pd.isna(n) else str(n).strip())
        for p, n in zip(df["professional_id"], df["name"])
    }


def _render_key_metrics(
    year: int, selected_months: list[int], fallback_ids: set[str],
    professionals_path: Path,
) -> None:
    """Quadre amb NOMÉS les mètriques clau: caselles sense cobrir, dobles
    feines i equitat a dalt; a sota, per facultatiu, presencials, no
    presencials, peonades, revisions, dobles feines i disponibilitat.
    Compta com el solver (un bloc vinculat = una feina)."""
    from src.services.key_metrics import key_metrics
    schedule = _scoped_schedule_rows(year, selected_months)
    templates_path = Path("data/weekday/weekly_slot_templates.csv")
    templates = (
        pd.read_csv(templates_path)
        if templates_path.exists() and templates_path.stat().st_size > 0
        else None
    )
    table, uncovered = key_metrics(
        schedule, templates, _slot_link_pairs(), exclude=fallback_ids,
    )
    if table.empty:
        st.info("Encara no hi ha assignacions a l'àmbit seleccionat.")
        return
    eff = _effective_capacity_by_prof(year, selected_months)
    cap = _capacity_by_prof(year, selected_months)
    table["disp"] = [
        float(eff.get(p, cap.get(p, 100.0))) for p in table["professional"]
    ]

    def _cv(col: str) -> float:
        adj = table[col] / (table["disp"].clip(lower=1.0) / 100.0)
        mean = float(adj.mean())
        return float(adj.std(ddof=0) / mean * 100.0) if mean > 0 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Sense cobrir", uncovered,
        help="Caselles que ningú no pot fer (en vermell al calendari).",
    )
    c2.metric(
        "Dobles feines", int(table["dobles_feines"].sum()),
        help="Dies en què algú fa més d'una activitat a la mateixa franja "
             "o més d'una presencial (falta de gent).",
    )
    c3.metric(
        "Equitat presencials", f"{_cv('presencials'):.0f}%",
        help="Dispersió (coeficient de variació) de les presencials segons "
             "la disponibilitat de cadascú. Com més baixa, més equitativa.",
    )
    c4.metric(
        "Equitat no presencials", f"{_cv('no_presencials'):.0f}%",
        help="El mateix per a les no presencials ordinàries.",
    )
    names = _professional_names(professionals_path)
    view = pd.DataFrame({
        "Facultatiu": table["professional"],
        "Nom": [names.get(p, "") for p in table["professional"]],
        "Presencials": table["presencials"],
        "No presencials": table["no_presencials"],
        "Peonades": table["peonades"],
        "Revisions": table["revisions"],
        "Dobles feines": table["dobles_feines"],
        "% disponib.": table["disp"].round(0).astype(int),
    })
    if not view["Nom"].astype(bool).any():
        view = view.drop(columns="Nom")
    st.dataframe(
        view, width="stretch", hide_index=True,
        height=38 + 35 * (len(view) + 1),
        column_config={
            "Presencials": st.column_config.NumberColumn(
                help="Presencials ordinàries. Un bloc vinculat compta com 1.",
            ),
            "No presencials": st.column_config.NumberColumn(
                help="No presencials ordinàries (sense peonades).",
            ),
            "% disponib.": st.column_config.NumberColumn(
                help="Disponibilitat efectiva: jornada menys absències i "
                     "postguàrdies. Es reparteix la feina segons aquest %.",
            ),
        },
    )


def _machine_crosstab_table(rows: pd.DataFrame) -> pd.DataFrame | None:
    """Matriu facultatiu × màquina (amb columna Total, ordenada desc) a
    partir de files de màquina ja filtrades (ordinàries o peonades).
    Inclou el comodí (fallback). Retorna None si no hi ha cap fila."""
    if rows.empty:
        return None
    profs = sorted(set(rows["professional"]) - _NOT_PEOPLE)
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
    """Font única: slot_catalog.secondary_slot_ids_effective (templates
    primer, catàleg com a fallback)."""
    from src.services.slot_catalog import secondary_slot_ids_effective
    return secondary_slot_ids_effective()


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
    """Vista de mètriques: a dalt, un quadre amb les clau; a sota, el detall
    per màquina i per revisió (plegat). Llegeix l'únic calendari
    (`schedule_weekday.csv`) o els canvis en sessió."""
    schedule_path = Path("outputs/schedule_weekday.csv")
    if not (schedule_path.exists() and schedule_path.stat().st_size > 0):
        st.info(
            "Encara no hi ha cap calendari generat. Ves a «Calendari» i "
            "prem **Generar**."
        )
        return

    fallback_ids = _fallback_ids()
    m = _scoped_machine_rows(year, selected_months)

    st.caption("Mètriques del calendari de l'**àmbit seleccionat**.")

    _render_key_metrics(year, selected_months, fallback_ids, professionals_path)

    st.divider()
    st.caption("**Detall** per activitat i per revisió:")

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

    with st.expander("Activitats presencials ordinàries per facultatiu"):
        _render_machine_table(
            _pres_rows,
            "No hi ha activitats presencials ordinàries a l'àmbit seleccionat.",
            highlight_red=True,
            caption="En vermell: màquines amb 4 assignacions o més.",
        )

    with st.expander("Activitats no presencials ordinàries per facultatiu"):
        _render_machine_table(
            _np_rows,
            "No hi ha activitats no presencials ordinàries a l'àmbit seleccionat.",
            highlight_red=True,
            caption="En vermell: màquines amb 4 assignacions o més.",
            secondary_ids=_secondary_slot_ids(),
        )

    with st.expander("Peonades per facultatiu"):
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
                - _NOT_PEOPLE
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
