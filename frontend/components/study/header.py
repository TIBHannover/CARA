"""The study page's header: its name and a settings button with the study's general settings, people and,
for superusers, deleting the study."""

import streamlit as st

import styles
from client import ApiError, CaraClient, Settings, Study
from components.study import team
from state import forget_study, remember


def general(api: CaraClient, study: Study) -> None:
    """Draw the study's general settings: name, annotators per query, query order, demo flag."""
    settings = study.settings
    with st.form("general", border=False):
        name = st.text_input("Name", settings.name)
        per_query = st.number_input("Annotators per query", 1, 20, settings.annotators_per_query)
        orders = {"shuffled": "Shuffled per annotator", "listed": "As listed in the query set"}
        query_order = st.segmented_control(
            "Query order", list(orders), format_func=orders.__getitem__, default=settings.query_order
        )
        demo = st.checkbox("Demo study", settings.demo, help="Listed after the other studies.")
        if st.form_submit_button("Save", icon=":material/save:"):
            changes = {
                "name": name,
                "annotators_per_query": int(per_query),
                "query_order": query_order or settings.query_order,
                "demo": demo,
            }
            try:
                api.update_settings(study.id, Settings.model_validate(settings.model_dump() | changes))
                forget_study()
                st.rerun()
            except ApiError as error:
                st.error(str(error))


def delete(api: CaraClient, study: Study) -> None:
    """Delete the study once its name is typed in, then go back to the Studies page."""
    st.markdown("**Delete this study**")
    st.caption(
        "Deletes every query, pool, judgment and adjudication in it. The dataset and the accounts stay."
    )
    with st.form("delete-study", border=False):
        typed = st.text_input("Type the study's name to confirm", placeholder=study.name)
        if st.form_submit_button("Delete study", icon=":material/delete:"):
            if typed.strip() != study.name:
                st.error("The name doesn't match.")
                return
            try:
                api.delete_study(study.id)
            except ApiError as error:
                st.error(str(error))
                return
            forget_study()
            st.session_state.study_id = st.session_state.study_role = None
            remember(cara_study=None)
            # Without an open study the study page leaves the navigation, which falls back to Studies.
            st.rerun()


def render(api: CaraClient, study: Study) -> None:
    """Draw the study's name, its stage, and the settings button (general settings, people, delete)."""
    with st.container(horizontal=True, vertical_alignment="center"):
        st.title(study.name, width="content")
        if study.overview is not None:
            label, colour, _ = styles.STAGES[study.overview.stage]
            st.badge(label, color=colour)
        st.space("stretch")
        with st.popover("Study settings", icon=":material/settings:"):
            general(api, study)
            st.divider()
            team.render(api, study)
            if st.session_state.is_superuser:
                st.divider()
                delete(api, study)
    kind = f"{study.query_kind} queries · " if study.query_kind else ""
    st.caption(f":material/dataset: {study.dataset} · {kind}{study.settings.encoder or 'no encoder'}")
