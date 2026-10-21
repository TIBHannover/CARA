"""Simulation step 3: the grouping methods to compare and their values. Every combination is one setting."""

from dataclasses import dataclass
from math import prod

import streamlit as st

import styles
from client import Study

MAX_SETTINGS = 60
SIZES = [4, 8, 12, 16, 24, 32, 48]
SOLO = [0, 5, 10, 20]


@dataclass(frozen=True, slots=True)
class Parameter:
    """One parameter of a grouping method: the values offered and those picked to start with.

    Attributes:
        field: The parameter's name in the server's plan.
    """

    field: str
    label: str
    options: list[object]
    default: list[object]


@dataclass(frozen=True, slots=True)
class Method:
    """A grouping method the simulator can try, with a line about it and its parameters.

    Attributes:
        name: The method's name in the server's plan.
    """

    name: str
    title: str
    about: str
    parameters: list[Parameter]


METHODS = [
    Method(
        "agglomerative",
        "Agglomerative clustering",
        "Merges similar images into a tree, cut at the maximum group size. Linkage: average (balanced), "
        "complete (tight), single (long chains).",
        [
            Parameter("linkage", "Linkage", ["average", "complete", "single"], ["average"]),
            Parameter("max_size", "Maximum group size", list(SIZES), [8, 16, 32]),
        ],
    ),
    Method(
        "kmeans",
        "k-means",
        "k groups per pool; larger ones are split further.",
        [
            Parameter("n_groups", "Number of groups (k)", [5, 10, 15, 20, 30, 40], [10, 20]),
            Parameter("max_size", "Maximum group size", list(SIZES), [16]),
        ],
    ),
    Method(
        "hdbscan",
        "HDBSCAN",
        "Dense groups only; outliers are left ungrouped.",
        [
            Parameter("min_cluster_size", "Minimum cluster size", [2, 3, 5, 10, 15], [3, 5]),
            Parameter("max_size", "Maximum group size", list(SIZES), [16]),
        ],
    ),
]


@dataclass(frozen=True, slots=True)
class Candidates:
    """The settings step 3 asks the simulator to compare.

    Attributes:
        plan: The server's `SimulatorPlan`, without the annotators.
        total: Settings to compare, the one-at-a-time reference included.
        complete: Whether every chosen method has a value for every parameter.
    """

    plan: dict[str, object]
    total: int
    complete: bool


def _values(method: Method) -> dict[str, list[object]]:
    """Draw a method's card; return the values picked for each of its parameters."""
    with st.container(border=True):
        st.markdown(f"**{method.title}**")
        st.caption(method.about)
        with st.container(horizontal=True):
            return {
                p.field: st.multiselect(p.label, p.options, default=p.default, key=f"{method.name}-{p.field}")
                for p in method.parameters
            }


def candidate_settings(study: Study) -> Candidates:
    """Draw step 3: the grouping methods and values to compare; return them as candidates."""
    with styles.section("settings", "3 · Grouping methods"):
        st.caption(
            "Every combination of values is one setting; one image at a time and the current setting are "
            "always included."
        )
        by_name = {m.name: m for m in METHODS}
        chosen = st.multiselect(
            "Grouping methods",
            list(by_name),
            format_func=lambda name: by_name[name].title,
            default=["agglomerative"],
        )
        plan: dict[str, object] = dict.fromkeys(by_name)
        groupings, complete = 0, bool(chosen)
        for name in chosen:
            values = _values(by_name[name])
            plan[name] = values
            groupings += prod(len(v) for v in values.values())
            complete &= all(values.values())

        st.markdown("**Ungrouped images**, with any method")
        current_solo = int(study.settings.solo.percentile)
        with st.container(horizontal=True):
            solo = st.multiselect(
                "Images without a close neighbour (percentile)",
                SOLO,
                default=[current_solo] if current_solo in SOLO else [10],
                help="Images whose nearest neighbour is less similar than this percentile of the query's "
                "images are left ungrouped: placed in a group, they would make it mixed.",
            )
            top_k = st.multiselect(
                "Images most similar to the query (top k)",
                [0, 5, 10, 20],
                default=[0],
                help="The k images most similar to the query are left ungrouped; most Relevant images "
                "are usually among them.",
            )
        plan |= {"solo_percentile": solo, "top_k_individual": top_k}
        total = groupings * len(solo) * len(top_k) + 1
        complete &= bool(solo) and bool(top_k)
        if not complete:
            st.warning("Choose at least one method and one value for every option.", icon=":material/tune:")
        elif total > MAX_SETTINGS:
            st.warning(f"{total} settings: choose fewer values (at most {MAX_SETTINGS}).")
        else:
            st.info(
                f"**{total} settings to compare**: {groupings} groupings × {len(solo) * len(top_k)} rules "
                "for ungrouped images, plus the one-image-at-a-time reference (and the current setting if "
                "it is not among them).",
                icon=":material/tune:",
            )
    return Candidates(plan, total, complete)
