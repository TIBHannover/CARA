"""The Simulation tab: compare grouping settings on the study's own queries."""

import streamlit as st

from client import CaraClient, Study
from components import tours
from components.simulator import results
from components.simulator.annotators import simulated_annotators
from components.simulator.choose import choose
from components.simulator.ground_truth import ground_truth
from components.simulator.methods import candidate_settings
from components.simulator.run import SimulationRun, summary_and_run


def render(api: CaraClient, study: Study) -> None:
    """Draw the Simulation tab: the six steps, or why it needs an encoder."""
    if study.settings.encoder is None:
        st.info(
            "The simulator compares ways of grouping, so it needs an encoder; this study judges every "
            "image on "
            "its own.",
            icon=":material/info:",
        )
        return
    scope = api.simulator_scope(study.id)
    result_key = f"simulation:{study.id}"

    st.markdown(
        "Find the grouping that saves the most time without losing relevant images: simulated annotators "
        "judge a sample of this study's queries under each setting."
    )
    tours.show("simulator")  # drawn before the page can stop early

    ground = ground_truth(api, study, scope)
    annotators = simulated_annotators(api.pilot_report(study.id).annotators)
    candidates = candidate_settings(study)
    summary_and_run(api, study.id, scope, ground, candidates, annotators, result_key)

    result = st.session_state.get(result_key)
    if not isinstance(result, SimulationRun):
        return
    profile = results.show(result, scope.images)
    choose(api, study, result.event.results or [], profile)
