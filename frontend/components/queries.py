"""An annotator's queue of queries: what is left, where to go next, and the browse and completion dialogs."""

from typing import Literal

import streamlit as st

import styles
from client import QueueItem
from components.judging import Judging
from state import thumbnails

STATUS_COLOUR: dict[str, Literal["gray", "blue", "green", "orange"]] = {
    "not started": "gray",
    "judged": "blue",
    "reviewed": "green",
}


def unfinished(ctx: Judging, item: QueueItem) -> bool:
    """Return whether a query still needs judging, or a required review."""
    return item.judged < item.pool_size or (ctx.settings.review.required and not item.reviewed)


def upcoming(ctx: Judging, items: list[QueueItem], current: int) -> QueueItem | None:
    """Return the next unfinished query after `current`, wrapping round; None when all are done."""
    ids = [item.query_id for item in items]
    start = ids.index(current) + 1 if current in ids else 0
    rotated = items[start:] + items[:start]
    return next((item for item in rotated if item.query_id != current and unfinished(ctx, item)), None)


def status(item: QueueItem) -> str:
    """Return a query's state in words: not started, in progress (n of m), judged or reviewed."""
    if item.judged == 0:
        return "not started"
    if item.judged < item.pool_size:
        return f"in progress ({item.judged} of {item.pool_size})"
    return "reviewed" if item.reviewed else "judged"


def short_status(item: QueueItem) -> str:
    """Return `status`, as n/m while in progress, to fit the query picker."""
    if 0 < item.judged < item.pool_size:
        return f"{item.judged}/{item.pool_size}"
    return status(item)


def go_to(query_id: int) -> None:
    """Open a query (the browse dialog's callback)."""
    st.session_state.query_id = query_id


def next_query(ctx: Judging) -> None:
    """Open the next unfinished query (the "Next query" callback)."""
    target = upcoming(ctx, ctx.api.queue(ctx.study.id), st.session_state.query_id)
    if target is not None:
        st.session_state.query_id = target.query_id


@st.dialog("Your queries", width="large")
def browse(ctx: Judging, items: list[QueueItem], current: int) -> None:
    """Show every query of the annotator as a card, to jump to one."""
    images = thumbnails(
        ctx.token, ctx.study.id, tuple(i.image_id for i in items if i.image_id is not None), 160, True
    )
    for start in range(0, len(items), 6):
        for column, (number, item) in zip(
            st.columns(6), list(enumerate(items, start=1))[start : start + 6], strict=False
        ):
            with column, styles.card(f"query-{item.query_id}"):
                if item.image_id is not None:
                    st.image(images[item.image_id], width="stretch")
                if item.text:
                    st.caption(item.text if len(item.text) < 80 else item.text[:77] + "…")
                state_name = status(item)
                st.badge(state_name, color=STATUS_COLOUR.get(state_name, "orange"))
                if st.button(
                    f"Query {number}",
                    key=f"browse:{item.query_id}",
                    type="primary" if item.query_id == current else "secondary",
                    width="stretch",
                    on_click=go_to,
                    args=(item.query_id,),
                ):
                    st.rerun()


@st.dialog("All done", icon=":material/celebration:")
def all_done(ctx: Judging, items: list[QueueItem]) -> None:
    """Thank the annotator once every query is judged (and reviewed)."""
    images = sum(item.pool_size for item in items)
    reviewed = " and reviewed" if ctx.settings.review.enabled else ""
    st.markdown(
        f"You judged{reviewed} all **{images:,} images** in **{len(items)} queries** of *{ctx.study.name}*."
    )
    st.markdown("Every label is saved. Thank you!")
    st.caption("You can come back at any time to change a label.")
    if st.button("Back to my queries", type="primary", width="stretch"):
        st.rerun()


def completion(ctx: Judging, queue: list[QueueItem]) -> tuple[bool, int]:
    """Return whether every query is finished and how many are left to review; celebrate the moment."""
    finished = not any(unfinished(ctx, item) for item in queue)
    to_review = sum(not item.reviewed for item in queue) if ctx.settings.review.enabled else 0
    working_key = f"working:{ctx.study.id}"
    if not finished or to_review:
        st.session_state[working_key] = True
    elif st.session_state.pop(working_key, False):
        # Celebrate only the moment the last query is finished, not on every visit afterwards.
        st.balloons()
        all_done(ctx, queue)
    return finished, to_review
