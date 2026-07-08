import streamlit as st


def apply_global_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --planner-font-size: 0.84rem;
        }

        .stApp {
            font-size: var(--planner-font-size);
        }

        /* Amagar la barra d'eines de Streamlit (botó Deploy + menú) i fer
           transparent la franja blanca de dalt per recuperar espai. Es manté
           el botó de plegar/desplegar la barra lateral. */
        [data-testid="stAppDeployButton"],
        [data-testid="stMainMenu"] {
            display: none !important;
        }

        [data-testid="stHeader"] {
            background: transparent !important;
            height: 0 !important;
        }

        .planner-title {
            display: block !important;
            position: relative;
            z-index: 1;
            color: #2f3342;
            font-size: 1.08rem;
            font-weight: 700;
            line-height: 1.08;
            margin: 0 0 0.9rem 0;
        }

        .session-title {
            color: #2f3342;
            font-size: 1.12rem;
            font-weight: 700;
            line-height: 1.12;
            margin: 0 0 0.35rem 0;
        }

        .block-container {
            max-width: 100% !important;
            padding-top: 1.6rem !important;
            padding-bottom: 0.75rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }

        [data-testid="stSidebar"][aria-expanded="true"] {
            min-width: 16.5rem !important;
            max-width: 16.5rem !important;
        }

        [data-testid="stSidebar"] .block-container {
            padding-top: 4.2rem !important;
            padding-left: 0.85rem !important;
            padding-right: 0.85rem !important;
        }

        h1 {
            font-size: 1.35rem !important;
            line-height: 1.1 !important;
            margin-top: 0 !important;
            margin-bottom: 0.15rem !important;
        }

        h2 {
            font-size: 1rem !important;
            line-height: 1.2 !important;
            margin-top: 0.25rem !important;
            margin-bottom: 0.2rem !important;
        }

        h3 {
            font-size: 0.94rem !important;
            margin-top: 0.35rem !important;
            margin-bottom: 0.25rem !important;
        }

        p, label, .stMarkdown, .stCaption, [data-testid="stMarkdownContainer"] {
            font-size: var(--planner-font-size) !important;
            line-height: 1.28 !important;
        }

        div[data-testid="stVerticalBlock"] {
            gap: 0.2rem !important;
        }

        div[data-testid="stHorizontalBlock"] {
            gap: 0.36rem !important;
        }

        div[data-testid="stTabs"] button {
            padding: 0.2rem 0.42rem !important;
            min-height: 1.58rem !important;
            font-size: 0.82rem !important;
        }

        div[data-testid="stTabs"] [role="tablist"] {
            gap: 0.18rem !important;
            margin-bottom: 0.2rem !important;
        }

        .stButton > button,
        [data-testid="stDownloadButton"] button {
            min-height: 1.86rem !important;
            padding: 0.22rem 0.55rem !important;
            font-size: 0.8rem !important;
            border-radius: 0.35rem !important;
        }

        /* Franges (fixes i canvis puntuals): cada franja (Matí/Tarda/Nit) amb
           el seu to de gris per agrupar visualment els slots del mateix grup. */
        [class*="st-key-franjabox_MATI_"] {
            background: #f4f5f7 !important;
            border-radius: 6px !important;
            padding: 3px 5px !important;
            margin-bottom: 4px !important;
        }
        [class*="st-key-franjabox_TARDA_"] {
            background: #e9ecf0 !important;
            border-radius: 6px !important;
            padding: 3px 5px !important;
            margin-bottom: 4px !important;
        }
        [class*="st-key-franjabox_NIT_"] {
            background: #dde1e7 !important;
            border-radius: 6px !important;
            padding: 3px 5px !important;
            margin-bottom: 4px !important;
        }

        [data-testid="stRadio"] {
            margin-bottom: 0.35rem !important;
        }

        [data-testid="stRadio"] label {
            font-weight: 500 !important;
        }

        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input,
        [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            min-height: 1.72rem !important;
            font-size: 0.8rem !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            padding: 0.32rem 0.48rem !important;
        }

        [data-testid="stFileUploader"] section {
            padding: 0.55rem !important;
            min-height: 3.2rem !important;
        }

        [data-testid="stExpander"] details {
            margin-top: 0.25rem !important;
            margin-bottom: 0.25rem !important;
        }

        [data-testid="stExpander"] summary {
            padding: 0.35rem 0.55rem !important;
            font-size: 0.8rem !important;
        }

        [data-testid="stDataFrame"],
        [data-testid="stDataEditor"] {
            font-size: 0.8rem !important;
        }

        [data-testid="stDataFrame"] [role="gridcell"],
        [data-testid="stDataEditor"] [role="gridcell"],
        [data-testid="stDataFrame"] [role="columnheader"],
        [data-testid="stDataEditor"] [role="columnheader"] {
            padding-top: 0.18rem !important;
            padding-bottom: 0.18rem !important;
            font-size: 0.8rem !important;
        }

        div[data-testid="stAlert"] {
            padding: 0.35rem 0.6rem !important;
            margin: 0.2rem 0 !important;
        }

        hr {
            margin: 0.9rem 0 !important;
        }

        .slot-month {
            margin-bottom: 0.35rem;
        }

        .slot-month-title {
            color: #2f3342;
            font-weight: 700;
            font-size: 0.92rem;
            margin: 0.2rem 0 0.35rem 0;
        }

        table.slot-calendar {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 0.72rem;
        }

        table.slot-calendar th,
        table.slot-calendar td {
            border: 1px solid #e5e7eb;
            vertical-align: top;
        }

        table.slot-calendar th {
            background: #f6f7f9;
            color: #6b7280;
            font-weight: 600;
            padding: 0.28rem;
            text-align: left;
        }

        table.slot-calendar td {
            height: 5.1rem;
            padding: 0.24rem;
            background: white;
        }

        table.slot-calendar td.empty {
            background: #fafafa;
        }

        table.slot-calendar td.non-working {
            background: #f1f3f5;
            color: #8a9099;
        }

        .slot-day-number {
            font-weight: 700;
            color: #2f3342;
            margin-bottom: 0.18rem;
        }

        .slot-day-label {
            color: #8a9099;
            font-size: 0.66rem;
            margin-bottom: 0.15rem;
        }

        .slot-line {
            border-left: 2px solid #ff4b4b;
            padding-left: 0.22rem;
            margin-top: 0.14rem;
            line-height: 1.15;
            overflow-wrap: anywhere;
        }

        .slot-line-muted {
            color: #6b7280;
        }

        .schedule-calendar {
            margin-top: 0.35rem;
        }

        .schedule-calendar-title {
            color: #2f3342;
            font-weight: 700;
            font-size: 0.95rem;
            margin: 0.2rem 0 0.35rem 0;
        }

        .schedule-calendar-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem 0.8rem;
            align-items: center;
            color: #6b7280;
            font-size: 0.68rem;
            margin-bottom: 0.45rem;
        }

        .schedule-calendar-legend-item {
            display: inline-flex;
            align-items: center;
            gap: 0.22rem;
            white-space: nowrap;
        }

        .schedule-calendar-swatch {
            width: 0.78rem;
            height: 0.78rem;
            border: 1px solid #cbd5e1;
            border-radius: 0.12rem;
            display: inline-block;
        }

        .schedule-calendar-week {
            display: grid;
            gap: 0.28rem;
            margin-bottom: 0.28rem;
        }

        .schedule-day-card {
            border: 1px solid #cbd5e1;
            background: #ffffff;
            border-radius: 0.35rem;
            min-width: 0;
            overflow: hidden;
        }

        .schedule-day-card.non-working {
            background: #f8fafc;
        }

        .schedule-day-card.empty {
            background: #f8fafc;
            border-style: dashed;
            min-height: 2.6rem;
        }

        .schedule-day-header {
            background: #e2e8f0;
            color: #2f3342;
            font-weight: 700;
            font-size: 0.72rem;
            padding: 0.14rem 0.32rem;
            border-bottom: 1px solid #cbd5e1;
        }

        .schedule-day-status {
            color: #6b7280;
            font-size: 0.62rem;
            font-weight: 500;
            margin-left: 0.15rem;
        }

        .schedule-day-body {
            padding: 0.2rem;
        }

        .schedule-franja-block {
            margin-bottom: 0.28rem;
            padding-bottom: 0.24rem;
            border-bottom: 2px solid #94a3b8;
        }

        .schedule-franja-block:last-child {
            margin-bottom: 0;
            padding-bottom: 0;
            border-bottom: none;
        }

        .schedule-franja-title {
            background: #475569;
            color: #ffffff;
            font-weight: 700;
            font-size: 0.64rem;
            padding: 0.1rem 0.32rem;
            margin-bottom: 0.16rem;
            border-radius: 0.22rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .schedule-area-block {
            margin-bottom: 0.18rem;
        }

        .schedule-area-block:last-child {
            margin-bottom: 0;
        }

        .schedule-area-title {
            color: #1f2937;
            border: 1px solid #94a3b8;
            border-radius: 0.25rem 0.25rem 0 0;
            font-size: 0.62rem;
            font-weight: 800;
            padding: 0.12rem 0.26rem;
            line-height: 1.15;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        /* Paleta genèrica per àrea (qualsevol àrea de l'usuari). Mateixos
           colors i ordre que _AREA_PDF_PALETTE perquè app i PDF coincideixin. */
        .schedule-area-c1 { background: #dbeafe; }
        .schedule-area-c2 { background: #dcfce7; }
        .schedule-area-c3 { background: #ede9fe; }
        .schedule-area-c4 { background: #fef3c7; }
        .schedule-area-c5 { background: #fce7f3; }
        .schedule-area-c6 { background: #ccfbf1; }

        .schedule-area-other {
            background: #f8fafc;
        }

        .schedule-chip-list {
            display: grid;
            gap: 0.08rem;
            border-left: 1px solid #94a3b8;
            border-right: 1px solid #94a3b8;
            border-bottom: 1px solid #94a3b8;
            border-radius: 0 0 0.25rem 0.25rem;
            padding: 0.1rem;
            background: #ffffff;
        }

        .schedule-assignment-chip {
            border: 1px solid #cbd5e1;
            border-radius: 0.22rem;
            padding: 0.06rem 0.16rem;
            color: #2f3342;
            font-size: 0.62rem;
            line-height: 1.05;
            overflow-wrap: anywhere;
        }

        .schedule-assignment-chip.urgent {
            background: #bfd7f2;
        }

        .schedule-assignment-chip.presencial {
            background: #cfe8d5;
        }

        .schedule-assignment-chip.peonada {
            background: #fee2e2;
            border-color: #dc2626;
            color: #b91c1c;
            font-weight: 700;
        }

        .schedule-assignment-chip.tld {
            background: #fef3c7;
            border-color: #d97706;
            color: #b45309;
            font-weight: 700;
        }

        .schedule-assignment-chip.default {
            background: #ffffff;
        }

        .schedule-machine {
            font-weight: 700;
        }

        .schedule-empty-note {
            color: #8a9099;
            font-size: 0.66rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
