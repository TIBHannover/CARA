"""What annotators do; and the images, for every member of a study.

Their queue, a query's groups, labelling, splits, review, similar images, Suggest mode.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from cara.api.auth import CurrentUserDep, get_study_role, require_annotator
from cara.api.deps import AnnotationDep, ImagesDep, SimilarityDep
from cara.api.schemas import JudgeIn, SplitIn
from cara.services.annotation import QueryView, QueueItem
from cara.services.similarity import Suggestions

router = APIRouter(
    prefix="/studies/{study_id}", tags=["annotation"], dependencies=[Depends(require_annotator)]
)
images_router = APIRouter(
    prefix="/studies/{study_id}", tags=["annotation"], dependencies=[Depends(get_study_role)]
)
"""Thumbnails are for every member: admins see them on the Results and Studies pages too."""


@router.get("/queue")
def queue(study_id: int, user: CurrentUserDep, annotation: AnnotationDep) -> list[QueueItem]:
    """Return the annotator's queries, pilot queries first, each with how far they got."""
    return annotation.queue(user, study_id)


@router.get("/queries/{query_id}")
def query_view(study_id: int, query_id: int, user: CurrentUserDep, annotation: AnnotationDep) -> QueryView:
    """Return a query as the annotator sees it: its groups, its images judged alone, their labels."""
    return annotation.query_view(user, study_id, query_id)


@router.get("/queries/{query_id}/similar")
def similar(
    study_id: int,
    query_id: int,
    to: Annotated[list[int], Query(min_length=1)],
    user: CurrentUserDep,
    similarity: SimilarityDep,
    k: Annotated[int, Query(ge=1, le=500)] = 12,
) -> list[int]:
    """Return the pool images most like any of `to`, most similar first.

    One image's neighbours, or, when `to` holds the images labelled relevant, where a missed relevant image is
    likely to be.
    """
    return similarity.similar(user, study_id, query_id, to, k)


@router.get("/queries/{query_id}/suggestions")
def suggestions(study_id: int, query_id: int, user: CurrentUserDep, similarity: SimilarityDep) -> Suggestions:
    """Return Suggest mode's suggestions: the unjudged images clustered around the annotator's seeds."""
    return similarity.suggestions(user, study_id, query_id)


@router.post("/queries/{query_id}/judgments", status_code=204)
def judge(
    study_id: int, query_id: int, body: JudgeIn, user: CurrentUserDep, annotation: AnnotationDep
) -> None:
    """Label pool images; the first judgment of an annotation query locks the study."""
    annotation.judge(user, study_id, query_id, body.member_ids, body.label, body.source, body.group_position)


@router.post("/queries/{query_id}/split")
def split(
    study_id: int, query_id: int, body: SplitIn, user: CurrentUserDep, annotation: AnnotationDep
) -> list[list[int]]:
    """Split a group in two; returns the halves."""
    return annotation.split(user, study_id, query_id, body.member_ids)


@router.post("/queries/{query_id}/split/undo")
def undo_split(study_id: int, query_id: int, user: CurrentUserDep, annotation: AnnotationDep) -> list[int]:
    """Merge back the most recent split of this query that is not undone yet; returns its members."""
    return annotation.undo_split(user, study_id, query_id)


@router.post("/queries/{query_id}/review", status_code=204)
def finish_review(study_id: int, query_id: int, user: CurrentUserDep, annotation: AnnotationDep) -> None:
    """Mark the query's review as done; 409 while images are unjudged."""
    annotation.finish_review(user, study_id, query_id)


@images_router.get("/images/{image_id}", response_class=Response)
def image(
    study_id: int,
    image_id: int,
    size: Annotated[int, Query(ge=32, le=2048)],
    images: ImagesDep,
    square: Annotated[bool, Query()] = False,
) -> Response:
    """Return a thumbnail of one of the study's images, cached by the browser for a day."""
    content = images.thumbnail(study_id, image_id, size, square)
    return Response(content, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
