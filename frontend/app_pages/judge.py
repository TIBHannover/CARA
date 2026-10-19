"""The judge page: an annotator's queries, one at a time, in Judge, Suggest or Review mode."""

import streamlit as st

import styles
from components import queries, query_panel, tours
from components.feedback import show_toasts
from components.judging import judging
from components.modes import grouped, review, suggest
from state import thumbnail_store, thumbnails

ctx = judging()
settings = ctx.settings
styles.labels(ctx.offered)
styles.judge_page()
show_toasts()

queue = ctx.api.queue(ctx.study.id)
if not queue:
    st.info("No queries are assigned to you in this study.")
    st.stop()
finished, to_review = queries.completion(ctx, queue)

left, right = st.columns([1, 4], gap="medium")
with left:
    view, mode, following = query_panel.render(ctx, queue, finished, to_review)
grouped.set_up_groups(view, settings.display.group_order)
thumbs = thumbnails(
    ctx.token, ctx.study.id, tuple(m.image_id for m in view.members), settings.display.thumb_px, True
)

with right:
    if mode == "Review":
        review.render(ctx, view, thumbs)
    elif mode == "Suggest":
        suggest.render(ctx, view, thumbs)
    else:
        grouped.render(ctx, view, thumbs)

if following is not None:
    thumbnail_store().prefetch_query(
        ctx.token, ctx.study.id, following.query_id, settings.display.thumb_px, settings.display.query_px
    )

tours.judge(mode, view.is_pilot)
