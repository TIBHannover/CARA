"""The annotation guidelines as annotators and adjudicators read them: the text, with examples placed in it.

The admin places an example with `{{example 123}}`, or a row of them with `{{examples 12 34}}`; the
number is the example's id, shown with each example on the Guidelines tab. The rest follow the text.
"""

import re
from collections.abc import Callable

import streamlit as st

import styles
from client import Example, Study
from components.images import frame_suffix, show_query
from state import thumbnails

PLACEHOLDER = re.compile(r"\{\{\s*examples?\s+([\d ,]+?)\s*\}\}")


def placeholder(example: Example) -> str:
    """Return the text that places an example in the guidelines."""
    return f"{{{{example {example.member_id}}}}}"


def label_badge(study: Study, name: str) -> None:
    """Show a label's name in its colour, as on the label buttons."""
    colour = next((label.colour for label in study.settings.labels if label.name == name), "#71717A")
    st.html(f'<span class="cara-badge" style="border-color:{colour};color:{colour}">{name}</span>')


def examples(
    study: Study, shown: list[Example], key: str, below: Callable[[Example], None] | None = None
) -> None:
    """Show examples by query: the query on the left, its examples framed in their label's colour.

    Args:
        key: Makes the widget keys unique when examples are shown in several places.
        below: Drawn under each example (the admin's id and Remove button); None for nothing.
    """
    settings = study.settings
    names = [label.name for label in settings.labels]
    by_query: dict[tuple[int | None, str | None], list[Example]] = {}
    for example in shown:
        by_query.setdefault((example.query_image_id, example.query_text), []).append(example)
    token = st.session_state.token
    thumbs = thumbnails(token, study.id, tuple(e.image_id for e in shown), settings.display.thumb_px, True)
    for number, ((query_image, query_text), group) in enumerate(by_query.items(), start=1):
        with st.container(border=True, key=f"guide-{key}-{number}"):
            left, right = st.columns([1, 4], gap="medium")
            with left:
                st.caption("Query")
                show_query(study.id, query_image, query_text, settings.display.thumb_px)
            with right, st.container(key=f"grid:guide:{key}:{number}"):
                for example in group:
                    frame = frame_suffix(names, example.label)
                    with st.container(key=f"cell:guide:{key}:{number}:{example.member_id}:{frame}"):
                        st.image(thumbs[example.image_id], width="stretch")
                        label_badge(study, example.label)
                        if example.note:
                            st.caption(example.note)
                        if below is not None:
                            below(example)


def render(study: Study, below: Callable[[Example], None] | None = None) -> None:
    """Show the guidelines' text with the examples it places, then the examples it doesn't."""
    guidelines = study.settings.guidelines
    by_id = {e.member_id: e for e in guidelines.examples}
    placed: set[int] = set()
    parts = PLACEHOLDER.split(guidelines.text)
    for index, part in enumerate(parts):
        if index % 2 == 0:  # text between placeholders
            if part.strip():
                st.markdown(part)
            continue
        ids = [int(i) for i in re.findall(r"\d+", part)]
        found = [by_id[i] for i in ids if i in by_id]
        if missing := [i for i in ids if i not in by_id]:
            st.caption(f":material/warning: No example with id {', '.join(map(str, missing))}.")
        placed |= {e.member_id for e in found}
        if found:
            examples(study, found, f"in{index}", below)
    rest = [e for e in guidelines.examples if e.member_id not in placed]
    if rest:
        st.markdown("**More examples**" if placed else "**Examples**")
        examples(study, rest, "rest", below)


@st.dialog("Annotation guidelines", width="large")
def _dialog(study: Study) -> None:
    styles.labels(study.settings.labels)
    styles.judge_page()
    render(study)


def button(study: Study) -> None:
    """Draw a panel-wide button that opens the guidelines, if the study has any."""
    guidelines = study.settings.guidelines
    if (guidelines.text or guidelines.examples) and st.button(
        "Guidelines", key="open-guidelines", icon=":material/menu_book:", width="stretch"
    ):
        _dialog(study)
