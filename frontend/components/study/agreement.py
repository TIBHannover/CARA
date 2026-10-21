"""Results tab, top: the final numbers, agreement, and the final labels (`components.adjudication`)."""

import streamlit as st

import styles
from client import AgreementReport, CaraClient, Study
from components import adjudication
from components.agreement_scale import KAPPA, alpha_metric, legend, meaning
from components.feedback import count


def render(api: CaraClient, study: Study) -> None:
    """Draw the Results tab's numbers: an overview, agreement, and the final labels to set."""
    report = api.agreement(study.id)
    with styles.section("results-overview", "Overview"):
        _overview(api, study, report)
    with styles.section("results-agreement", "Agreement"):
        _agreement(report)
    with styles.section("results-disagreements", "Final labels"):
        adjudication.final_labels(api, study, report)


def _overview(api: CaraClient, study: Study, report: AgreementReport) -> None:
    overview = study.overview
    rows = [row for row in api.progress(study.id) if row.role == "annotator"]
    with st.container(horizontal=True):
        if overview is not None:
            st.metric(
                "Queries judged",
                f"{overview.annotation_complete} of {overview.annotation_assignments}",
                help="assigned annotation queries with every image labelled",
                border=True,
            )
        st.metric("Judgments", f"{sum(row.judgments for row in rows):,}", border=True)
        st.metric(
            "Time spent",
            f"{sum(row.active_minutes for row in rows) / 60:.1f} h",
            help="all annotators, pilot included; breaks over 10 minutes left out",
            border=True,
        )
        alpha_metric(report.alpha, "Over all images judged by two or more annotators.")
    total = sum(report.label_counts.values())
    if total:
        with st.container(horizontal=True):
            for name, n in report.label_counts.items():
                st.metric(
                    name,
                    f"{n / total:.0%}",
                    f"{n:,} judgments",
                    delta_color="off",
                    delta_arrow="off",
                    border=True,
                )


def _agreement(report: AgreementReport) -> None:
    st.caption(
        f"{report.items_with_two_or_more:,} images with two or more labels · "
        f"{count(sum(q.disagreements > 0 for q in report.queries), 'query')} with disagreements"
    )
    if not report.pairs:
        st.info("Agreement appears once two annotators have judged the same images (two or more per query).")
        return

    st.dataframe(
        [
            {
                "annotators": f"{p.annotator_a} · {p.annotator_b}",
                "shared images": p.shared_items,
                "Cohen's κ": p.kappa,
                "agreement": meaning(p.kappa, KAPPA),
            }
            for p in report.pairs
        ],
        hide_index=True,
        column_config={"Cohen's κ": st.column_config.NumberColumn(format="%.2f")},
    )
    legend()
