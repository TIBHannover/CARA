"""Annotation tab, top: start the study (assign the study queries)."""

import streamlit as st

import styles
from client import ApiError, CaraClient, Study
from components import tours
from components.feedback import count, notify
from components.study import tabs
from state import forget_study


def render(api: CaraClient, study: Study) -> None:
    """Draw the Start annotation card: who judges the study queries, and how many per query."""
    overview = study.overview
    assert overview is not None  # admins only
    settings = study.settings

    tours.show("study-page")
    started = overview.stage in ("annotation", "done")
    st.markdown(
        "Annotation covers every query that is not a pilot query: "
        f"**{count(overview.annotation_queries, 'query')}**. Starting assigns them to the annotators below. "
        "The first judgment fixes the pools and the grouping."
    )

    annotators = [m.username for m in api.members(study.id) if m.role == "annotator"]
    with styles.section("study-start", "Start annotation"):
        if not annotators:
            st.warning(
                "The study has no annotators yet. Add them in the study settings (⚙ above).",
                icon=":material/group_add:",
            )
            return
        if not started and overview.pilot_judged < overview.pilot_queries:
            st.warning(
                f"The pilot is not finished: {overview.pilot_judged} of "
                f"{count(overview.pilot_queries, 'query')} judged. The simulator compares settings on its "
                "labels.",
                icon=":material/science:",
            )
        if started:
            st.markdown(
                f"**Annotation has started**: {overview.annotation_complete} of "
                f"{overview.annotation_assignments} assigned queries judged. Assigning again moves queries "
                "between annotators; judgments stay with whoever made them."
            )
        with st.form("study", border=False):
            chosen = st.multiselect("Annotators", annotators, default=annotators)
            per_query = st.number_input(
                "Annotators per query",
                1,
                len(annotators),
                min(settings.annotators_per_query, len(annotators)),
                help="Two or more give agreement figures and consensus labels.",
            )
            label = "Assign again" if started else "Start annotation"
            if st.form_submit_button(label, type="primary", icon=":material/play_arrow:"):
                try:
                    counts = api.assign(study.id, int(per_query), chosen)
                    notify(
                        "Assigned: " + ", ".join(f"{name} {n}" for name, n in counts.items()),
                        ":material/task:",
                    )
                    forget_study()
                    st.rerun()
                except ApiError as error:
                    st.error(str(error))

    if started:
        tabs.link("Progress", "Next: track progress")
