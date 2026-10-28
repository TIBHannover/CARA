"""Simulation step 5: the recommendation, then the results for one annotator type at a time: time against
recall, total time, and every setting in a table."""

from collections.abc import Mapping
from dataclasses import dataclass

import streamlit as st

import styles
from client import AnnotatorResult, SettingResult
from components.feedback import count, percent
from components.simulator.run import SimulationRun

DEFINITIONS = """
- **★ Recommended**: the fastest setting that keeps every annotator type's recall within the tolerance of
  one at a time. Perfect and Group-only don't count. A suggestion: which setting to use is your call.
- **One at a time**: every image judged on its own (◆, dashed line); the reference for time and recall.
- **Bounds**: Perfect never errs, so it shows the fewest actions a setting allows; Group-only labels each
  group by one glance and never corrects an image, so it shows how much a setting relies on corrections.
- **Groups / query**: groups an annotator sees for one query, on average.
- **Ungrouped**: share of the images outside any group: images without a close neighbour, the images
  most similar to the query (top k), and images the method leaves ungrouped.
- **Min. actions / image**: one action per group plus one per individually judged image, divided by the
  number of images; the fewest possible, reached only if every group is all relevant or all not relevant.
- **Actions / image**: actions a perfect annotator needs, including corrections of single images inside
  mixed groups.
- **Min. time / image**: the time of the selected type if every group were all relevant or all not
  relevant: one group action and a glance per grouped image, a full look per individually judged image;
  a lower bound on the time.
- **Time / image**: time of the selected annotator type, from its time per action.
- **Total time**: time per image × every image in the study, for one annotator, one pass.
- **Recall**: share of the relevant images that the selected annotator type labels relevant.
- **Recall, uncorrected**: recall if an annotator only labels groups and never corrects a single image.
"""

RECOMMENDED = "★ recommended"
ROLES = {
    "one at a time": "#18181B",
    "recommended": "#4F46E5",
    "current": "#0EA5E9",
    "other settings": "#D4D4D8",
}
STAR = (
    "M0,-1L0.225,-0.309L0.951,-0.309L0.363,0.118L0.588,0.809L0,0.382L-0.588,0.809L-0.363,0.118"
    "L-0.951,-0.309L-0.225,-0.309Z"
)
ROLE_SCALE = {"domain": list(ROLES), "range": list(ROLES.values())}
SHAPE_SCALE = {"domain": list(ROLES), "range": ["diamond", STAR, "circle", "circle"]}
SIZE_SCALE = {"domain": list(ROLES), "range": [150, 320, 150, 110]}


def rule(tolerance: float) -> str:
    """Return the recommendation rule in words, for captions and help texts."""
    return (
        f"the fastest setting that keeps every annotator type within {100 * tolerance:g} recall points of "
        "one at a time (Perfect and Group-only don't count)"
    )


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


@dataclass(frozen=True, slots=True)
class SettingView:
    """One setting as seen for one annotator type."""

    result: SettingResult
    profile: int

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
        """Return how the charts mark the setting: one at a time, recommended, current, or other."""
        if self.result.strategy == "one at a time":
            return "one at a time"
        if self.result.recommended:
            return "recommended"
        return "current" if self.result.is_current else "other settings"

    @property
    def tagged(self) -> str:
        """Return the label with the setting's marks, for chart axes."""
        marks = ["★ "] * self.result.recommended + ["current · "] * self.result.is_current
        return "".join(marks) + self.label

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
    """Return each setting as seen for one annotator type."""
    return [SettingView(r, profile) for r in results]


def voters(results: list[SettingResult]) -> list[int]:
    """Return the annotator types the recommendation is based on: all but the bounds."""
    baseline = next(r for r in results if r.strategy == "one at a time")
    return [i for i, a in enumerate(baseline.annotators) if a.keeps_recall is not None]


def duration(seconds: float) -> str:
    """Return a duration in minutes below an hour, else in hours ("40 min", "2.5 h")."""
    return f"{seconds / 60:.0f} min" if seconds < 3600 else f"{seconds / 3600:.1f} h"


def show(run: SimulationRun, study_images: int) -> int:
    """Draw the recommendation and the results; return the annotator type picked to view them for."""
    results: list[SettingResult] = run.event.results or []
    images = run.event.images_in_study or study_images
    tolerance = run.event.recall_tolerance or 0.02
    names = [a.name for a in results[0].annotators]
    deciding = voters(results)
    with styles.section("results", "5 · Results"):
        st.caption(
            f"{run.source} · {count(results[0].queries, 'query')} replayed · "
            f"{count(len(results), 'setting')} · {count(len(names), 'annotator type')} · "
            f"ran at {run.when} in {run.seconds:.0f} s"
        )
        _recommendation(results, deciding, images, tolerance)
        profile = 0
        if len(names) > 1:
            styles.profile_bar()
            with st.container(key="profile-bar", horizontal=True, vertical_alignment="center"):
                st.markdown(":material/person: **Results for annotator type**", width="content")
                picked = st.segmented_control(
                    "Results for",
                    names,
                    default=names[0],
                    format_func=lambda n: n if names.index(n) in deciding or not deciding else f"{n} · bound",
                    label_visibility="collapsed",
                )
            profile = names.index(picked or names[0])
        shown = views(results, profile)
        recall_column, time_column = st.columns(2)
        with recall_column:
            st.markdown(f"##### Time against recall · {names[profile]}")
            _time_recall_chart(shown)
            st.caption(
                "One point per setting. Higher finds more relevant images, further left is faster. "
                "◆ and the dashed line: one at a time."
            )
        with time_column:
            st.markdown(f"##### Time for all {images:,} images · {names[profile]}")
            _time_chart(shown, images)
        if deciding and profile not in deciding:
            st.caption(
                f":material/info: {names[profile]} is a bound, not a real annotator: it shows the best or "
                "the worst case and doesn't count toward the recommendation."
            )
        with st.expander("All settings", icon=":material/table:"):
            _settings_table(shown, images)
        with st.expander("Definitions", icon=":material/menu_book:"):
            st.markdown(DEFINITIONS)
    return profile


def _recommendation(results: list[SettingResult], deciding: list[int], images: int, tolerance: float) -> None:
    """Say which setting is recommended and what it saves and costs, for the annotator types that decide."""
    best = next((r for r in results if r.recommended), None)
    if best is None:
        st.info(
            "No recommendation: without labels the simulator can't measure recall. The charts show "
            "effort only.",
            icon=":material/info:",
        )
        return
    who = ", ".join(results[0].annotators[i].name for i in deciding)
    if best.strategy == "one at a time":
        st.warning(
            f"**Recommended: judge one image at a time.** Every grouping setting makes at least one "
            f"annotator type ({who}) lose more than {100 * tolerance:g} recall points.",
            icon=":material/warning:",
        )
        return
    reference = next(r for r in results if r.strategy == "one at a time")
    seconds = [best.annotators[i].seconds_pc or 0.0 for i in deciding]
    base = [reference.annotators[i].seconds_pc or 0.0 for i in deciding]
    mean, base_mean = sum(seconds) / len(seconds), sum(base) / len(base)
    worst = min(
        (best.annotators[i].recall or 0.0) - (reference.annotators[i].recall or 0.0) for i in deciding
    )
    with st.container(border=True, key="recommendation"):
        st.markdown(f"**★ Recommended: {label(best)}**")
        with st.container(horizontal=True):
            st.metric(
                "Time per image",
                f"{mean:.2f} s",
                delta=f"{mean / base_mean - 1:+.0%} vs one at a time" if base_mean else None,
                delta_color="inverse",
                border=True,
            )
            st.metric(
                f"All {images:,} images",
                duration(mean * images),
                delta=f"instead of {duration(base_mean * images)}",
                delta_color="off",
                delta_arrow="off",
                border=True,
            )
            st.metric(
                "Recall, worst type",
                f"{100 * worst:+.1f} pt",
                delta="vs one at a time",
                delta_color="off",
                delta_arrow="off",
                border=True,
                help=f"The smallest recall change across {who}.",
            )
        st.caption(
            f"The fastest setting that keeps every annotator type ({who}) within {100 * tolerance:g} recall "
            "points of one at a time. Perfect and Group-only show the bounds and don't decide. Times are the "
            "mean over these types, for one annotator and one pass. Compare or apply it in step 6."
        )


def _chart(points: list[dict[str, object]], profile: int, spec: Mapping[str, object], height: int) -> None:
    # Streamlit redraws a chart when its spec changes, not when only its data does: hence usermeta.
    st.vega_lite_chart({"usermeta": {"profile": profile}, "data": {"values": points}, **spec}, height=height)


def _time_recall_chart(shown: list[SettingView]) -> None:
    """Draw time against recall, one point per setting: further left is faster, higher finds more."""
    points: list[dict[str, object]] = [
        {"setting": v.tagged, "seconds": v.mine.seconds_pc, "recall": v.mine.recall, "role": v.role}
        for v in shown
        if v.mine.seconds_pc is not None and v.mine.recall is not None
    ]
    reference = [p["recall"] for p in points if p["role"] == "one at a time"]
    recalls = [v.mine.recall for v in shown if v.mine.recall is not None]
    # Equal recalls (the perfect annotator) collapse the axis to one tick: pad it to a visible range.
    pad = max(0.05, (max(recalls) - min(recalls)) * 0.1) if recalls else 0.0
    domain = [max(0.0, min(recalls) - pad), min(1.0, max(recalls) + pad)] if recalls else None
    dots = {
        "mark": {"type": "point", "filled": True, "opacity": 1},
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
                "scale": {"zero": False, "domain": domain} if domain else {"zero": False},
                "title": "Recall · finds more ↑",
                "axis": {"format": ".0%", "tickCount": 5},
            },
            "color": {
                "field": "role",
                "type": "nominal",
                "title": None,
                "scale": ROLE_SCALE,
                "legend": {"orient": "bottom"},
            },
            "shape": {
                "field": "role",
                "type": "nominal",
                "title": None,
                "scale": SHAPE_SCALE,
                "legend": {"orient": "bottom"},
            },
            "size": {"field": "role", "type": "nominal", "scale": SIZE_SCALE, "legend": None},
            "tooltip": [
                {"field": "setting", "title": "Setting"},
                {"field": "seconds", "title": "Time per image (s)", "format": ".2f"},
                {"field": "recall", "title": "Recall", "format": ".1%"},
            ],
        },
    }
    line = {
        "data": {"values": [{"recall": r} for r in reference]},
        "mark": {"type": "rule", "strokeDash": [4, 4], "color": ROLES["one at a time"], "opacity": 0.5},
        "encoding": {"y": {"field": "recall", "type": "quantitative"}},
    }
    _chart(points, shown[0].profile, {"layer": [line, dots]}, 320)


def _time_chart(shown: list[SettingView], images: int) -> None:
    """Hours for one annotator to judge the whole study once, per setting, fastest first, with time saved."""
    base = next((v.mine.seconds_pc for v in shown if v.role == "one at a time"), None)
    bars: list[dict[str, object]] = [
        {
            "setting": v.tagged,
            "hours": v.hours(images),
            "role": v.role,
            "saved": f"{1 - v.mine.seconds_pc / base:.0%} less time"
            if base and v.role != "one at a time"
            else "",
        }
        for v in sorted(shown, key=lambda v: v.mine.seconds_pc or 0.0)
        if v.mine.seconds_pc is not None
    ]
    encoding = {
        "y": {
            "field": "setting",
            "type": "nominal",
            "title": None,
            "sort": None,  # the rows come sorted, fastest first
            "axis": {"labelLimit": 240, "labelOverlap": False},
        },
        "x": {"field": "hours", "type": "quantitative", "title": "Hours, one annotator, one pass"},
    }
    spec = {
        "encoding": encoding,
        "layer": [
            {
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "encoding": {
                    "color": {"field": "role", "type": "nominal", "scale": ROLE_SCALE, "legend": None},
                    "tooltip": [
                        {"field": "setting", "title": "Setting"},
                        {"field": "hours", "title": "Hours", "format": ".1f"},
                    ],
                },
            },
            {
                "mark": {"type": "text", "align": "left", "dx": 6, "color": "#52525B"},
                "encoding": {"text": {"field": "saved"}},
            },
        ],
    }
    _chart(bars, shown[0].profile, spec, max(160, 34 * len(bars)))


def _settings_table(shown: list[SettingView], images: int) -> None:
    table = [
        {
            "": " · ".join([RECOMMENDED] * v.result.recommended + ["current"] * v.result.is_current),
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
            "": st.column_config.TextColumn(width="medium"),
            "method": st.column_config.TextColumn("Method"),
            "parameters": st.column_config.TextColumn(
                "Parameters",
                help="max: largest group; k: number of groups; min: smallest group; no close neighbour: "
                "percentile of images left ungrouped for lack of a close neighbour; top: images most "
                "similar to the query, left ungrouped",
            ),
            "groups": number("Groups / query", format="%.1f"),
            "individual": number("Ungrouped", format="%.1f %%"),
            "lower bound": number("Min. actions / image", format="%.2f"),
            "actions": number("Actions / image", format="%.2f"),
            "min seconds": number("Min. time / image (s)", format="%.2f"),
            "seconds": number("Time / image (s)", format="%.2f"),
            "hours": number("Total time (h)", format="%.1f"),
            "recall": number("Recall", format="%.1f %%"),
            "uncorrected": number("Recall, uncorrected", format="%.1f %%"),
        },
    )
