"""The Pilot results tab: agreement over the pilot, and how each pilot annotator worked."""

from statistics import median

import streamlit as st

import styles
from client import CaraClient, Study
from components.agreement_scale import KAPPA, alpha_metric, legend, meaning
from components.feedback import percent
from components.study import tabs


def render(api: CaraClient, study: Study) -> None:
    """Draw the Pilot results tab: agreement over the pilot and how each pilot annotator worked."""
    overview = study.overview
    if overview is None or not overview.pilot_queries:
        st.info("No pilot yet.", icon=":material/science:")
        tabs.link("Pilot", "Set up the pilot")
        return
    report = api.pilot_report(study.id)
    if not report.annotators:
        st.info("No pilot judgments yet.", icon=":material/hourglass_empty:")
        return

    with styles.section("pilot-overview", "Overview"):
        timed = [a.seconds_per_image for a in report.annotators if a.seconds_per_image is not None]
        with st.container(horizontal=True):
            st.metric(
                "Pilot queries judged", f"{overview.pilot_judged} of {overview.pilot_queries}", border=True
            )
            st.metric("Annotators", len(report.annotators), border=True)
            alpha_metric(report.alpha, "Over every pilot image with two or more labels.")
            st.metric(
                "Seconds per image",
                f"{median(timed):.1f}" if timed else "–",
                help="Median over the annotators of each one's median time before labelling one image.",
                border=True,
            )
            st.metric("Corrections", sum(a.corrections for a in report.annotators), border=True)

    with styles.section("pilot-annotators", "Per annotator"):
        shared = len(report.annotators) > 1
        st.dataframe(
            [
                {
                    "annotator": a.username,
                    "queries": a.queries_judged,
                    "images": a.images,
                    "s / image": a.seconds_per_image,
                    "minutes": a.active_minutes,
                    "corrections": a.corrections,
                    "relevant": percent(a.relevant_share),
                    "unsure": percent(a.unsure_share),
                    **(
                        {
                            "κ": a.kappa,
                            "agreement": meaning(a.kappa, KAPPA),
                            "correct on relevant": percent(a.acc_relevant),
                            "correct on not relevant": percent(a.acc_nonrelevant),
                        }
                        if shared
                        else {}
                    ),
                }
                for a in report.annotators
            ],
            hide_index=True,
            column_config={
                "queries": st.column_config.NumberColumn(help="pilot queries with every image labelled"),
                "s / image": st.column_config.NumberColumn(
                    format="%.1f", help="median time before labelling one image"
                ),
                "minutes": st.column_config.NumberColumn(format="%.0f", help="active time; breaks left out"),
                "corrections": st.column_config.NumberColumn(help="labels changed after they were given"),
                "relevant": st.column_config.NumberColumn(format="%.0f%%"),
                "unsure": st.column_config.NumberColumn(format="%.0f%%"),
                "κ": st.column_config.NumberColumn(format="%.2f", help="mean Cohen's κ with the others"),
                "correct on relevant": st.column_config.NumberColumn(
                    format="%.0f%%", help="against the other annotators' majority label"
                ),
                "correct on not relevant": st.column_config.NumberColumn(
                    format="%.0f%%", help="against the other annotators' majority label"
                ),
            },
        )
        if shared:
            legend()
        else:
            st.caption("Agreement and accuracy need two or more pilot annotators on the same queries.")
        st.caption(
            ":material/person: Each pilot annotator is also a simulated annotator type in the Simulation, "
            "with their measured speed and accuracy."
        )
    tabs.link("Simulation", "Next: compare settings in the simulation")
