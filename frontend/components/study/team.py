"""Study settings: the people in the study, and new accounts."""

import streamlit as st

import styles
from client import ApiError, CaraClient, Study


def render(api: CaraClient, study: Study) -> None:
    """Draw the study's members, adding someone, and (for superusers) creating an account."""
    me = api.me()

    members = api.members(study.id)
    st.dataframe(
        [{"user": m.username, "role": m.role, "assigned queries": m.assigned} for m in members],
        hide_index=True,
    )

    st.caption(
        "Admins manage, annotators judge, and adjudicators set the final labels where annotators disagree or "
        "are unsure. Someone with two roles needs two accounts."
    )

    with styles.card("member"):
        st.markdown("**Add someone to this study**")
        with st.form("member", border=False):
            with st.container(horizontal=True, vertical_alignment="bottom"):
                username = st.text_input("Username")
                role = st.segmented_control(
                    "Role", ["annotator", "adjudicator", "admin"], default="annotator"
                )
                add = st.form_submit_button("Add", icon=":material/person_add:")
            if add:
                try:
                    api.set_member(study.id, username, role or "annotator")
                    st.rerun()
                except ApiError as error:
                    st.error(str(error))

    if me.is_superuser:
        with styles.card("account"):
            st.markdown("**Create an account**")
            with st.form("account", border=False, clear_on_submit=True):
                with st.container(horizontal=True, vertical_alignment="bottom"):
                    new_user = st.text_input("Username", key="new_user")
                    password = st.text_input("Password", type="password")
                    create = st.form_submit_button("Create", icon=":material/badge:")
                if create:
                    try:
                        api.create_user(new_user, password)
                        st.success(f"Created {new_user}. Add them to the study above.")
                    except ApiError as error:
                        st.error(str(error))
