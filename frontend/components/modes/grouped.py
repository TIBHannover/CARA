"""Judge mode: the groups of similar images, then the images judged one by one."""

from collections import Counter

import streamlit as st

from client import Member, QueryView
from components.feedback import count, notify, show_toasts
from components.images import image_grid
from components.judging import (
    Judging,
    forget_groups,
    group_key,
    groups,
    has_groups,
    kept,
    on_label,
    remember_collapsed,
    set_groups,
    state,
    take_pool_completed,
)
from components.labels import label_control

GROUP_ORDER = {
    "similarity": "most similar to the query first",
    "similarity_asc": "least similar to the query first",
    "size": "largest first",
    "size_asc": "smallest first",
}


def set_up_groups(view: QueryView, group_order: str) -> None:
    """Store the query's groups in the study's group order, unless this session has them already."""
    if has_groups(view.query_id):
        return
    ordered = [[m.member_id for m in group.members] for group in view.groups]
    # The server sends the groups most similar to the query first; sorting is stable, so ties keep that order.
    match group_order:
        case "similarity_asc":
            ordered.reverse()
        case "size":
            ordered.sort(key=len, reverse=True)
        case "size_asc":
            ordered.sort(key=len)
    set_groups(view.query_id, ordered)


def render(ctx: Judging, view: QueryView, thumbs: dict[int, bytes]) -> None:
    """Draw Judge mode: the group navigator, every group, then the images judged one by one."""
    member_of = {m.member_id: m for m in view.members}
    group_navigator(ctx, groups(view.query_id), len(view.individual))
    for position, member_ids in enumerate(groups(view.query_id), start=1):
        render_group(ctx, view, [member_of[m] for m in member_ids], thumbs, position)
    if view.individual:
        render_group(ctx, view, view.individual, thumbs, None)


def open_key(query_id: int, member_ids: list[int]) -> str:
    """Return the session key that says whether a group's images are shown."""
    return f"open:{query_id}:{min(member_ids)}:{len(member_ids)}"


def toggle(key: str) -> None:
    """Flip a boolean in session state (the fold button's callback)."""
    st.session_state[key] = not st.session_state[key]


def collapse_judged(query_id: int, individual: list[int]) -> None:
    """Fold or unfold every fully judged group of the query (the "Collapse judged" callback)."""
    collapsed = remember_collapsed(query_id)
    labels = state(query_id)
    # Read the groups now: when the toggle was drawn they may not have been set up yet.
    changed = 0
    for member_ids in [*groups(query_id), individual]:
        if member_ids and all(labels[m][0] for m in member_ids):
            st.session_state[open_key(query_id, member_ids)] = not collapsed
            changed += 1
    if changed:
        what = "collapsed" if collapsed else "shown again"
        notify(f"{count(changed, 'judged group')} {what}.", ":material/unfold_less:")


def undo_split(ctx: Judging, query_id: int) -> None:
    """Merge back the annotator's last split, and drop the groups so the next run reads them again."""
    merged = set(ctx.api.undo_split(ctx.study.id, query_id))
    parts = [p for p, g in enumerate(forget_groups(query_id), start=1) if set(g) <= merged]
    together = f"one group again ({count(len(merged), 'image')})"
    if len(parts) == 2:
        notify(f"Groups {parts[0]} and {parts[1]} are {together}.", ":material/undo:")
    else:
        notify(f"Split undone: {together}.", ":material/undo:")


@st.fragment
def render_group(
    ctx: Judging, view: QueryView, members: list[Member], thumbs: dict[int, bytes], position: int | None
) -> None:
    """Draw one group (or, with `position` None, the images judged one by one) as a fragment.

    An action inside reruns only this group; a label that completes the pool reruns the whole page.
    """
    if take_pool_completed():
        st.rerun()
    show_toasts()
    query_id = view.query_id
    member_ids = [m.member_id for m in members]
    labels = state(query_id)
    judged = sum(labels[m][0] is not None for m in member_ids)
    shown_key = open_key(query_id, member_ids)
    st.session_state.setdefault(shown_key, True)
    shown = st.session_state[shown_key]
    bar_key = group_key(query_id, member_ids)
    # ":solo" lets the tour tell the one-by-one section from the groups.
    with st.container(border=True, key=f"box:{shown_key}" + (":solo" if position is None else "")):
        with st.container(horizontal=True, vertical_alignment="center", key=f"head:{shown_key}"):
            title = "Judge one by one" if position is None else f"Group {position}"
            counts = Counter(label for m in member_ids if (label := labels[m][0]) is not None)
            summary = "" if shown else " · " + " ".join(f"{ctx.icon_of[n]} {c}" for n, c in counts.items())
            # Taller than the box's height cap (styles.judge_page): the rest is a scroll inside the box.
            more = " · scroll for all" if shown and len(members) > 3 * st.session_state.cols else ""
            anchor = f'<span id="{group_anchor(position)}" class="cara-anchor"></span>'
            st.markdown(
                f"{anchor}**{title}** ({count(len(members), 'image')}) "
                f":gray[· {judged} judged{summary}{more}]",
                unsafe_allow_html=True,
            )
            st.space("stretch")
            if position is not None:
                if bar_key not in st.session_state:
                    values = {labels[m][0] for m in member_ids}
                    st.session_state[bar_key] = values.pop() if len(values) == 1 else None
                label_control(
                    ctx,
                    query_id,
                    bar_key,
                    member_ids,
                    st.session_state[bar_key],
                    "group",
                    position,
                    compact=False,
                )
                if (
                    ctx.settings.display.split
                    and len(members) > 1
                    and st.button(
                        "Split",
                        key=f"split:{bar_key}",
                        icon=":material/call_split:",
                        help="Divide into two groups",
                    )
                ):
                    shown_groups = groups(query_id)  # the stored list: changing it changes what is shown
                    index = shown_groups.index(member_ids)
                    halves = ctx.api.split(ctx.study.id, query_id, member_ids)
                    shown_groups[index : index + 1] = halves
                    notify(
                        f"Group {position} ({count(len(member_ids), 'image')}) split into Group {position} "
                        f"({count(len(halves[0]), 'image')}) and Group {position + 1} "
                        f"({count(len(halves[1]), 'image')}).",
                        ":material/call_split:",
                    )
                    st.rerun()
            st.button(
                ":material/unfold_less:" if shown else ":material/unfold_more:",
                key=f"toggle:{shown_key}",
                help="Hide the images" if shown else "Show the images",
                on_click=toggle,
                args=(shown_key,),
            )
        if position is not None:
            kept_notice(ctx, query_id, bar_key, position)
        if shown:
            image_grid(ctx, view, members, thumbs, False, position)


def kept_notice(ctx: Judging, query_id: int, bar_key: str, position: int) -> None:
    """Say which images kept their own label when the group was labelled, and offer to set them too."""
    label, kept_ids = kept(bar_key)
    labels = state(query_id)
    differ = [m for m in kept_ids if labels[m][0] != label]  # some may have been changed since
    if not differ or label is None:
        return
    with st.container(horizontal=True, vertical_alignment="center", key=f"kept-{bar_key}"):
        counts = Counter(labels[m][0] for m in differ)
        parts = [
            f"{n} {'image was' if n == 1 else 'images were'} labelled {name}" for name, n in counts.items()
        ]
        st.markdown(f":material/info: {' and '.join(parts)} individually.")
        st.button(
            f"Set {'all ' if len(differ) > 1 else ''}{len(differ)} to {label}",
            key=f"setall:{bar_key}",
            icon=ctx.icon_of[label],
            on_click=set_all,
            args=(ctx, query_id, differ, label, position),
        )


def set_all(ctx: Judging, query_id: int, member_ids: list[int], label: str, position: int) -> None:
    """Give images the group's label (the notice's button callback)."""
    on_label(ctx, query_id, member_ids, label, "item", position)
    notify(f"{count(len(member_ids), 'image')} set to {label}.", ctx.icon_of[label])


def group_anchor(position: int | None) -> str:
    """Return the HTML id the group navigator jumps to."""
    return "grp-solo" if position is None else f"grp-{position}"


def group_navigator(ctx: Judging, groups: list[list[int]], individual: int) -> None:
    """Draw one link per group with its size, above the groups, and how the groups are ordered."""
    parts = [(group_anchor(p), f"Group {p}", len(g)) for p, g in enumerate(groups, start=1)]
    if individual:
        parts.append((group_anchor(None), "One by one", individual))
    if not groups:  # a pilot query: nothing is grouped
        return
    links = "".join(f'<a href="#{a}">{name} <span>({n})</span></a>' for a, name, n in parts)
    total = count(len(groups), "group")
    order = GROUP_ORDER.get(ctx.settings.display.group_order, "")
    st.html(f'<nav class="cara-groups"><span class="cara-order">{total}, {order}:</span>{links}</nav>')
