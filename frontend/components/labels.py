"""The label buttons: under an image (icons only) or on a group's bar (icon and name)."""

from collections.abc import Callable
from typing import Literal

import streamlit as st

from components.judging import Judging, on_label


def label_control(
    ctx: Judging,
    query_id: int,
    key: str,
    member_ids: list[int],
    active: str | None,
    source: str,
    position: int | None,
    compact: bool,
    on_compare: Callable[[], None] | None = None,
) -> None:
    """Draw one button per offered label; the active label is drawn as primary.

    Args:
        key: The container's key; the buttons' keys and the frame CSS build on it.
        active: The label to highlight, None for none.
        compact: Icon-only buttons that share the image's width; otherwise icon and name (a group's bar).
        on_compare: When given, a zoom button that opens the compare dialog.
    """
    # Buttons, not a segmented control: a button click carries its label in the callback arguments, while a
    # segmented control's value can be rolled back by a rerun that finishes after the next click, which then
    # saved labels nobody chose. The label lives in session state; the active one is drawn as primary.
    width: Literal["stretch", "content"] = "stretch" if compact else "content"
    # Under each image there are no tooltips: with ~800 buttons on a page they made every redraw much slower.
    with st.container(
        horizontal=True, gap=None, key=f"{key}:labels", width=width, vertical_alignment="center"
    ):
        for index, name in enumerate(ctx.label_names):
            st.button(
                ctx.icon_of[name] if compact else name,
                key=f"{key}:lbl{index}",
                icon=None if compact else ctx.icon_of[name],
                type="primary" if name == active else "secondary",
                width=width,
                on_click=on_label,
                args=(ctx, query_id, member_ids, name, source, position),
            )
        if on_compare is not None and st.button(":material/zoom_in:", key=f"{key}:compare"):
            on_compare()
