"""Review mode: every image of the query under its label, to check and fix once all are judged."""

import streamlit as st
from streamlit_dnd import dnd

import styles
from client import Member, QueryView
from components.images import candidate, image_grid, similar
from components.judging import Judging, on_label, state


def label_board(
    ctx: Judging, view: QueryView, panels: list[tuple[str, str, list[Member]]], thumbs: dict[int, bytes]
) -> None:
    """Draw Review mode as a board: one column per label, images moved between columns to relabel.

    Each column scrolls on its own, so every drop target stays in view while dragging. A drop relabels the
    image at once; the label buttons stay as the keyboard path.

    Args:
        panels: (label, column title, images) per column.
    """
    # streamlit-dnd moves the keyed direct children of a panel, so the tiles sit right inside it.
    panel_label = {f"panel-{view.query_id}-{i}": name for i, (name, _, _) in enumerate(panels)}
    label_of = {label.name: label for label in ctx.settings.labels}
    hints = [f"hint-{view.query_id}-{i}" for i in range(len(panels))]
    # "Images per row" is shared out over the panels by how many images each shows, so every image on the
    # board has the same size and a panel with few images does not get oversized ones.
    widths = styles.slots([len(members) for _, _, members in panels], st.session_state.cols)
    colour_of = {label.name: label.colour for label in ctx.settings.labels}
    colours = [colour_of[name] for name in panel_label.values()]
    styles.review_board(list(panel_label), f"hint-{view.query_id}-", widths, colours)
    columns = st.columns(widths, gap="small")
    for column, (_, title, members), key, hint in zip(columns, panels, panel_label, hints, strict=True):
        with column:
            with st.container(key=f"head-{key}"):
                st.markdown(f"{styles.label_icon(label_of[panel_label[key]])} {title}")
            with st.container(key=key):
                if not members:
                    # An empty container is not drawn, so it could not take a drop: keep a hint in it.
                    with st.container(key=hint):
                        st.caption("Drop images here")
                for member in members:
                    with st.container(key=f"tile-{view.query_id}-{member.member_id}", border=True):
                        candidate(ctx, view, member, thumbs[member.image_id], "review", None, wrap=True)
    event = dnd(*panel_label, exclude=hints, key=f"dnd-{view.query_id}")
    if event is None or event.from_container not in panel_label or event.to_container not in panel_label:
        return
    source = next(
        members
        for (_, _, members), key in zip(panels, panel_label, strict=True)
        if key == event.from_container
    )
    # Ignore an event that no longer matches the board, e.g. one sent just before a rerun.
    if (
        not 0 <= event.from_index < len(source)
        or event.item_key != f"tile-{view.query_id}-{source[event.from_index].member_id}"
    ):
        return
    member_id = source[event.from_index].member_id
    label = panel_label[event.to_container]
    orders: dict[str, list[int]] = st.session_state[f"board:{view.query_id}"]
    to_index = event.to_index
    if event.from_container == event.to_container and event.from_index < to_index:
        to_index -= 1  # the index counts the dragged image still in its old place
    orders[panel_label[event.from_container]].remove(member_id)
    orders[label].insert(to_index, member_id)
    if state(view.query_id)[member_id][0] != label:
        on_label(ctx, view.query_id, [member_id], label, "review", None)
    st.rerun()


def render(ctx: Judging, view: QueryView, thumbs: dict[int, bytes]) -> None:
    """Draw Review mode once every image has a label: columns by label, then "Done reviewing".

    Each column keeps its own order. Not Relevant starts with the images most similar to those judged
    Relevant, where a missed Relevant image is most likely (to the query when none are, in pool order without
    an encoder).
    """
    settings = ctx.settings
    labels = state(view.query_id)
    if not all(value[0] for value in labels.values()):
        st.info("Review opens once every image has a label.")
        return
    not_relevant = next((label.name for label in settings.labels if label.grade == 0), "Not Relevant")
    show_all = st.toggle(f"Show all {not_relevant} images")
    # Each column keeps its own order: a dropped image stays where it was dropped, and an image relabelled
    # with its buttons goes to the top of its new column. A missed Relevant image looks like the Relevant
    # ones, so the Not Relevant column starts with the images most similar to them (else to the query).
    orders: dict[str, list[int]] = st.session_state.setdefault(f"board:{view.query_id}", {})
    member_of = {m.member_id: m for m in view.members}
    panels = []
    positive = {label.name for label in settings.labels if (label.grade or 0) >= 1}
    relevant = tuple(sorted(m for m, (name, _) in labels.items() if name in positive))
    rank: dict[int, int] = {}
    if relevant and settings.encoder:
        ranked = similar(ctx.token, ctx.study.id, view.query_id, relevant, len(view.members))
        rank = {member_id: position for position, member_id in enumerate(ranked)}
    # A label that is switched off keeps a column only while images still have it.
    given = {name for name, _ in labels.values()}
    shown_labels = [label for label in settings.labels if label.offered or label.name in given]
    for label in shown_labels:
        by_relevant = label.grade == 0 and bool(rank)
        mine = [m for m in view.members if labels[m.member_id][0] == label.name]
        if by_relevant:
            mine.sort(key=lambda m: rank.get(m.member_id, len(rank)))
        else:
            mine.sort(key=lambda m: -m.score)
        kept = [i for i in orders.get(label.name, []) if labels[i][0] == label.name]
        orders[label.name] = [m.member_id for m in mine if m.member_id not in kept] + kept
        members = [member_of[i] for i in orders[label.name]]
        shown = members if label.grade != 0 or show_all else members[: settings.review.negatives_shown]
        order = (
            "most similar to the Relevant images first"
            if by_relevant
            else "most similar to the query first"
            if settings.encoder
            else "in pool order"
        )
        title = f"**{label.name}** ({len(members)}) :gray[· {order}]" + (
            "" if len(shown) == len(members) else f" :gray[· showing {len(shown)}]"
        )
        panels.append((label.name, title, shown))
    if settings.display.drag_and_drop:
        st.caption("Drag an image by its border into another column to relabel it, or use its buttons.")
        label_board(ctx, view, panels, thumbs)
    else:
        for _, title, shown in panels:
            with st.expander(title, expanded=True):
                image_grid(ctx, view, shown, thumbs, True, None)
    if view.reviewed:
        st.success("Review done.", icon=":material/check:")
    elif st.button("Done reviewing", key="done-review", icon=":material/done_all:", type="primary"):
        ctx.api.finish_review(ctx.study.id, view.query_id)
        st.rerun()
