"""The encoders of a nearest-neighbour pool, and how many images each contributes (New study, Pools card)."""

import streamlit as st


def depth_table(
    key: str, encoders: list[str], depths: dict[str, int], default: int, disabled: bool = False
) -> dict[str, int]:
    """Pick the pooling encoders, then a depth for each; return the depths of the encoders in use.

    The pool is the union of each encoder's nearest images, each image once, so it holds up to the sum of the
    depths (TREC-style depth pooling). One encoder is simply one depth field.

    Args:
        depths: The encoders in use and their depths; the others start at `default` once picked.
    """
    chosen = st.multiselect(
        "Pooling encoders",
        encoders,
        [name for name in encoders if name in depths],
        key=f"{key}-use",
        disabled=disabled,
        help="Each adds its nearest images to every pool. An encoder is listed once it has embedded the "
        "query set (cara encode). Several encoders keep the pool from favouring what one of them finds.",
    )
    picked = {
        name: int(
            st.number_input(
                f"Depth · {name}" if len(chosen) > 1 else "Depth",
                1,
                5000,
                depths.get(name, default),
                step=10,
                key=f"{key}-depth-{name}",
                disabled=disabled,
                help="How many of its nearest images this encoder adds to each pool",
            )
        )
        for name in chosen
    }
    if picked:
        st.caption(
            f"Each pool: up to {sum(picked.values())} images; an image several encoders find counts once."
        )
    else:
        st.caption(":material/warning: Pick at least one encoder.")
    return picked
