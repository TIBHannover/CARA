"""Simulation step 1: where the relevance labels to replay against come from."""

from dataclasses import dataclass

import streamlit as st

import styles
from client import CaraClient, SimulatorScope, Study
from components.study import tabs

SOURCES = {"pilot": "Pilot judgments", "qrels": "Relevance file (qrels)"}


@dataclass(frozen=True, slots=True)
class GroundTruth:
    """The labels a simulation replays against, as step 1 chose them.

    Attributes:
        source: `pilot` or `qrels`.
        qrels: The uploaded qrels file's text, for `qrels`.
        pilot_users: Whose pilot labels count; None means everyone's.
        usable: Queries with labels to replay (labelled pilot queries; for a qrels file, counted by the
            server).
    """

    source: str
    qrels: str | None
    pilot_users: list[str] | None
    usable: int

    @property
    def ready(self) -> bool:
        """Return whether there are labels to simulate against."""
        return self.qrels is not None if self.source == "qrels" else self.usable > 0


def _pilot_annotator(name: str, scope: SimulatorScope) -> str:
    found = next(a for a in scope.pilot_annotators if a.username == name)
    agreement = "" if found.kappa is None else f" · κ {found.kappa:.2f}"
    return f"{name} · {found.judged} judged{agreement}"


def ground_truth(api: CaraClient, study: Study, scope: SimulatorScope) -> GroundTruth:
    """Draw step 1: the pilot judgments or a qrels file; return the ground truth chosen."""
    with styles.section("labels", "1 · Ground truth"):
        picked = st.segmented_control(
            "Labels",
            list(SOURCES),
            format_func=SOURCES.__getitem__,
            default="pilot" if scope.pilot_annotators or not api.sample_qrels(study.id) else "qrels",
            label_visibility="collapsed",
        )
        if (picked or "pilot") == "qrels":
            return _qrels(api, study)
        st.caption("Majority label of the chosen pilot annotators, per image.")
        if not scope.pilot_annotators:
            st.warning(
                "No pilot judgments yet. Start a pilot and have its images judged, or use a qrels file.",
                icon=":material/hourglass_empty:",
            )
            tabs.link("Pilot", "Go to the pilot")
            return GroundTruth("pilot", None, None, 0)
        names = [a.username for a in scope.pilot_annotators]
        chosen = st.multiselect(
            "Use the pilot judgments of",
            names,
            default=names,
            format_func=lambda name: _pilot_annotator(name, scope),
            help="κ: agreement with the other pilot annotators on the images they share (1 = always the "
            "same). Leave out someone who often disagrees.",
        )
        if len(chosen) == 1 and len(names) > 1:
            st.info(
                "With one annotator, their mistakes count as the truth: recall then means agreement with "
                "them.",
                icon=":material/info:",
            )
        usable = api.simulator_scope(study.id, chosen).labelled_pilot_queries if chosen else 0
        if usable:
            st.success(
                f"{usable} of {scope.pilot_queries} pilot queries are fully labelled and will be used.",
                icon=":material/check_circle:",
            )
        else:
            st.warning(
                "No pilot query is fully labelled by these annotators yet (every image needs a label, and "
                "ties stay undecided).",
                icon=":material/hourglass_empty:",
            )
        return GroundTruth("pilot", None, None if chosen == names else chosen, usable)


def _qrels(api: CaraClient, study: Study) -> GroundTruth:
    st.caption("A TREC qrels file: `query_id 0 doc_id grade`, grade above 0 = relevant.")
    uploaded = st.file_uploader("Relevance file", type=["qrels", "txt"], label_visibility="collapsed")
    sample = api.sample_qrels(study.id)
    if sample is not None:
        st.download_button(
            "Sample qrels for this study",
            sample,
            file_name="sample.qrels",
            on_click="ignore",
            icon=":material/download:",
            help="Example labels that come with the dataset: download, then upload above to try a run.",
        )
    qrels = uploaded.getvalue().decode() if uploaded else None
    usable = len({line.split()[0] for line in qrels.splitlines() if line.strip()}) if qrels else 0
    return GroundTruth("qrels", qrels, None, usable)
