"""The encoders of a nearest-neighbour pool, and how many images each contributes (New study, Pools card)."""

from typing import Any

import streamlit as st


def depth_table(
    key: str, encoders: list[str], depths: dict[str, int], default: int, disabled: bool = False
) -> dict[str, int]:
    """Draw one row per encoder (Use, Encoder, Depth); return the depths of the encoders in use.

    The pool is the union of each encoder's nearest images, each image once, so it holds up to the sum of the
    depths (TREC-style depth pooling). One encoder is simply one row.

    Args:
        depths: The encoders in use and their depths; the others start unticked at `default`.
    """
    rows: list[dict[str, Any]] = [
        {"use": name in depths, "encoder": name, "depth": depths.get(name, default)} for name in encoders
    ]
    edited = st.data_editor(
        rows,
        key=key,
        hide_index=True,
        width="stretch",
        disabled=True if disabled else ["encoder"],
        column_config={
            "use": st.column_config.CheckboxColumn("Use", width="small"),
            "encoder": st.column_config.TextColumn("Encoder"),
            "depth": st.column_config.NumberColumn(
                "Depth",
                min_value=1,
                max_value=5000,
                step=1,
                help="How many of its nearest images this encoder adds to each pool",
            ),
        },
    )
    chosen = {str(row["encoder"]): int(row["depth"]) for row in edited if row["use"] and row["depth"]}
    if chosen:
        st.caption(
            f"Each pool: up to {sum(chosen.values())} images; an image several encoders find counts once."
        )
    else:
        st.caption(":material/warning: Tick at least one encoder.")
    return chosen
