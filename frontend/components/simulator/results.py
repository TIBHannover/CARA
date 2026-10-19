"""Simulation step 5: the results for one annotator type at a time: time against recall, total time, and
every setting in a table."""

from collections.abc import Mapping
from dataclasses import dataclass

import streamlit as st

import styles
from client import AnnotatorResult, SettingResult
from components.feedback import count, percent
from components.simulator.run import SimulationRun

DEFINITIONS = """
- **Groups / query**: groups an annotator sees for one query, on average.
- **Judged one by one**: share of the images outside any group: images without a close neighbour, the images
  most similar to the query (top k), and images the method leaves ungrouped.
- **Min. actions / image**: one action per group plus one per individually judged image, divided by the
  number of images; the fewest possible, reached only if every group is all relevant or all not relevant.
- **Actions / image**: actions a perfect annotator needs, including corrections of single images inside
  mixed groups.
- **Min. time / image**: the time of the selected profile if every group were all relevant or all not
  relevant: one group action and a glance per grouped image, a full look per individually judged image;
  a lower bound on the time.
- **Time / image**: time of the selected annotator type, from its time per action.
- **Total time**: time per image × every image in the study, for one annotator, one pass.
- **Recall**: share of the relevant images that the selected realistic annotator labels relevant.
- **Recall, uncorrected**: recall if an annotator only labels groups and never corrects a single image;
  it shows how much a setting relies on corrections.
- **Trade-off front**: settings that no other setting beats on both time and recall for the selected annotator
  type; every other setting is slower, finds less, or both. Which one to use is your call.
- **One at a time**: every image judged on its own; the reference for time and recall.
"""


ROLES = {
    "trade-off front": "#4F46E5",
    "current": "#0EA5E9",
    "one at a time": "#18181B",
    "other settings": "#A1A1AA",
}
ROLE_SCALE = {"domain": list(ROLES), "range": list(ROLES.values())}


def method_of(result: SettingResult) -> str:
    """Return a setting's grouping method in words."""
    grouping = result.grouping
    return {
        "agglomerative": f"Agglomerative ({grouping.get('linkage')} linkage)",
        "kmeans": "k-means",
        "hdbscan": "HDBSCAN",
    }.get(str(grouping["method"]), "One at a time")


def parameters(result: SettingResult) -> str:
    """Return a setting's parameters in short (`max 16 · no close neighbour 10%`); a dash for none."""
    grouping = result.grouping
    found = {
        "agglomerative": [f"max {grouping.get('max_size')}"],
        "kmeans": [f"k={grouping.get('n_groups')}", f"max {grouping.get('max_size')}"],
        "hdbscan": [f"min {grouping.get('min_cluster_size')}", f"max {grouping.get('max_size')}"],
    }.get(str(grouping["method"]), [])
    found += [f"no close neighbour {result.solo_percentile:g}%"] if result.solo_percentile else []
    found += [f"top {result.top_k_individual}"] if result.top_k_individual else []
    return " · ".join(found) or "–"


def front(results: list[SettingResult], profile: int) -> set[int]:
    """Return the settings that no other beats on both time (lower) and recall (higher) for this type."""
    scored: list[tuple[int, float, float]] = []
    for i, r in enumerate(results):
        seconds, recall = r.annotators[profile].seconds_pc, r.annotators[profile].recall
        if seconds is not None and recall is not None:
            scored.append((i, seconds, recall))
    return {
        i
        for i, seconds, recall in scored
        if not any(t <= seconds and q >= recall and (t < seconds or q > recall) for _, t, q in scored)
    }


@dataclass(frozen=True, slots=True)
class SettingView:
    """One setting as seen for one annotator type."""

    result: SettingResult
    profile: int
    on_front: bool

    @property
    def mine(self) -> AnnotatorResult:
        """Return the result for the annotator type being viewed."""
        return self.result.annotators[self.profile]

    @property
    def label(self) -> str:
        """Return a setting's label for charts and tables: its method and parameters."""
        return label(self.result)

    @property
    def role(self) -> str:
        """Return how the charts mark the setting: one at a time, current, on the front, or other."""
        if self.result.strategy == "one at a time":
            return "one at a time"
        if self.result.is_current:
            return "current"
        return "trade-off front" if self.on_front else "other settings"

    def hours(self, images: int) -> float | None:
        """Return the time to judge the study's `images` images, in hours, for one annotator."""
        return self.mine.seconds_pc * images / 3600 if self.mine.seconds_pc is not None else None


def label(result: SettingResult) -> str:
    """Return a setting's label for charts and tables: its method and parameters."""
    return (
        "One at a time"
        if result.strategy == "one at a time"
        else f"{method_of(result)} · {parameters(result)}"
    )


def views(results: list[SettingResult], profile: int) -> list[SettingView]:
    """Return each setting as seen for one annotator type, marking the trade-off front."""
    best = front(results, profile)
    return [SettingView(r, profile, i in best) for i, r in enumerate(results)]


def show(run: SimulationRun, study_images: int) -> int:
    """Draw the results; return the annotator type picked to view them for."""
    results: list[SettingResult] = run.event.results or []
    images = run.event.images_in_study or study_images
    names = [a.name for a in results[0].annotators]
    with styles.section("results", "5 · Results"):
        st.caption(
            f"{run.source} · {count(results[0].queries, 'query')} replayed · "
            f"{count(len(results), 'setting')} · {count(len(names), 'annotator type')} · "
            f"ran at {run.when} in {run.seconds:.0f} s"
        )
        profile = 0
        if len(names) > 1:
            styles.profile_bar()
            with st.container(key="profile-bar", horizontal=True, vertical_alignment="center"):
                st.markdown(":material/person: **Results for annotator type**", width="content")
                picked = st.segmented_control(
                    "Results for", names, default=names[0], label_visibility="collapsed"
                )
            profile = names.index(picked or names[0])
        shown = views(results, profile)
        st.markdown(f"##### Time against recall · {names[profile]}")
        _time_recall_chart(shown)
        st.caption("Front: no other setting is both faster and finds more. Pick one below.")
        st.markdown(f"##### Time for all {images:,} images · {names[profile]}")
        _time_chart(shown, images)
        with st.expander("All settings", icon=":material/table:"):
            _settings_table(shown, images)
        with st.expander("Definitions", icon=":material/menu_book:"):
            st.markdown(DEFINITIONS)
    return profile


def _chart(points: list[dict[str, object]], profile: int, spec: Mapping[str, object], height: int) -> None:
    # Streamlit redraws a chart when its spec changes, not when only its data does: hence usermeta.
    st.vega_lite_chart({"usermeta": {"profile": profile}, "data": {"values": points}, **spec}, height=height)


def _time_recall_chart(shown: list[SettingView]) -> None:
    """Draw time against recall, one point per setting: further left is faster, higher finds more."""
    points: list[dict[str, object]] = [
        {"setting": v.label, "seconds": v.mine.seconds_pc, "recall": v.mine.recall, "role": v.role}
        for v in shown
        if v.mine.seconds_pc is not None and v.mine.recall is not None
    ]
    spec = {
        "mark": {"type": "point", "filled": True, "size": 140},
        "encoding": {
            "x": {
                "field": "seconds",
                "type": "quantitative",
                "scale": {"zero": False},
                "title": "Time per image (s) · faster ←",
            },
            "y": {
                "field": "recall",
                "type": "quantitative",
                "scale": {"zero": False},
                "title": "Recall · finds more ↑",
                "axis": {"format": "%"},
            },
            "color": {"field": "role", "type": "nominal", "title": None, "scale": ROLE_SCALE},
            "tooltip": [
                {"field": "setting", "title": "Setting"},
                {"field": "seconds", "title": "Time per image (s)", "format": ".2f"},
                {"field": "recall", "title": "Recall", "format": ".1%"},
            ],
        },
    }
    _chart(points, shown[0].profile, spec, 320)


def _time_chart(shown: list[SettingView], images: int) -> None:
    """Hours for one annotator to judge the whole study once, per setting."""
    bars: list[dict[str, object]] = [
        {"setting": v.label, "hours": v.hours(images), "role": v.role}
        for v in shown
        if v.mine.seconds_pc is not None
    ]
    spec = {
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "y": {
                "field": "setting",
                "type": "nominal",
                "title": None,
                "sort": "x",
                "axis": {"labelLimit": 360, "labelOverlap": False},
            },
            "x": {"field": "hours", "type": "quantitative", "title": "Hours, one annotator, one pass"},
            "color": {"field": "role", "type": "nominal", "title": None, "scale": ROLE_SCALE},
            "tooltip": [
                {"field": "setting", "title": "Setting"},
                {"field": "hours", "title": "Hours", "format": ".1f"},
            ],
        },
    }
    _chart(bars, shown[0].profile, spec, max(160, 34 * len(bars)))


def _settings_table(shown: list[SettingView], images: int) -> None:
    table = [
        {
            "": {"trade-off front": "front", "current": "current"}.get(v.role, ""),
            "method": method_of(v.result),
            "parameters": parameters(v.result),
            "groups": v.result.groups_per_pool,
            "individual": 100 * v.result.individual_share,
            "lower bound": v.result.min_actions_pc,
            "actions": v.result.actions_pc,
            "min seconds": v.mine.min_seconds_pc,
            "seconds": v.mine.seconds_pc,
            "hours": v.hours(images),
            "recall": percent(v.mine.recall),
            "uncorrected": percent(v.result.recall_uncorrected),
        }
        for v in shown
    ]
    number = st.column_config.NumberColumn
    labelled_columns = ["actions", "seconds", "recall", "uncorrected"]
    st.dataframe(
        table,
        hide_index=True,
        height=36 * (len(shown) + 1) + 2,
        column_order=[
            "",
            "method",
            "parameters",
            "groups",
            "individual",
            "lower bound",
            "min seconds",
            *labelled_columns,
            "hours",
        ],
        column_config={
            "": st.column_config.TextColumn(width="small"),
            "method": st.column_config.TextColumn("Method"),
            "parameters": st.column_config.TextColumn(
                "Parameters",
                help="max: largest group; k: number of groups; min: smallest group; no close neighbour: "
                "percentile of images judged one by one for lack of a close neighbour; top: images most "
                "similar to the query judged one by one",
            ),
            "groups": number("Groups / query", format="%.1f"),
            "individual": number("Judged one by one", format="%.1f %%"),
            "lower bound": number("Min. actions / image", format="%.2f"),
            "actions": number("Actions / image", format="%.2f"),
            "min seconds": number("Min. time / image (s)", format="%.2f"),
            "seconds": number("Time / image (s)", format="%.2f"),
            "hours": number("Total time (h)", format="%.1f"),
            "recall": number("Recall", format="%.1f %%"),
            "uncorrected": number("Recall, uncorrected", format="%.1f %%"),
        },
    )
