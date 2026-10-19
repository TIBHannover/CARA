"""Suggest mode: images similar to the ones an annotator marked, offered with the same label."""

import streamlit as st

from client import QueryView, SuggestedCluster, Suggestions
from components.feedback import count, notify
from components.images import candidate
from components.judging import Judging, on_label, state
from state import client


@st.cache_data(ttl=600, max_entries=200, show_spinner=False)
def suggestions(token: str, study_id: int, query_id: int, judged: tuple[tuple[int, str], ...]) -> Suggestions:
    """Return Suggest mode's suggestions, cached per set of this annotator's labels.

    `judged` is only the cache key: a new label (a new seed, or fewer open images) fetches anew.
    """
    return client().suggestions(study_id, query_id)


def suggest_legend(ctx: Judging) -> None:
    """Draw how to read Suggest mode, as a short list with swatches in the label colours."""
    relevant = next(label for label in ctx.settings.labels if (label.grade or 0) >= 1)
    not_relevant = next(label for label in ctx.settings.labels if label.grade == 0)

    def swatch(colour: str) -> str:
        """Return a small square in `colour`, for the legend."""
        return f'<span class="cara-swatch" style="border-color:{colour}"></span>'

    st.html(
        '<ul class="cara-legend">'
        f"<li>{swatch(relevant.colour)}Suggested <b>{relevant.name}</b></li>"
        f"<li>{swatch(not_relevant.colour)}Suggested <b>{not_relevant.name}</b></li>"
        f"<li>{swatch('#A1A1AA')}No suggestion: judge it yourself</li>"
        "<li>A suggestion is not a label until you pick one: for the whole group with the bar on its right "
        "(the dashed button is the suggestion), or image by image.</li>"
        "</ul>"
    )


def render(ctx: Judging, view: QueryView, thumbs: dict[int, bytes]) -> None:
    """Draw Suggest mode: a hint until enough images are marked, then the suggested groups."""
    labels = state(view.query_id)
    judged = tuple(sorted((m, label) for m, (label, _) in labels.items() if label))
    found = suggestions(ctx.token, ctx.study.id, view.query_id, judged)
    names = {label.grade: label.name for label in ctx.settings.labels}
    if not found.ready:
        st.info(
            f"Suggestions start after you mark {found.min_seeds} images {names.get(0)} one by one "
            f"(Judge mode, buttons under an image). Marked so far: {found.nonrelevant_seeds} "
            f"{names.get(0)}, {found.relevant_seeds} {names.get(1)}.",
            icon=":material/lightbulb:",
        )
        return
    if not found.clusters:
        st.success("Every image has a label.", icon=":material/check:")
        return
    suggest_legend(ctx)
    for cluster in found.clusters:
        render_suggested(ctx, view, cluster, thumbs)


def mark_all(ctx: Judging, query_id: int, member_ids: list[int], label: str, suggested: str | None) -> None:
    """Label a whole group of suggestions (the bar's callback).

    Taking the suggestion is recorded as `suggestion`; another label as the annotator's own group decision.
    """
    on_label(ctx, query_id, member_ids, label, "suggestion" if label == suggested else "group", None)
    notify(f"{count(len(member_ids), 'image')} marked {label}.", ctx.icon_of[label])


def suggest_bar(ctx: Judging, query_id: int, key: str, member_ids: list[int], suggested: str | None) -> None:
    """Draw the label bar for a whole group of suggestions; the suggested label has a dashed outline."""
    with st.container(
        horizontal=True, gap=None, key=f"sugbar:{key}:labels", vertical_alignment="center", width="content"
    ):
        for index, name in enumerate(ctx.label_names):
            st.button(
                name,
                key=f"sugbar:{key}:lbl{index}" + (":sugpick" if name == suggested else ""),
                icon=ctx.icon_of[name],
                help=f"Mark all {count(len(member_ids), 'image')} {name}",
                on_click=mark_all,
                args=(ctx, query_id, member_ids, name, suggested),
            )


def render_suggested(
    ctx: Judging, view: QueryView, cluster: SuggestedCluster, thumbs: dict[int, bytes]
) -> None:
    """Draw one group of suggestions: the marked images it follows, its bar, and its images."""
    query_id = view.query_id
    member_of = {m.member_id: m for m in view.members}
    key = f"{query_id}:{min(cluster.seeds, default='none')}"
    n = len(cluster.members)
    with st.container(border=True, key=f"sugbox:{key}"):
        with st.container(horizontal=True, vertical_alignment="center", key=f"sughead:{key}"):
            if cluster.seeds and cluster.label is not None:
                for seed in cluster.seeds[:3]:
                    st.image(thumbs[member_of[seed].image_id], width=56)
                which = "this image" if len(cluster.seeds) == 1 else f"these {len(cluster.seeds)} images"
                st.markdown(
                    f"You marked {which} **{ctx.icon_of[cluster.label]} {cluster.label}**. "
                    f"Similar images ({n}):"
                )
            else:
                st.markdown(f"**No suggestion: judge these yourself** ({count(n, 'image')})")
            st.space("stretch")
            suggest_bar(ctx, query_id, key, cluster.members, cluster.label)
        hint = f"sug{ctx.label_names.index(cluster.label)}" if cluster.label else "nosug"
        with st.container(key=f"grid:sug:{key}"):
            for member_id in cluster.members:
                member = member_of[member_id]
                with st.container(key=f"cell:sug:{query_id}:{member_id}:{hint}"):
                    candidate(ctx, view, member, thumbs[member.image_id], "item", None)
