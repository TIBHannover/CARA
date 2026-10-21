"""Guidelines tab: the admin writes the annotation guidelines and picks examples from judged queries."""

import streamlit as st

import styles
from client import ApiError, CaraClient, Example, JudgedItem, Settings, Study
from components import adjudication, guidelines
from components.feedback import count
from state import forget_study


def _save(api: CaraClient, study: Study, text: str, chosen: list[Example]) -> None:
    """Save the guidelines; they can change at any time, also once annotation has started."""
    value = {"text": text, "examples": [e.model_dump() for e in chosen]}
    try:
        api.update_settings(
            study.id, Settings.model_validate(study.settings.model_dump() | {"guidelines": value})
        )
        forget_study()
    except ApiError as error:
        st.error(str(error))


def render(api: CaraClient, study: Study) -> None:
    """Draw the Guidelines tab: the text, a preview with the examples, and judged images to pick more from."""
    current = study.settings.guidelines
    styles.labels(study.settings.labels)
    styles.judge_page()

    with styles.section("guidelines-text", "Text"):
        st.caption(
            "What annotators should judge relevant, in Markdown. Place an example with its placeholder, "
            "such as `{{example 123}}`, or a row of them with `{{examples 12 34}}`; examples not placed "
            "follow the text. Annotators and adjudicators open the guidelines from their query panel; they "
            "can change at any time."
        )
        with st.form("guidelines-text", border=False):
            text = st.text_area("Guidelines", current.text, height=260, label_visibility="collapsed")
            if st.form_submit_button("Save", icon=":material/save:"):
                _save(api, study, text, current.examples)
                st.rerun()

    with styles.section("guidelines-preview", f"Preview · {count(len(current.examples), 'example')}"):
        if not current.text and not current.examples:
            st.caption("Nothing yet: write the text above and add examples from the judged images below.")
        else:

            def manage(example: Example) -> None:
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    st.code(guidelines.placeholder(example), language=None, width="stretch")
                    if st.button(
                        ":material/delete:",
                        key=f"guide-remove-{example.member_id}",
                        help="Remove the example",
                    ):
                        _save(api, study, current.text, [e for e in current.examples if e != example])
                        st.rerun()

            guidelines.render(study, manage)

    with styles.section("guidelines-pick", "Add examples"):
        _pick(api, study)


def _pick(api: CaraClient, study: Study) -> None:
    """Draw the judged images of one query, filtered, each with a button that adds it as an example."""
    current = study.settings.guidelines
    report = api.agreement(study.id)
    queries = [q for q in report.queries if q.is_pilot] or report.queries
    if not queries:
        st.info("Examples come from judged images: run the pilot first.", icon=":material/science:")
        return
    st.caption(
        "Images the pilot annotators disagreed on or marked Unsure make the most useful examples: they show "
        "where the line between the labels runs."
        if queries[0].is_pilot
        else "No pilot was judged, so these are the study's judged queries."
    )
    by_id = {q.query_id: q for q in queries}
    ids = list(by_id)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        picked = st.selectbox(
            "Query",
            ids,
            key="guide-query",
            format_func=lambda q: (
                f"Query {ids.index(q) + 1} of {len(ids)} · {by_id[q].disagreements} disagree · "
                f"{by_id[q].unsure} unsure" + (" · pilot" if by_id[q].is_pilot else "")
            ),
        )
        shown = st.segmented_control(
            "Show", list(adjudication.FILTERS), default="Disagreements", key="guide-filter"
        )
    query = by_id[picked or ids[0]]
    ungraded = {label.name for label in study.settings.labels if label.grade is None}
    items = [
        item
        for item in api.judged_items(study.id, query.query_id)
        if adjudication.FILTERS[shown or "All"](item.labels, ungraded)
    ]
    st.caption(f"{count(len(items), 'image')}; the frame shows the label an image ends with.")
    added = {e.member_id for e in current.examples}
    names = [label.name for label in study.settings.labels]

    def add(item: JudgedItem) -> None:
        if item.member_id in added:
            st.caption(":material/check: In the guidelines")
            return
        with (
            st.popover("Add", icon=":material/add:", width="stretch"),
            st.form(f"guide-add-{item.member_id}", border=False),
        ):
            ends = adjudication.outcome(item)
            label = st.selectbox("Label", names, index=names.index(ends) if ends in names else 0)
            note = st.text_input("Why", placeholder="Only the frame matches the query.")
            if st.form_submit_button("Add to the guidelines", icon=":material/add:"):
                example = Example(
                    member_id=item.member_id,
                    image_id=item.image_id,
                    query_image_id=query.image_id,
                    query_text=query.text,
                    label=label,
                    note=note,
                )
                _save(api, study, current.text, [*current.examples, example])
                st.rerun()

    adjudication.image_grid(study, f"guide-pick:{query.query_id}", items, add)
