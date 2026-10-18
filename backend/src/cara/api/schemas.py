"""The API's request and response bodies; their docstrings and field descriptions appear in `/docs`."""

from typing import Literal

from pydantic import BaseModel, Field

from cara.db.models import Role, Source
from cara.services.simulator import SimulatorPlan
from cara.settings import StudySettings


class Token(BaseModel):
    """A login token, to send as `Authorization: Bearer <token>`."""

    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """The logged-in account."""

    username: str
    is_superuser: bool


class QuerySetOut(BaseModel):
    """What a new study can do with one query set of a dataset."""

    name: str
    queries: int
    kind: str = Field(description="`image`, `text` or `image + text`, judged from the first query.")
    given_pools: bool = Field(description="Whether every query comes with its candidates.")
    knn_encoders: list[str] = Field(
        description="Encoders that give every query a vector, so pools can be built by nearest neighbours."
    )
    given_encoders: list[str] = Field(
        description="Encoders that embed every candidate, so the given pools can be grouped."
    )


class DatasetOut(BaseModel):
    """A dataset at a glance, with its query sets."""

    id: int
    name: str
    description: str
    images: int
    query_sets: dict[str, int] = Field(description="Queries per query set.")
    encoders: dict[str, int] = Field(description="Images with an embedding, per encoder.")
    studies: int = Field(description="Studies that use the dataset.")
    sets: list[QuerySetOut] = []


class StudyIn(BaseModel):
    """A new study on a dataset (superusers, the New study page)."""

    name: str = Field(min_length=1, max_length=256)
    dataset_id: int
    query_set: str
    encoder: str
    k: int | None = Field(
        default=None, ge=2, le=5000, description="Nearest neighbours per pool; None: the given candidates."
    )
    queries: int | None = Field(
        default=None, ge=1, description="A random sample of this many queries; None: every query."
    )
    seed: int = Field(default=0, description="The seed of the query sample.")
    unsure: bool = Field(default=True, description="Whether annotators are offered the Unsure label.")
    annotators: list[str] = []
    admins: list[str] = []


class OverviewOut(BaseModel):
    """Where a study stands (see the Studies guide, "Stages")."""

    stage: Literal["new", "pilot", "annotation", "done"]
    pilot_queries: int
    pilot_judged: int = Field(description="Pilot queries fully judged by at least one annotator.")
    annotation_queries: int
    annotation_assignments: int = Field(description="Annotation queries assigned, counted per annotator.")
    annotation_complete: int = Field(description="Of those, fully judged by their annotator.")


class StudyOut(BaseModel):
    """A study as one of its members sees it."""

    id: int
    name: str
    role: Role = Field(description="The caller's role in the study.")
    locked: bool = Field(description="Whether judging has started, which locks most settings.")
    settings: StudySettings
    dataset: str
    query_set: str
    query_kind: Literal["image", "text", "image + text"] | None = None
    cover_image_ids: list[int] = Field(default=[], description="A few images to show on the study's card.")
    overview: OverviewOut | None = Field(default=None, description="For the study's admins only.")


class JudgeIn(BaseModel):
    """Labels for pool images, given in one action."""

    member_ids: list[int] = Field(min_length=1, description="The pool images (members), by id.")
    label: str = Field(description="One of the study's label names.")
    source: Source = Field(
        description="How: `group`, `item` (one by one), `review`, or `suggestion` (Suggest mode)."
    )
    group_position: int | None = Field(
        default=None, description="The group's place on the judge page, from 1; None outside groups."
    )


class SplitIn(BaseModel):
    """A group to split in two."""

    member_ids: list[int] = Field(min_length=2, description="The group's members, by id.")


class PilotIn(BaseModel):
    """Pilot queries to draw, and the annotators to assign them to."""

    count: int | None = Field(
        default=None, ge=1, description="Pilot queries to draw; None: keep them, only assign them again."
    )
    seed: int = 0
    annotators: list[str] = []
    per_query: int = Field(default=1, ge=1, description="Annotators on each pilot query.")


class PilotOut(BaseModel):
    """The pilot queries, and how many queries each annotator now has."""

    queries: list[str]
    assigned: dict[str, int]


class SimulatorIn(BaseModel):
    """A simulator run: the ground truth, how many queries to replay, and what to compare."""

    source: Literal["qrels", "pilot", "none"] = Field(
        description="The ground truth: a qrels file, the judged pilot queries, or none (effort only)."
    )
    qrels: str | None = Field(default=None, description="The qrels file's text, for source `qrels`.")
    max_queries: int = Field(default=30, ge=1, le=500)
    plan: SimulatorPlan | None = Field(default=None, description="What to compare; None: common settings.")
    pilot_users: list[str] | None = Field(
        default=None, description="Whose pilot labels count, for source `pilot`; None: everyone's."
    )


class AdjudicateIn(BaseModel):
    """The final label of one pool image, overriding the annotators' majority."""

    member_id: int
    label: str


class MemberIn(BaseModel):
    """A user to add to a study, or whose role to change."""

    username: str
    role: Role = Role.ANNOTATOR


class UserIn(BaseModel):
    """A new account."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=4)


class AssignIn(BaseModel):
    """The annotation queries' assignment, which starts annotation."""

    per_query: int = Field(ge=1, description="Annotators on each query.")
    annotators: list[str] | None = Field(default=None, description="Who; None: every annotator of the study.")
