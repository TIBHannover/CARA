"""Images on the judge page: the grid, one image with its label buttons, and the compare dialog."""

import streamlit as st

import styles
from client import Member, QueryView
from components.feedback import count
from components.judging import Judging, groups, on_label, state
from components.labels import label_control
from state import client, thumbnails


@st.dialog("Compare with the query", width="large")
def compare(ctx: Judging, view: QueryView, member: Member, source: str, position: int | None) -> None:
    """Show an image beside the query, large, with its label buttons and its neighbours (`context`)."""
    labels = state(view.query_id)
    with st.container(horizontal=True, vertical_alignment="center"):
        for name in ctx.label_names:
            current = labels[member.member_id][0] == name
            if st.button(name, icon=ctx.icon_of[name], type="primary" if current else "secondary"):
                on_label(ctx, view.query_id, [member.member_id], name, source, position)
                st.rerun()
        st.space("stretch")
        size = st.segmented_control(
            "Size", ["Side by side", "Large"], default="Side by side", label_visibility="collapsed"
        )
    side_by_side = size != "Large"
    wanted = tuple(i for i in (view.image_id, member.image_id) if i is not None)
    images = thumbnails(ctx.token, ctx.study.id, wanted, 640 if side_by_side else 1280, False)
    query_box, candidate_box = st.columns(2) if side_by_side else (st.container(), st.container())
    with query_box:
        st.caption("Query")
        if view.image_id is not None:
            st.image(images[view.image_id], width="stretch")
        if view.text:
            st.markdown(f"> {view.text}")
    with candidate_box:
        st.caption(f"Image · {labels[member.member_id][0] or 'not judged yet'}")
        st.image(images[member.image_id], width="stretch")
    context(ctx, view, member, source)


@st.cache_data(ttl=600, max_entries=500, show_spinner=False)
def similar(token: str, study_id: int, query_id: int, to: tuple[int, ...], k: int) -> list[int]:
    """Return the `k` pool images most like any of `to`, most similar first; cached for ten minutes."""
    return client().similar(study_id, query_id, list(to), k)


def context(ctx: Judging, view: QueryView, member: Member, source: str) -> None:
    """Show the image among its neighbours: the group it was judged in, or the pool images most like it.

    Labels set here are saved at once; "Done" redraws the page with them.
    """
    shown_groups = groups(view.query_id)
    number = next(
        (n for n, g in enumerate(shown_groups, start=1) if member.member_id in g and len(g) > 1), None
    )
    group = shown_groups[number - 1] if number else None
    original = f"Original group (Group {number}, {count(len(group), 'image')})" if group else None
    views = ([original] if original else []) + (["Most similar images"] if ctx.settings.encoder else [])
    if not views:
        st.caption("This study has no encoder, so there are no similar images to show next to it.")
        return
    with st.container(horizontal=True, vertical_alignment="center"):
        shown = (
            st.segmented_control(
                "Show next to it", views, default=views[0], key=f"ctx-view:{member.member_id}"
            )
            or views[0]
        )
        st.space("stretch")
        if st.button("Done", icon=":material/check:", type="primary"):
            st.rerun()
    if not group:
        st.caption("This image is judged one by one, not in a group.")
    if shown == original and group:
        ids = [m for m in group if m != member.member_id]
    else:
        ids = similar(ctx.token, ctx.study.id, view.query_id, (member.member_id,), 2 * st.session_state.cols)
    member_of = {m.member_id: m for m in view.members}
    neighbours = [member_of[i] for i in ids]
    thumbs = thumbnails(
        ctx.token, ctx.study.id, tuple(m.image_id for m in neighbours), ctx.settings.display.thumb_px, True
    )
    with st.container(key=f"grid:ctx:{view.query_id}:{member.member_id}"):
        for other in neighbours:
            with st.container(key=f"cell:ctx:{view.query_id}:{other.member_id}:{frame(ctx, view, other)}"):
                st.image(thumbs[other.image_id], width="stretch")
                label_control(
                    ctx,
                    view.query_id,
                    f"item:ctx:{view.query_id}:{other.member_id}",
                    [other.member_id],
                    state(view.query_id)[other.member_id][0],
                    source,
                    None,
                    compact=True,
                )


def frame(ctx: Judging, view: QueryView, member: Member) -> str:
    """Return the key suffix that gives an image the frame of its label (`lab<index>`, or `labnone`)."""
    # Key suffix with the image's label, so its coloured frame is a plain class rule (no :has()).
    label = state(view.query_id)[member.member_id][0]
    return f"lab{ctx.label_names.index(label)}" if label in ctx.label_names else "labnone"


def candidate(
    ctx: Judging,
    view: QueryView,
    member: Member,
    thumb: bytes,
    source: str,
    position: int | None,
    wrap: bool = False,
) -> None:
    """Draw one pool image with its label buttons and the button that opens the compare dialog.

    Args:
        source: How a label given here is recorded: `item` (Judge mode) or `review`.
        position: The image's group on the page, or None outside a group.
        wrap: Put the frame suffix on a wrapper, so the tile keeps a stable key for drag and drop (review).
    """
    key = f"{source}:{view.query_id}:{member.member_id}"
    label = state(view.query_id)[member.member_id][0]
    if wrap:  # review tiles keep a stable key for drag and drop, so the frame suffix goes on a wrapper
        with st.container(key=f"img:{key}:{frame(ctx, view, member)}"):
            st.image(thumb, width="stretch")
    else:
        st.image(thumb, width="stretch")
    label_control(
        ctx,
        view.query_id,
        key,
        [member.member_id],
        label,
        source,
        position,
        compact=True,
        on_compare=lambda: compare(ctx, view, member, source, position),
    )


def image_grid(
    ctx: Judging,
    view: QueryView,
    members: list[Member],
    thumbs: dict[int, bytes],
    review: bool,
    position: int | None,
) -> None:
    """Draw images as a grid whose width follows "Images per row" (`styles.images_per_row`).

    A CSS grid, not `st.columns`: changing the setting then changes one CSS variable and the browser doesn't
    rebuild every tile.
    """
    if not members:
        return
    source = "review" if review else "item"
    first = min(m.member_id for m in members)
    with st.container(key=f"grid:{source}:{view.query_id}:{first}:{len(members)}"):
        for member in members:
            with st.container(
                key=f"cell:{source}:{view.query_id}:{member.member_id}:{frame(ctx, view, member)}"
            ):
                candidate(ctx, view, member, thumbs[member.image_id], source, position)


@st.fragment
def images_per_row(reflows: bool) -> None:
    """Draw the "Images per row" slider and apply it.

    Args:
        reflows: Whether a change redraws the page (Review mode shares the columns out over its panels);
            otherwise only one CSS variable changes.
    """
    # A widget key keeps the slider one widget (without it, every change made a new one, and a drag still in
    # progress snapped back). Streamlit drops a keyed widget's value when the page is not shown, so it is
    # seeded again from `cols`, which holds the setting.
    st.session_state.setdefault("cols_slider", st.session_state.cols)
    cols = st.slider("Images per row", 2, 12, key="cols_slider")
    if cols != st.session_state.cols:
        st.session_state.cols = cols
        if reflows:
            st.rerun()
    styles.images_per_row(cols)
