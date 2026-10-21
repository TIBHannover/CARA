"""Simulation step 6: pick a setting, compare it with one image at a time, take it to the Annotation tab."""

import streamlit as st

import styles
from client import CaraClient, SettingResult, Study
from components.simulator.results import label, views
from components.study import tabs
from components.study.settings import Proposal, proposal_key


def choose(api: CaraClient, study: Study, results: list[SettingResult], profile: int) -> None:
    """Pick a setting, see it next to one image at a time, and use it for the study."""
    with styles.section("apply", "6 · Choose a setting"):
        shown = views(results, profile)
        index: int = st.selectbox(
            "Setting",
            range(len(shown)),
            index=next((i for i, r in enumerate(results) if r.is_current), 0),
            format_func=lambda i: ("● " if shown[i].on_front else "") + shown[i].label,
            help="● on the trade-off front",
        )
        chosen, reference = results[index], next(r for r in results if r.strategy == "one at a time")
        mine, base = chosen.annotators[profile], reference.annotators[profile]
        with st.container(horizontal=True):
            if mine.seconds_pc and base.seconds_pc:
                st.metric(
                    "Time per image",
                    f"{mine.seconds_pc:.2f} s",
                    delta=f"{mine.seconds_pc / base.seconds_pc - 1:+.0%} vs one at a time",
                    delta_color="inverse",
                    border=True,
                )
            if mine.recall is not None and base.recall is not None:
                st.metric(
                    "Recall",
                    f"{mine.recall:.1%}",
                    delta=f"{mine.recall - base.recall:+.1%} vs one at a time",
                    border=True,
                )
            st.metric("Groups per query", f"{chosen.groups_per_pool:.1f}", border=True)
            st.metric("Ungrouped", f"{chosen.individual_share:.0%}", border=True)
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


def _propose(study_id: int, proposal: Proposal) -> None:
    st.session_state[proposal_key(study_id)] = proposal
    st.session_state[tabs.KEY] = "Annotation"
