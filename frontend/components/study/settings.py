"""Annotation tab, below: the study's grouping, display, Suggest mode, labels, pools and review."""

from dataclasses import dataclass

import streamlit as st

import styles
from client import ApiError, CaraClient, Settings, Study
from state import forget_study

# Colour presets for the labels, in label order. The default matches the default labels (Relevant, Not
# Relevant, Unsure); the colour-blind safe one is Okabe and Ito's palette (2008).
PALETTES = {
    "Default": ["#2ecc71", "#e74c3c", "#f1c40f", "#3498db", "#9b59b6", "#e67e22", "#95a5a6"],
    "Colour-blind safe": ["#0072B2", "#E69F00", "#CC79A7", "#009E73", "#56B4E9", "#D55E00", "#F0E442"],
}


def _preset(palette: list[str], labels: int) -> None:
    """Put a palette into the colour pickers and save it on this run (a preset button's callback)."""
    for index in range(labels):
        st.session_state[f"label-colour-{index}"] = palette[index % len(palette)]
    st.session_state["label-preset"] = True


@dataclass(frozen=True, slots=True)
class Proposal:
    """A setting chosen in the Simulation tab, waiting in the Grouping card to be saved."""

    name: str
    grouping: dict[str, str | int | float]
    solo_percentile: float
    top_k_individual: int


def proposal_key(study_id: int) -> str:
    """Return the session key of the setting chosen in the Simulation tab for this study."""
    return f"proposal:{study_id}"


def render(api: CaraClient, study: Study) -> None:
    """Draw the study's settings cards; the locked ones are disabled once judging has started."""
    settings = study.settings
    locked = study.locked

    if locked:
        st.info(
            "Judging has started, so the pools, the grouping, the review rules and the label names and "
            "grades are fixed. The name, query order, display, Suggest mode, label colours and annotators "
            "per query can still change.",
            icon=":material/lock:",
        )

    def save(changes: dict[str, object], then: str | None = None) -> None:
        """Save changed settings, regroup or rebuild the pools if asked, and redraw the page.

        Args:
            then: `regroup` or `rebuild` after saving; None for neither.
        """
        try:
            api.update_settings(study.id, Settings.model_validate(settings.model_dump() | changes))
            if then == "regroup":
                with st.spinner("Grouping every pool"):
                    api.regroup(study.id)
            elif then == "rebuild":
                with st.spinner("Building and grouping every pool"):
                    api.rebuild_pools(study.id)
            forget_study()
            st.toast("Saved", icon=":material/check:")
            st.rerun()
        except ApiError as error:
            st.error(str(error))

    with styles.section("grouping", "Grouping"):
        if settings.encoder is None:
            st.markdown(
                "This study has no encoder, so every image is judged on its own. Grouping needs an "
                "encoder: create a new study with one."
            )
        else:
            proposal: Proposal | None = st.session_state.get(proposal_key(study.id))
            grouping = proposal.grouping if proposal else settings.grouping
            if proposal and not locked:
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.info(
                        f"From the simulation: **{proposal.name}**. Check it, then save to regroup every "
                        "pool.",
                        icon=":material/tune:",
                    )
                    if st.button("Discard", icon=":material/close:"):
                        del st.session_state[proposal_key(study.id)]
                        st.rerun()
            else:
                st.caption("The Simulation tab compares these options on your own queries before you choose.")
            current_method = str(grouping["method"])
            method = st.segmented_control(
                "Method",
                ["agglomerative", "kmeans", "hdbscan", "none"],
                default=current_method,
                disabled=locked,
            )
            method = method or current_method
            new_grouping: dict[str, str | int | float] = {"method": method}
            with st.container(horizontal=True):
                if method != "none":
                    new_grouping["max_size"] = st.number_input(
                        "Largest group", 2, 200, int(grouping.get("max_size", 16)), disabled=locked
                    )
                if method == "agglomerative":
                    linkages = ["average", "complete", "single"]
                    current_linkage = str(grouping.get("linkage", "average"))
                    new_grouping["linkage"] = st.selectbox(
                        "Linkage", linkages, linkages.index(current_linkage), disabled=locked
                    )
                if method == "kmeans":
                    new_grouping["n_groups"] = st.number_input(
                        "Groups (k)", 2, 200, int(grouping.get("n_groups", 12)), disabled=locked
                    )
                    new_grouping["seed"] = st.number_input(
                        "Seed", 0, 10_000, int(grouping.get("seed", 0)), disabled=locked
                    )
                if method == "hdbscan":
                    new_grouping["min_cluster_size"] = st.number_input(
                        "Smallest group", 2, 100, int(grouping.get("min_cluster_size", 3)), disabled=locked
                    )
            with st.container(horizontal=True):
                solo = st.number_input(
                    "Ungrouped: images without a close neighbour (percentile)",
                    0.0,
                    50.0,
                    proposal.solo_percentile if proposal else settings.solo.percentile,
                    step=5.0,
                    disabled=locked,
                )
                top_k = st.number_input(
                    "Ungrouped: the images most similar to the query",
                    0,
                    200,
                    proposal.top_k_individual if proposal else settings.top_k_individual,
                    disabled=locked,
                )
                order = st.segmented_control(
                    "Order", ["similarity", "pool_rank"], default=settings.order, disabled=locked
                )
            if st.button("Save and regroup every pool", icon=":material/workspaces:", disabled=locked):
                changes: dict[str, object] = {
                    "grouping": new_grouping,
                    "solo": {"percentile": float(solo)},
                    "top_k_individual": int(top_k),
                    "order": order or settings.order,
                }
                st.session_state.pop(proposal_key(study.id), None)
                save(changes, then="regroup")

    with styles.section("display", "Display"):
        st.caption("Defaults for every annotator; each annotator can change images per row in the View menu.")
        display = settings.display
        with st.form("display", border=False):
            with st.container(horizontal=True):
                thumb_px = st.number_input("Thumbnail size (px)", 64, 1024, display.thumb_px, step=32)
                query_px = st.number_input("Query image size (px)", 64, 2048, display.query_px, step=64)
                cols = st.number_input("Images per row", 1, 12, display.cols)
            drag = st.toggle("Drag and drop in Review mode", display.drag_and_drop)
            split = display.split
            group_order: str | None = display.group_order
            # Without an encoder there are no groups to split or order.
            if settings.encoder is not None:
                split = st.toggle(
                    "Annotators may split groups",
                    display.split,
                    help="Split divides a mixed group in two; off keeps every annotator on the same groups.",
                )
                orders = {
                    "similarity": "Most similar to the query first",
                    "similarity_asc": "Least similar to the query first",
                    "size": "Largest first",
                    "size_asc": "Smallest first",
                }
                group_order = st.segmented_control(
                    "Group order",
                    list(orders),
                    format_func=orders.__getitem__,
                    default=display.group_order,
                    help="Applies to queries an annotator opens from now on. The default is most similar to "
                    "the query first.",
                )
            if st.form_submit_button("Save", icon=":material/save:"):
                sizes = {"thumb_px": int(thumb_px), "query_px": int(query_px), "cols": int(cols)}
                flags = {"drag_and_drop": drag, "split": split, "group_order": group_order or "similarity"}
                save({"display": sizes | flags})

    with styles.section("suggest", "Suggest mode"):
        if settings.encoder is None:
            st.markdown("Suggest mode compares images, so it needs an encoder; this study has none.")
        else:
            st.markdown(
                "- Annotators mark a few images Not Relevant (and, if any, Relevant) one by one.\n"
                "- Unjudged images clearly similar to a marked image get its label as a suggestion.\n"
                "- Images similar to the query never get a Not Relevant suggestion.\n"
                "- A suggestion becomes a label only when accepted, and is recorded as an accepted "
                "suggestion.\n"
                "- Faster, but suggestions can sway annotators. Never used in pilot queries."
            )
            suggest = settings.suggest
            with st.form("suggest", border=False):
                enabled = st.toggle("Offer Suggest mode", suggest.enabled)
                with st.container(horizontal=True):
                    min_seeds = st.number_input(
                        "Images marked Not Relevant before suggestions start",
                        1,
                        20,
                        suggest.min_seeds,
                        help="Marked one by one. Images marked Relevant are optional starting points.",
                    )
                    min_pool = st.number_input(
                        "Only for pools of at least (images)",
                        0,
                        100_000,
                        suggest.min_pool_size,
                        step=50,
                        help="0: every pool. Larger pools (or whole-corpus studies) gain most.",
                    )
                margin = st.slider(
                    "How clear a suggestion must be",
                    0.0,
                    0.3,
                    suggest.min_margin,
                    0.01,
                    help="How much more similar an image must be to the image it follows than to any image "
                    "of the other label (cosine similarity). Higher: fewer, safer suggestions.",
                )
                if st.form_submit_button("Save", icon=":material/save:"):
                    values = suggest.model_dump() | {
                        "enabled": enabled,
                        "min_seeds": int(min_seeds),
                        "min_pool_size": int(min_pool),
                        "min_margin": float(margin),
                    }
                    save({"suggest": values})

    with styles.section("labels", "Labels"):
        st.caption(
            "Names and grades are fixed when the study is created; colours and short names can change. A "
            "label without a grade (such as Unsure) can be switched off: annotators no longer see it, and "
            "images that already have it keep it."
        )
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown("Colours:")
            for name, palette in PALETTES.items():
                st.button(
                    name,
                    key=f"preset-{name}",
                    icon=":material/palette:",
                    on_click=_preset,
                    args=(palette, len(settings.labels)),
                )
        with st.form("labels", border=False):
            labels = []
            for index, label in enumerate(settings.labels):
                with st.container(horizontal=True, vertical_alignment="bottom"):
                    st.text_input("Name", label.name, disabled=True, key=f"label-name-{index}")
                    st.text_input(
                        "Grade", str(label.grade), disabled=True, key=f"label-grade-{index}", width=90
                    )
                    short = st.text_input("Short", label.short or "", key=f"label-short-{index}", width=90)
                    colour = st.color_picker("Colour", label.colour, key=f"label-colour-{index}")
                    offered = (
                        st.toggle("Offer to annotators", label.offered, key=f"label-offered-{index}")
                        if label.grade is None
                        else True
                    )
                update = {"short": short or None, "colour": colour, "offered": offered}
                labels.append(label.model_copy(update=update).model_dump())
            if st.form_submit_button("Save", icon=":material/save:") or st.session_state.pop(
                "label-preset", False
            ):
                save({"labels": labels})

    with styles.section("pools", "Pools"):
        pool = settings.pool
        if pool.source == "file":
            st.markdown(
                "Pools come from `queries.jsonl` (`pool.source: file`); create a new study to change them."
            )
        elif pool.source == "random":
            st.caption(
                "A random draw of k images per query, among those the study's encoder has embedded: a "
                "baseline that no encoder shapes. Rebuilding regroups too. Not possible once judged."
            )
            with st.form("pools", border=False):
                with st.container(horizontal=True):
                    k = st.number_input("k", 1, 5000, pool.k or 200, disabled=locked)
                    seed = st.number_input("Seed", 0, 2**31 - 1, pool.seed, disabled=locked)
                if st.form_submit_button("Save and redraw pools", icon=":material/refresh:", disabled=locked):
                    save(
                        {"pool": pool.model_copy(update={"k": int(k), "seed": int(seed)}).model_dump()},
                        then="rebuild",
                    )
        else:
            fused = pool.encoders or [name for name in (settings.encoder,) if name]
            st.caption(
                f"The k nearest images of each query by {' and '.join(fused)}"
                + (", fused by reciprocal rank fusion" if len(fused) > 1 else "")
                + ". Rebuilding regroups too. Not possible once judged."
            )
            with st.form("pools", border=False):
                whole = st.toggle("Whole collection (up to the size limit)", pool.k is None, disabled=locked)
                k = st.number_input("k", 1, 5000, pool.k or 200, disabled=locked)
                if st.form_submit_button(
                    "Save and rebuild pools", icon=":material/refresh:", disabled=locked
                ):
                    save(
                        {"pool": pool.model_copy(update={"k": None if whole else int(k)}).model_dump()},
                        then="rebuild",
                    )

    with styles.section("review", "Review round"):
        review = settings.review
        with st.form("review", border=False):
            with st.container(horizontal=True, vertical_alignment="bottom"):
                enabled = st.toggle("Review round", review.enabled, disabled=locked)
                required = st.toggle(
                    "Required before a query counts as done", review.required, disabled=locked
                )
                shown = st.number_input(
                    "Not Relevant images shown in review", 1, 1000, review.negatives_shown, disabled=locked
                )
            if st.form_submit_button("Save", icon=":material/save:", disabled=locked):
                save({"review": {"enabled": enabled, "required": required, "negatives_shown": int(shown)}})
