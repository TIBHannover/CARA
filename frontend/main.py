"""The entry point (`streamlit run main.py`): login, the Studies page, and the navigation to the other
pages."""

import streamlit as st

import styles
from client import ApiError, AuthError, CaraClient, QueueItem, Study
from components.feedback import count
from components.study.tabs import KEY as TAB_KEY
from components.study.tabs import first_tab
from state import API_URL, client, remember, thumbnails, write_cookies

st.set_page_config(page_title="CARA", page_icon="assets/favicon.svg", layout="wide")
st.logo("assets/logo.svg", size="large", icon_image="assets/icon.svg")
styles.base()
for key, default in {
    "token": None,
    "username": None,
    "is_superuser": False,
    "study_id": None,
    "study_role": None,
}.items():
    st.session_state.setdefault(key, default)


def login() -> None:
    """Draw the login form; on success, keep the token in the session and a browser cookie."""
    _, middle, _ = st.columns([1, 1, 1])
    with middle, styles.card("login"):
        st.image("assets/logo.svg", width=240)
        st.markdown("#### Cluster-Assisted Relevance Assessment")
        st.caption("A relevance assessment tool to judge image retrieval pools cluster by cluster")
        with st.form("login", border=False):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")
        if submitted:
            try:
                st.session_state.token = client().login(username, password)
                st.session_state.username = username
                st.session_state.is_superuser = client().me().is_superuser
                remember(cara_token=st.session_state.token)
                st.rerun()
            except (AuthError, ApiError):
                st.error("Invalid username or password.")


def logout() -> None:
    """Forget the login and the open study, here and in the browser's cookies."""
    for key in ("token", "username", "study_id", "study_role"):
        st.session_state[key] = None
    st.session_state.is_superuser = False
    st.session_state.logged_out = True  # the cookies this session started with must not log back in
    remember(cara_token=None, cara_study=None)
    st.rerun()


def restore_session() -> None:
    """After a reload (a new session), log back in from the browser's cookie and reopen the study."""
    if st.session_state.token is not None or st.session_state.get("logged_out"):
        return
    token = st.context.cookies.get("cara_token")
    if not token:
        return
    try:
        me = CaraClient(API_URL, token).me()
    except (AuthError, ApiError):  # expired or revoked
        remember(cara_token=None, cara_study=None)
        return
    st.session_state.token, st.session_state.username = token, me.username
    st.session_state.is_superuser = me.is_superuser
    study_id = st.context.cookies.get("cara_study", "")
    if study_id.isdigit():
        try:
            study = client().study(int(study_id))
        except ApiError:
            return
        st.session_state.study_id, st.session_state.study_role = study.id, study.role


def open_study(study: Study) -> None:
    """Open a study: the admin tabs, the adjudicate page or the judge page, by the person's role."""
    st.session_state.study_id = study.id
    remember(cara_study=str(study.id))
    st.session_state.study_role = study.role
    if study.role == "admin":
        st.session_state[TAB_KEY] = first_tab(study)
        st.switch_page(study_page)
    st.switch_page(adjudicate_page if study.role == "adjudicator" else judge_page)


def admin_summary(study: Study) -> None:
    """Draw how far a study's pilot and annotation are, for its admin."""
    overview = study.overview
    if overview is None:
        return
    if overview.pilot_queries:
        st.caption(f"Pilot: {overview.pilot_judged} of {count(overview.pilot_queries, 'query')} judged")
    if overview.annotation_assignments:
        st.progress(
            overview.annotation_complete / overview.annotation_assignments,
            text=f"Annotation: {overview.annotation_complete} of "
            f"{count(overview.annotation_assignments, 'assigned query')} judged",
        )
    else:
        st.caption(f"Annotation: {count(overview.annotation_queries, 'query')}, not started")


def annotator_summary(queue: list[QueueItem]) -> None:
    """Draw how much of their queue an annotator has judged."""
    if not queue:
        st.caption("No queries assigned to you.")
        return
    done = sum(item.judged == item.pool_size for item in queue)
    images = sum(item.judged for item in queue)
    total = sum(item.pool_size for item in queue)
    st.progress(images / total, text=f"{done} of {len(queue)} queries judged")
    st.caption(f"{images:,} of {total:,} images")


def study_card(study: Study) -> None:
    """Draw a study's card: cover images, stage and kind badges, progress, and the button that opens it."""
    with styles.card(f"study-{study.id}"):
        if study.cover_image_ids:
            ids = tuple(study.cover_image_ids)
            tiles = thumbnails(st.session_state.token, study.id, ids, 160, True)
            with st.container(key=f"cover-{study.id}"):
                for image_id in ids:
                    st.image(tiles[image_id], width="stretch")
        st.markdown(f"**{study.name}**")
        with st.container(horizontal=True, gap="small"):
            if study.overview is not None:
                label, colour, icon = styles.STAGES[study.overview.stage]
                st.badge(label, icon=icon, color=colour)
            if study.query_kind:
                st.badge(f"{study.query_kind} queries", icon=":material/search:", color="violet")
            st.badge(study.dataset, icon=":material/dataset:", color="gray")
        if study.role == "admin":
            admin_summary(study)
        elif study.role == "adjudicator":
            st.caption("You set the final labels.")
        else:
            annotator_summary(client().queue(study.id))
        st.button(
            {"admin": "Open", "adjudicator": "Adjudicate"}.get(study.role, "Judge"),
            key=f"open:{study.id}",
            icon=":material/arrow_forward:",
            type="primary",
            width="stretch",
            on_click=open_study,
            args=(study,),
        )


def new_study_card() -> None:
    """Draw the New study card (superusers), built like a study card with a plus where the covers go."""
    with styles.card("new-study"):
        with st.container(key="new-cover", horizontal_alignment="center", vertical_alignment="center"):
            st.markdown(":material/add_circle:")
        st.markdown("**New study**")
        st.caption("A dataset's queries, the pools to judge, and who judges them.")
        st.button(
            "Create",
            key="new-study-button",
            icon=":material/arrow_forward:",
            type="primary",
            width="stretch",
            on_click=st.switch_page,
            args=(new_study_page,),
        )


def studies() -> None:
    """Draw the Studies page: the study cards, with New study for superusers."""
    every = client().studies()
    datasets = client().datasets() if st.session_state.is_superuser else None
    st.title("Studies")
    if datasets == []:
        st.info(
            "No dataset yet. Datasets are added on the command line: `cara dataset-add /data/<folder>` "
            "(README, *Your own data*).",
            icon=":material/dataset:",
        )
    elif not every and datasets is None:
        st.info("You are not part of any study yet. Ask an admin to add you.")
    names = sorted({study.dataset for study in every})
    shown = every
    if len(names) > 1:
        picked = st.selectbox("Dataset", ["All datasets", *names], width=320)
        shown = [study for study in every if picked in ("All datasets", study.dataset)]
    # Demo studies (e.g. the toy shapes) after the others.
    shown = sorted(shown, key=lambda study: study.settings.demo)
    can_create = bool(datasets) and any(d.sets for d in datasets or [])
    with st.container(key="studies-grid"):
        if can_create:
            new_study_card()
        for study in shown:
            study_card(study)


# Studies are opened from their cards, so only the Studies page is in the top bar.
judge_page = st.Page(
    "app_pages/judge.py", title="Judge", icon=":material/photo_library:", visibility="hidden"
)
new_study_page = st.Page(
    "app_pages/new_study.py", title="New study", icon=":material/add_circle:", visibility="hidden"
)
adjudicate_page = st.Page(
    "app_pages/adjudicate.py", title="Adjudicate", icon=":material/gavel:", visibility="hidden"
)
study_page = st.Page(
    "app_pages/study.py", title="Study", icon=":material/science:", url_path="study", visibility="hidden"
)

restore_session()
write_cookies()
if st.session_state.token is None:
    navigation = st.navigation([st.Page(login, title="Log in", icon=":material/login:")], position="hidden")
else:
    main = [st.Page(studies, title="Studies", icon=":material/folder:", default=True)]
    if st.session_state.is_superuser:
        main.append(new_study_page)
    sections = {"": main}
    if st.session_state.study_id is not None:
        # Admins manage, adjudicators set final labels, annotators judge; two roles need two accounts.
        role = st.session_state.study_role
        main.append({"admin": study_page, "adjudicator": adjudicate_page}.get(role, judge_page))
    sections[st.session_state.username or "Account"] = [
        st.Page(logout, title="Log out", icon=":material/logout:")
    ]
    navigation = st.navigation(sections, position="top")

try:
    navigation.run()
except AuthError:
    logout()
