"""The Pilot tab: choose the pilot queries and who judges them."""

import streamlit as st

import styles
from client import ApiError, CaraClient, Study
from components import tours
from components.feedback import count, notify
from components.study import tabs
from state import forget_study


def render(api: CaraClient, study: Study) -> None:
    """Draw the Pilot tab: choose the pilot queries and who judges them, then follow their progress."""
    overview = study.overview
    assert overview is not None  # admins only

    tours.show("pilot-page")
    st.markdown(
        "A few queries that annotators judge image by image, before the grouping is fixed. Their labels feed "
        "the simulation and count as judged. Annotators see only these queries until annotation starts."
    )

    annotators = [m.username for m in api.members(study.id) if m.role == "annotator"]
    total = overview.pilot_queries + overview.annotation_queries
    started = overview.stage in ("annotation", "done")

    with styles.section("pilot-setup", "Pilot queries and annotators"):
        if overview.pilot_queries:
            st.markdown(
                f"**{count(overview.pilot_queries, 'pilot query')}**, {overview.pilot_judged} fully judged. "
                f"The study has the other {overview.annotation_queries}."
            )
        if not annotators:
            st.warning(
                "The study has no annotators yet. Add them in the study settings (⚙ above).",
                icon=":material/group_add:",
            )
            return
        with st.form("pilot", border=False):
            keep = False
            if overview.pilot_queries:
                keep = st.toggle(
                    "Keep these pilot queries",
                    True,
                    help="Off: draw new ones at random. Not possible once pilot images are judged.",
                )
            with st.container(horizontal=True):
                how_many = st.number_input(
                    "Number of pilot queries",
                    1,
                    max(1, total - 1),
                    overview.pilot_queries or min(5, max(1, total - 1)),
                    disabled=started,
                )
                per_query = st.number_input(
                    "Annotators per pilot query",
                    1,
                    len(annotators),
                    min(2, len(annotators)),
                    help="Two or more show how far annotators agree; one is fastest.",
                )
            chosen = st.multiselect("Pilot annotators", annotators, default=annotators)
            label = "Assign again" if overview.pilot_queries else "Start the pilot"
            if st.form_submit_button(label, type="primary", icon=":material/science:", disabled=started):
                try:
                    result = api.set_pilot(study.id, None if keep else int(how_many), chosen, int(per_query))
                    assigned = ", ".join(f"{name} {n}" for name, n in result.assigned.items())
                    notify(
                        f"{count(len(result.queries), 'pilot query')}, assigned: {assigned}.",
                        ":material/science:",
                    )
                    forget_study()
                    st.rerun()
                except ApiError as error:
                    st.error(str(error))
        if started:
            st.caption("The study has started, so the pilot stays as it is.")

    if overview.pilot_queries and not started:
        rows = [row for row in api.progress(study.id) if row.role == "annotator" and row.queries]
        if rows:
            with styles.section("pilot-progress", "Pilot progress"):
                st.dataframe(
                    [
                        {
                            "annotator": row.username,
                            "complete": row.complete / row.queries,
                            "queries": f"{row.complete} of {row.queries}",
                            "judgments": row.judgments,
                        }
                        for row in rows
                    ],
                    hide_index=True,
                    column_config={
                        "complete": st.column_config.ProgressColumn(
                            format="percent", min_value=0, max_value=1
                        )
                    },
                )
        if overview.pilot_judged:
            tabs.link("Simulation", "Next: compare settings in the simulation")
