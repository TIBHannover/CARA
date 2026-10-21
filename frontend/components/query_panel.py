"""The judge page's left panel: the query picker, the query itself, progress, mode and view controls."""

import streamlit as st

from client import QueryView, QueueItem
from components.images import images_per_row, tint_toggle
from components.judging import Judging, collapse_key, collapsed, load, state
from components.modes import MODES, offered
from components.modes.grouped import collapse_judged, undo_split
from components.queries import browse, next_query, short_status, unfinished, upcoming
from state import thumbnails

PICKER = "query-picker"


def _picked() -> None:
    st.session_state.query_id = st.session_state[PICKER]


def render(
    ctx: Judging, queue: list[QueueItem], finished: bool, to_review: int
) -> tuple[QueryView, str, QueueItem | None]:
    """Draw the panel; return the query shown, the chosen mode and the next unfinished query."""
    settings = ctx.settings
    by_id = {item.query_id: item for item in queue}
    if st.session_state.get("query_id") not in by_id:
        st.session_state.query_id = next((item for item in queue if unfinished(ctx, item)), queue[0]).query_id
    st.session_state.setdefault("cols", settings.display.cols)

    with st.container(key="query-panel", border=True):
        st.caption(ctx.study.name)
        query_ids = list(by_id)
        st.session_state[PICKER] = st.session_state.query_id
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small", key="query-select"):
            st.selectbox(
                "Query",
                query_ids,
                key=PICKER,
                on_change=_picked,
                format_func=lambda q: (
                    f"Query {query_ids.index(q) + 1} of {len(query_ids)} · {short_status(by_id[q])}"
                    + (" · pilot" if by_id[q].is_pilot else "")
                ),
            )
            query_id: int = st.session_state.query_id
            if st.button(":material/apps:", key="browse-queries", help="See all your queries"):
                browse(ctx, queue, query_id)
        view = ctx.api.query(ctx.study.id, query_id)
        load(view)
        if view.image_id is not None:
            query_thumb = thumbnails(
                ctx.token, ctx.study.id, (view.image_id,), settings.display.query_px, False
            )
            st.image(query_thumb[view.image_id], width="stretch")
        if view.text:
            st.markdown(f"> {view.text}")
        if view.is_pilot:
            st.info("Pilot query: judge every image one by one.", icon=":material/science:")
        judged = sum(value[0] is not None for value in state(query_id).values())
        st.progress(judged / view.pool_size, text=f"{judged} of {view.pool_size} judged")
        if finished and to_review:
            st.info(
                f"All {len(queue)} queries judged; {to_review} left to review.", icon=":material/task_alt:"
            )
        elif finished:
            st.success(f"All {len(queue)} queries done.", icon=":material/task_alt:")
        names = offered(settings, view)
        mode = (
            st.segmented_control("Mode", names, default=names[0], key=f"mode:{query_id}", width="stretch")
            or names[0]
        )
        following = upcoming(ctx, queue, query_id)
        st.button(
            "Next query",
            key="next-query",
            on_click=next_query,
            args=(ctx,),
            icon=":material/skip_next:",
            help="Next unfinished query",
            disabled=following is None,
            width="stretch",
        )
        images_per_row(MODES[mode].reflows)
        with st.container(horizontal=True, gap="small"):
            st.session_state.setdefault(collapse_key(query_id), collapsed(query_id))
            st.toggle(
                "Collapse judged",
                key=collapse_key(query_id),
                help="Hide the images of every fully judged group; switch off to show them again",
                on_change=collapse_judged,
                args=(query_id, [m.member_id for m in view.individual]),
            )
            tint_toggle()
            if settings.display.split and settings.encoder:
                st.button(
                    "Undo split",
                    key="undo-split",
                    icon=":material/undo:",
                    help="Merge back the last group you split",
                    disabled=view.undoable_splits == 0,
                    on_click=undo_split,
                    args=(ctx, query_id),
                )
    return view, mode, following
