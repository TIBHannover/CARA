"""Simulation step 6: pick a setting, see it for every annotator type, take it to the Annotation tab."""

import streamlit as st

import styles
from client import CaraClient, SettingResult, Study
from components.feedback import percent
from components.simulator.results import RECOMMENDED, duration, label, rule, voters
from components.study import tabs
from components.study.settings import Proposal, proposal_key


def choose(
    api: CaraClient, study: Study, results: list[SettingResult], images: int, tolerance: float
) -> None:
    """Pick a setting, compare it with one at a time for every annotator type, and use it for the study."""
    with styles.section("apply", "6 · Choose a setting"):
        default = next(
            (i for i, r in enumerate(results) if r.recommended),
            next((i for i, r in enumerate(results) if r.is_current), 0),
        )
        index: int = st.selectbox(
            "Setting",
            range(len(results)),
            index=default,
            format_func=lambda i: _option(results[i]),
            key=f"simulation-setting:{study.id}:{len(results)}",
            help=f"★ recommended: {rule(tolerance)}.",
        )
        chosen = results[index]
        reference = next(r for r in results if r.strategy == "one at a time")
        st.caption(_verdict(chosen, results, tolerance))
        _comparison(chosen, reference, images, tolerance)
        if study.locked:
            st.caption("Judging has started, so the grouping can no longer change.")
            return
        proposal = Proposal(label(chosen), chosen.grouping, chosen.solo_percentile, chosen.top_k_individual)
        st.button(
            "Use this setting",
            icon=":material/arrow_forward:",
            type="primary",
            help="Opens the Annotation tab with it filled in, to check and save there.",
            on_click=_propose,
            args=(study.id, proposal),
        )


def _option(result: SettingResult) -> str:
    marks = [RECOMMENDED] * result.recommended + ["current"] * result.is_current
    return " · ".join([label(result), *marks])


def _verdict(chosen: SettingResult, results: list[SettingResult], tolerance: float) -> str:
    """Say in one line why the chosen setting is, or isn't, the recommended one."""
    structure = (
        f"{chosen.groups_per_pool:.1f} groups per query · {chosen.individual_share:.0%} of the images "
        "judged on their own. "
        if chosen.strategy != "one at a time"
        else ""
    )
    deciding = voters(results)
    if chosen.recommended:
        why = f"Recommended: {rule(tolerance)}."
    elif not deciding or not any(r.recommended for r in results):
        why = "No recommendation without labels."
    else:
        losing = [chosen.annotators[i].name for i in deciding if chosen.annotators[i].keeps_recall is False]
        why = (
            f"Not recommended: {', '.join(losing)} lose more than {100 * tolerance:g} recall points."
            if losing
            else "Keeps recall for every annotator type, but the recommended setting is faster."
        )
    return structure + why + " The grouping is one for the whole study, whatever the annotator type."


def _comparison(chosen: SettingResult, reference: SettingResult, images: int, tolerance: float) -> None:
    """One row per annotator type: the chosen setting's time and recall, and the change from one at a time."""
    rows = [
        {
            "type": mine.name,
            "keeps": {True: "✓", False: "✗", None: "bound"}[mine.keeps_recall],
            "seconds": mine.seconds_pc,
            "time change": 100 * (mine.seconds_pc / base.seconds_pc - 1)
            if mine.seconds_pc is not None and base.seconds_pc
            else None,
            "total": duration(mine.seconds_pc * images) if mine.seconds_pc is not None else None,
            "recall": percent(mine.recall),
            "recall change": 100 * (mine.recall - base.recall)
            if mine.recall is not None and base.recall is not None
            else None,
        }
        for mine, base in zip(chosen.annotators, reference.annotators, strict=True)
    ]
    number = st.column_config.NumberColumn
    st.dataframe(
        rows,
        hide_index=True,
        column_config={
            "type": st.column_config.TextColumn("Annotator type"),
            "keeps": st.column_config.TextColumn(
                f"Within {100 * tolerance:g} pt",
                width="small",
                help=f"Recall within {100 * tolerance:g} points of one at a time. Perfect and Group-only are "
                "bounds and don't count toward the recommendation.",
            ),
            "seconds": number("Time / image (s)", format="%.2f"),
            "time change": number("Time vs one at a time", format="%+.0f %%"),
            "total": st.column_config.TextColumn(f"All {images:,} images"),
            "recall": number("Recall", format="%.1f %%"),
            "recall change": number("Recall vs one at a time", format="%+.1f pt"),
        },
    )


def _propose(study_id: int, proposal: Proposal) -> None:
    st.session_state[proposal_key(study_id)] = proposal
    st.session_state[tabs.KEY] = "Annotation"
