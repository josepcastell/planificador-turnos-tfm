import streamlit as st


WORKFLOW_KEYS = [
    "step_public_holidays",
    "step_base_calendar",
    "step_details_confirmed",
    "step_module_calendars",
    "step_operational_constraints",
    "step_planning",
    "step_pdfs",
    "step_metrics",
]


def init_workflow_state() -> None:
    for key in WORKFLOW_KEYS:
        st.session_state.setdefault(key, False)


def set_workflow_state(value: bool) -> None:
    for key in WORKFLOW_KEYS:
        st.session_state[key] = value


def invalidate_after_work_slot_change() -> None:
    for key in [
        "step_base_calendar",
        "step_module_calendars",
        "step_operational_constraints",
        "step_planning",
        "step_pdfs",
        "step_metrics",
    ]:
        st.session_state[key] = False


def invalidate_after_particularities() -> None:
    for key in [
        "step_details_confirmed",
        "step_module_calendars",
        "step_operational_constraints",
        "step_planning",
        "step_pdfs",
        "step_metrics",
    ]:
        st.session_state[key] = False
