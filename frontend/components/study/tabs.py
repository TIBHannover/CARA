"""The study page's tabs, and buttons that open one."""

import streamlit as st

from client import Study

TABS = ["Pilot", "Pilot results", "Guidelines", "Simulation", "Annotation", "Progress", "Results"]
ICONS = {
    "Pilot": ":material/science:",
    "Pilot results": ":material/insights:",
    "Guidelines": ":material/menu_book:",
    "Simulation": ":material/tune:",
    "Annotation": ":material/photo_library:",
    "Progress": ":material/monitoring:",
    "Results": ":material/task_alt:",
}
KEY = "tab"  # also the URL's query parameter


def _open(tab: str) -> None:
    st.session_state[KEY] = tab


def link(tab: str, label: str) -> None:
    """Draw a button that opens another tab of the study."""
    st.button(label, icon=ICONS[tab], type="tertiary", on_click=_open, args=(tab,), key=f"go-{tab}-{label}")


def first_tab(study: Study) -> str:
    """Return the tab a study opens on: the step it is at."""
    stage = study.overview.stage if study.overview else "new"
    if stage == "new":
        return "Pilot"
    if stage == "pilot":
        judged = study.overview.pilot_judged if study.overview else 0
        return "Simulation" if judged else "Pilot"
    return "Progress" if stage == "annotation" else "Results"
