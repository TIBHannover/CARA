"""The Progress tab: each annotator's progress."""

import streamlit as st

import styles
from client import CaraClient, Study


def render(api: CaraClient, study: Study) -> None:
    """Draw the Progress tab: totals, then each member's progress."""
    rows = api.progress(study.id)

    with st.container(horizontal=True):
        st.metric("Annotators", sum(row.role == "annotator" for row in rows), border=True)
        st.metric("Judgments", sum(row.judgments for row in rows), border=True)
        st.metric("Pools complete", sum(row.complete for row in rows), border=True)
        st.metric("Pools reviewed", sum(row.reviewed for row in rows), border=True)

    with styles.card("progress-table"):
        st.dataframe(
            [
                {
                    "annotator": row.username,
                    "role": row.role,
                    "complete": row.complete / row.queries if row.queries else 0.0,
                    "pools": f"{row.complete} of {row.queries}",
                    "reviewed": row.reviewed,
                    "judgments": row.judgments,
                    "seconds per action": row.median_seconds_per_action,
                }
                for row in rows
            ],
            hide_index=True,
            column_config={
                "complete": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "seconds per action": st.column_config.NumberColumn(
                    format="%.1f",
                    help="median time between consecutive actions; pauses over 10 minutes are left out",
                ),
            },
        )
