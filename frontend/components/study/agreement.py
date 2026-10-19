"""Results tab, top: the final numbers, agreement, and adjudication of disagreements."""

import streamlit as st

import styles
from client import AgreementReport, CaraClient, Study
from components.agreement_scale import KAPPA, alpha_metric, legend, meaning
from components.feedback import count
from state import thumbnails


def render(api: CaraClient, study: Study) -> None:
    """Draw the Results tab's numbers: an overview, agreement, and the disagreements to settle."""
    report = api.agreement(study.id)
    with styles.section("results-overview", "Overview"):
        _overview(api, study, report)
    with styles.section("results-agreement", "Agreement"):
        _agreement(report)
    with styles.section("results-disagreements", "Disagreements"):
        _disagreements(api, study, report)


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


def _disagreements(api: CaraClient, study: Study, report: AgreementReport) -> None:
    settings = study.settings
    styles.labels(settings.labels)
    short_of = {label.name: label.short or label.name for label in settings.labels}
    open_queries = [q for q in report.queries if q.disagreements]
    if not open_queries:
        st.success("All annotators agree on every image they share.", icon=":material/check:")
        return
    by_id = {q.query_id: q for q in open_queries}
    query_id = st.selectbox(
        "Query",
        list(by_id),
        format_func=lambda q: (
            f"{by_id[q].external_id} · {by_id[q].disagreements} disagreements · {by_id[q].adjudicated} "
            f"resolved"
        ),
    )
    items = api.disagreements(study.id, query_id)
    thumbs = thumbnails(
        st.session_state.token, study.id, tuple(i.image_id for i in items), settings.display.thumb_px, True
    )
    st.caption("Pick the final label for each image; it overrides the majority in the consensus qrels.")

    def on_adjudicate(member_id: int) -> None:
        """Save the admin's final label for an image (the label control's callback)."""
        label = st.session_state[f"adjudicate:{member_id}"]
        if label is not None:
            api.adjudicate(study.id, member_id, label)

    label_names = [label.name for label in settings.labels]
    cols = 5
    for start in range(0, len(items), cols):
        for column, item in zip(st.columns(cols, gap="small"), items[start : start + cols], strict=False):
            with column, styles.card(f"disagreement-{item.member_id}"):
                st.image(thumbs[item.image_id], width="stretch")
                st.caption(
                    " · ".join(f"{user}: {short_of[label]}" for user, label in sorted(item.labels.items()))
                )
                st.segmented_control(
                    item.doc_id,
                    label_names,
                    format_func=short_of.__getitem__,
                    default=item.adjudicated,
                    key=f"adjudicate:{item.member_id}",
                    label_visibility="collapsed",
                    on_change=on_adjudicate,
                    args=(item.member_id,),
                )
