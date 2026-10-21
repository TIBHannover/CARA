"""A study's admin page: one tab per step, from the pilot to the results."""

import streamlit as st

from components.feedback import show_toasts
from components.study import (
    agreement,
    exports,
    guidelines,
    header,
    pilot,
    pilot_results,
    progress,
    settings,
    simulation,
    start,
)
from components.study.tabs import KEY, TABS, first_tab
from state import client, current_study

api = client()
study = current_study()

show_toasts()
header.render(api, study)
tab = st.segmented_control(
    "Tab",
    TABS,
    default=first_tab(study),
    key=KEY,
    required=True,
    bind="query-params",
    label_visibility="collapsed",
    width="stretch",
)
if tab in ("Pilot", "Pilot results"):
    st.caption("Optional, recommended: a pilot shows how annotators judge before the grouping is fixed.")
match tab:
    case "Pilot":
        pilot.render(api, study)
    case "Pilot results":
        pilot_results.render(api, study)
    case "Guidelines":
        guidelines.render(api, study)
    case "Simulation":
        simulation.render(api, study)
    case "Annotation":
        start.render(api, study)
        settings.render(api, study)
    case "Progress":
        progress.render(api, study)
    case "Results":
        agreement.render(api, study)
        exports.render(api, study)
