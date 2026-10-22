"""Results tab: the qrels, training pairs and action log."""

import streamlit as st

import styles
from client import CaraClient, Study


def render(api: CaraClient, study: Study) -> None:
    """Draw the exports: consensus qrels, one annotator's qrels, training pairs and the action log."""
    with styles.section("exports", "Exports"):
        members = api.members(study.id)
        stem = study.name.lower().replace(" ", "_")

        st.caption(
            "Files are generated when you click; qrels contain only pools every image of which is labelled."
        )

        with styles.card("consensus"):
            st.markdown(
                "**Consensus qrels**: the adjudicated label first, otherwise the majority label; ties stay "
                "undecided."
            )
            st.download_button(
                "Consensus qrels",
                lambda: api.export(study.id, "consensus_qrels"),
                file_name=f"{stem}.consensus.qrels",
                icon=":material/download:",
            )

        with styles.card("annotator"):
            st.markdown("**One annotator's qrels**")
            with st.container(horizontal=True, vertical_alignment="bottom"):
                annotators = [m.username for m in members if m.role == "annotator"]
                username = st.selectbox("Annotator", annotators)
                st.download_button(
                    "Qrels",
                    lambda: api.export(study.id, "qrels", username),
                    disabled=username is None,
                    file_name=f"{stem}.{username}.qrels",
                    icon=":material/download:",
                )

        with styles.card("pairs"):
            st.markdown(
                "**Training pairs**: per query, the Relevant images and the hardest Not Relevant ones "
                "(consensus, in pool rank order). **Action log**: every click, for effort analysis."
            )
            with st.container(horizontal=True):
                st.download_button(
                    "Training pairs",
                    lambda: api.export(study.id, "pairs"),
                    file_name=f"{stem}.pairs.jsonl",
                    icon=":material/download:",
                )
                st.download_button(
                    "Action log",
                    lambda: api.export(study.id, "actions"),
                    file_name=f"{stem}.actions.jsonl",
                    icon=":material/download:",
                )
