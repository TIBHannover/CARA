"""Adjudication: adjudicators (and admins) set final labels of judged images, filtered by agreement.

Laid out like the judge page: the query in a panel on the left, its images as a grid on the right, framed and
tinted in the colour of the label they end with (the final label, else the annotators' majority).
"""

from collections import Counter
from collections.abc import Callable

import streamlit as st

import styles
from client import AgreementReport, CaraClient, JudgedItem, Label, QueryAgreement, Study
from components.feedback import count
from components.images import frame_suffix, images_per_row, show_query, tint_toggle
from components.labels import label_buttons
from state import thumbnails

# Which images each filter shows, from the annotators' labels and the names of labels without a grade.
FILTERS: dict[str, Callable[[dict[str, str], set[str]], bool]] = {
    "Disagreements": lambda labels, _: len(set(labels.values())) > 1,
    "Unsure": lambda labels, ungraded: bool(ungraded & set(labels.values())),
    "Agreements": lambda labels, _: len(labels) > 1 and len(set(labels.values())) == 1,
    "All": lambda labels, _: True,
}
QUERY = "adjudicate-query"


def outcome(item: JudgedItem) -> str | None:
    """Return the label an image ends with: the final label, else the annotators' majority (None on a tie)."""
    if item.adjudicated is not None:
        return item.adjudicated
    ranked = Counter(item.labels.values()).most_common(2)
    return ranked[0][0] if len(ranked) == 1 or ranked[0][1] > ranked[1][1] else None


def open_count(query: QueryAgreement) -> int:
    """Return about how many disputed or Unsure images of a query have no final label yet.

    An estimate: an image both disputed and Unsure counts twice, and a final label may be on an agreed image.
    """
    return max(0, query.disagreements + query.unsure - query.adjudicated)


def to_decide(query: QueryAgreement) -> bool:
    """Return whether a query seems to have disputed or Unsure images without a final label (`open_count`)."""
    return open_count(query) > 0


def _next_query(queries: list[QueryAgreement]) -> None:
    """Open the next query with something to decide, after the current one (the button's callback)."""
    ids = [q.query_id for q in queries]
    start = ids.index(st.session_state[QUERY])
    later = queries[start + 1 :] + queries[: start + 1]
    st.session_state[QUERY] = next(q.query_id for q in later if to_decide(q))


def annotator_labels(labels: list[Label], item: JudgedItem) -> None:
    """Show each annotator's label in its colour, as on the label buttons."""
    of = {label.name: label for label in labels}
    st.html(
        '<div class="cara-votes">'
        + "".join(
            f'<span style="color:{of[name].colour}">{user}&nbsp;{of[name].short or name}</span>'
            for user, name in sorted(item.labels.items())
        )
        + "</div>"
    )


def image_grid(study: Study, key: str, items: list[JudgedItem], below: Callable[[JudgedItem], None]) -> None:
    """Draw judged images as the judge page's grid, framed and tinted by `outcome`, `below` under each."""
    settings = study.settings
    names = [label.name for label in settings.labels]
    thumbs = thumbnails(
        st.session_state.token, study.id, tuple(i.image_id for i in items), settings.display.thumb_px, True
    )
    with st.container(key=f"grid:{key}"):
        for item in items:
            with st.container(key=f"cell:{key}:{item.member_id}:{frame_suffix(names, outcome(item))}"):
                st.image(thumbs[item.image_id], width="stretch")
                annotator_labels(settings.labels, item)
                below(item)


def final_labels(api: CaraClient, study: Study, report: AgreementReport) -> None:
    """Draw a query with its judged images, filtered, each with a final-label control."""
    settings = study.settings
    styles.labels(settings.labels)
    styles.judge_page()
    if not report.queries:
        st.info("Nothing is judged yet.", icon=":material/hourglass_empty:")
        return
    queries = report.queries
    by_id = {q.query_id: q for q in queries}
    if st.session_state.get(QUERY) not in by_id:
        st.session_state[QUERY] = next((q for q in queries if to_decide(q)), queries[0]).query_id
    st.session_state.setdefault("cols", settings.display.cols)
    ungraded = {label.name for label in settings.labels if label.grade is None}
    names = [label.name for label in settings.labels]
    icon_of = {label.name: styles.label_icon(label) for label in settings.labels}

    left, right = st.columns([1, 4], gap="medium")
    with left, st.container(key="query-panel", border=True):
        ids = list(by_id)
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            query_id = st.selectbox(
                "Query",
                ids,
                key=QUERY,
                format_func=lambda q: (
                    f"Query {ids.index(q) + 1} of {len(ids)} · "
                    + (f"{open_count(by_id[q])} open" if to_decide(by_id[q]) else "done")
                    + (" · pilot" if by_id[q].is_pilot else "")
                ),
            )
        query = by_id[query_id or ids[0]]
        show_query(study.id, query.image_id, query.text, settings.display.query_px)
        st.caption(
            f"{count(query.annotators, 'annotator')} · {query.disagreements} disagree · "
            f"{query.unsure} unsure · {count(query.adjudicated, 'final label')}"
        )
        every = api.judged_items(study.id, query.query_id)
        shown = st.segmented_control(
            "Show",
            list(FILTERS),
            default="Disagreements",
            key="adjudicate-filter",
            format_func=lambda f: f"{f} ({sum(FILTERS[f](i.labels, ungraded) for i in every)})",
            width="stretch",
        )
        st.button(
            "Next query to decide",
            icon=":material/skip_next:",
            on_click=_next_query,
            args=(queries,),
            disabled=not any(to_decide(q) for q in queries if q.query_id != query.query_id),
            width="stretch",
        )
        images_per_row(False)
        tint_toggle()

    def on_final(item: JudgedItem, name: str) -> None:
        """Set the image's final label; clicking the current one takes it back (a button callback)."""
        api.adjudicate(study.id, item.member_id, None if item.adjudicated == name else name)

    def buttons(item: JudgedItem) -> None:
        # The judge page's label bar; the "item" key prefix gives it the same look under each image.
        label_buttons(
            f"item:cur:{item.member_id}",
            names,
            icon_of,
            item.adjudicated,
            True,
            lambda name: on_final(item, name),
        )

    with right:
        items = [item for item in every if FILTERS[shown or "All"](item.labels, ungraded)]
        st.caption(
            f"{len(items)} of {count(len(every), 'judged image')}. The frame shows the label an image ends "
            "with: the final label (the highlighted button), else the majority. A final label overrides the "
            "majority in the consensus qrels; click it again to take it back."
        )
        if not items:
            st.success("No image of this query matches.", icon=":material/check:")
            return
        image_grid(study, f"cur:{query.query_id}", items, buttons)
