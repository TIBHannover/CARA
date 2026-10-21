"""Everything a user can configure in a study, from YAML or the admin pages.

The API's deployment settings, from the environment, are in `cara.config`.
"""

from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cara.grouping import GroupingSettings
from cara.grouping.agglomerative import Agglomerative

ENCODER_NAME = r"^[A-Za-z0-9._:/-]+$"
"""The characters an encoder name may use: it becomes part of an index name in the database."""


class Frozen(BaseModel):
    """A settings model that can't change after it is made and rejects unknown keys.

    A typo in a settings file then fails instead of being ignored.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Label(Frozen):
    """One answer an annotator can give for an image.

    Attributes:
        grade: The relevance written to the qrels; 1 or more counts as relevant everywhere else in CARA. None
            means the label counts as judged but is left out of the qrels (Unsure).
        short: A shorter form of the name, where space is tight (the Disagreements view); the name when not
            set.
        icon: A Material Symbols name (fonts.google.com/icons), such as `check`, `close` or `help`; when not
            set, chosen from the grade.
        offered: Whether annotators can choose it. Only a label without a grade can be switched off; images
            that already have it keep it.
    """

    name: str
    grade: int | None
    colour: str
    short: str | None = None
    icon: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    offered: bool = True


class PoolSettings(Frozen):
    """Which images each query is judged against.

    Attributes:
        source: `knn`: the query's nearest neighbours in the corpus; `file`: the candidates in the query file;
            `random`: `k` corpus images drawn at random per query, a baseline that no encoder shapes.
        k: Images per pool for `knn` and `random`; for `knn`, None means the whole corpus, up to `max_size`.
            Must be None for `file`.
        max_size: The most images a pool can hold.
        encoders: For `knn`, the encoders whose nearest neighbours are fused into one pool (reciprocal rank
            fusion, `cara.core.fusion`); empty means the study's own encoder. Pooling with several encoders
            keeps the pool from favouring the images one encoder likes.
        seed: For `random`, the seed of the draws; each query draws from it and its own id.
    """

    source: Literal["knn", "file", "random"] = "knn"
    k: int | None = Field(default=200, ge=1)
    max_size: int = Field(default=1000, ge=2)
    encoders: list[Annotated[str, Field(pattern=ENCODER_NAME)]] = Field(default_factory=list)
    seed: int = 0

    @model_validator(mode="after")
    def _fits_source(self) -> Self:
        if self.source == "file" and self.k is not None:
            raise ValueError(
                f"pool.k ({self.k}) applies to sources 'knn' and 'random'; set k: null for 'file'"
            )
        if self.source == "random" and self.k is None:
            raise ValueError("pool.k is needed for source 'random': how many images to draw per query")
        if self.encoders and self.source != "knn":
            raise ValueError(f"pool.encoders apply to source 'knn' only, not {self.source!r}")
        return self


class SoloSettings(Frozen):
    """Which images are judged one by one because they have no close neighbour.

    Attributes:
        percentile: An image whose nearest neighbour is less similar than this percentile of the pool's
            nearest-neighbour similarities is judged on its own; 0 turns the rule off.
    """

    percentile: float = Field(default=10.0, ge=0.0, le=100.0)


class ReviewSettings(Frozen):
    """The review round after a pool is labelled.

    Attributes:
        required: Whether a query counts as done only after its review.
        negatives_shown: How many Not Relevant images the review shows, those most like the Relevant ones
            first.
    """

    enabled: bool = True
    required: bool = False
    negatives_shown: int = Field(default=60, ge=1)


class SuggestSettings(Frozen):
    """Suggest mode: labels proposed for images clearly similar to ones already labelled.

    Once an annotator has marked enough images Not Relevant one by one (the seeds), every unjudged image
    clearly similar to a seed gets that seed's label as a suggestion, to accept or override.

    Attributes:
        min_seeds: Not Relevant seeds needed before suggestions start; Relevant seeds are optional.
        min_pool_size: Suggest mode is offered only for pools at least this large (deep pools, whole-corpus
            studies); 0 means every pool.
        min_margin: How much more similar an image must be to its seed than to any image of the other label
            (cosine similarity).
        merge_percentile: Seeds with the same label count as one starting point if they are at least as
            similar as this percentile of nearest-neighbour pairs in the pool (50: a typical nearest
            neighbour; 100: never merge).
    """

    enabled: bool = False
    min_seeds: int = Field(default=2, ge=1)
    min_pool_size: int = Field(default=0, ge=0)
    min_margin: float = Field(default=0.05, ge=0.0, le=1.0)
    merge_percentile: float = Field(default=50.0, ge=0.0, le=100.0)


class DisplaySettings(Frozen):
    """How the judge page looks; each annotator can change the images per row for themselves.

    Attributes:
        thumb_px: Thumbnail size in pixels.
        query_px: Query image size in pixels.
        cols: Images per row.
        drag_and_drop: Whether review mode lets annotators drag an image to another label (the buttons keep
            working either way).
        split: Whether annotators may split a group in two, and undo it.
        group_order: The order of the groups: by mean similarity to the query or by size, each descending or
            ascending (`_asc`).
    """

    thumb_px: int = Field(default=320, ge=64)
    query_px: int = Field(default=640, ge=64)
    cols: int = Field(default=5, ge=1, le=12)
    drag_and_drop: bool = True
    split: bool = True
    group_order: Literal["similarity", "similarity_asc", "size", "size_asc"] = "similarity"


class Example(Frozen):
    """An example in the annotation guidelines: a judged pool image, the label it should get, and why.

    The query's image and text are kept with it, so annotators see the example whatever queries they have.

    Attributes:
        member_id: The pool image (member) the example shows.
        image_id: Its image.
        query_image_id: The image of the query it was judged for, if the query has one.
        query_text: The text of that query, if it has one.
        note: Why the image gets the label, in a sentence or two.
    """

    member_id: int
    image_id: int
    query_image_id: int | None = None
    query_text: str | None = None
    label: str
    note: str = ""


class Guidelines(Frozen):
    """What annotators read before and while judging: Markdown text and examples, typically from the pilot."""

    text: str = ""
    examples: list[Example] = Field(default_factory=list)


class StudySettings(Frozen):
    """A study's settings: its labels, pools, grouping, review, display and Suggest mode.

    The first judgment of an annotation query fixes everything except the fields in `EDITABLE_AFTER_LOCK` and
    the label colours, short names and icons (see `locked_changes`).

    Attributes:
        labels: At least two, with unique names.
        encoder: The encoder whose embeddings group the pools and build them for `knn`, such as
            `dinov3` or `siglip2:google/siglip2-base-patch16-224` (see `cara.encoders`). None: a study
            without embeddings, judged one image at a time in pool order; then the pools are the given
            candidates or a random draw, and grouping, Suggest mode, similar images and the settings
            simulator are off.
        top_k_individual: The images most similar to the query that are judged one by one, outside any group.
        order: How images are ranked: by similarity to the query, or in the pool's own rank order (for
            queries without an embedding of their own).
        query_order: `shuffled`: each annotator gets the queries in their own fixed random order, which avoids
            order effects; `listed`: everyone in the order of the query file.
        annotators_per_query: How many annotators judge each annotation query.
        guidelines: What annotators read; it can change at any time.
        demo: Whether this is a sample study to try the tool on, listed apart below the real studies.
    """

    name: str
    labels: list[Label] = Field(min_length=2)
    encoder: str | None = Field(pattern=ENCODER_NAME)
    pool: PoolSettings = PoolSettings()
    grouping: GroupingSettings = Agglomerative(method="agglomerative")
    solo: SoloSettings = SoloSettings()
    top_k_individual: int = Field(default=0, ge=0)
    order: Literal["similarity", "pool_rank"] = "similarity"
    query_order: Literal["shuffled", "listed"] = "shuffled"
    review: ReviewSettings = ReviewSettings()
    annotators_per_query: int = Field(default=1, ge=1)
    display: DisplaySettings = DisplaySettings()
    suggest: SuggestSettings = SuggestSettings()
    guidelines: Guidelines = Guidelines()
    demo: bool = False

    @model_validator(mode="after")
    def _unique_labels(self) -> Self:
        names = [label.name for label in self.labels]
        if len(set(names)) != len(names):
            raise ValueError(f"label names must be unique, got {names}")
        if hidden := [label.name for label in self.labels if not label.offered and label.grade is not None]:
            raise ValueError(
                f"only labels without a grade can be switched off (offered: false), not {hidden}"
            )
        return self

    @model_validator(mode="after")
    def _encoder_free(self) -> Self:
        if self.encoder is not None:
            return self
        needs = [
            what
            for what, needed in (
                (f"grouping (method {self.grouping.method!r}; use 'none')", self.grouping.method != "none"),
                ("nearest-neighbour pools (pool.source 'knn')", self.pool.source == "knn"),
                ("ordering by similarity (order 'similarity'; use 'pool_rank')", self.order == "similarity"),
                ("Suggest mode (suggest.enabled)", self.suggest.enabled),
            )
            if needed
        ]
        if needs:
            raise ValueError(f"encoder is null, but these need one: {'; '.join(needs)}")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Read a study's settings from a YAML file.

        Raises:
            ValueError: The file's settings are invalid; the message names the file and every field at fault.
        """
        try:
            return cls.model_validate(yaml.safe_load(path.read_text()))
        except ValidationError as error:
            raise ValueError(f"{path}: invalid study settings\n{error}") from error


STANDARD_LABELS = (
    Label(name="Relevant", grade=1, colour="#2ecc71", short="✓"),
    Label(name="Not Relevant", grade=0, colour="#e74c3c", short="✗"),
    Label(name="Unsure", grade=None, colour="#f1c40f", short="?"),
)
"""The labels of a study created on the New study page."""

EDITABLE_AFTER_LOCK = frozenset(
    {"name", "annotators_per_query", "display", "query_order", "demo", "suggest", "guidelines"}
)
"""The study settings that can still change after the first judgment."""


def label_meaning(settings: StudySettings) -> list[tuple[str, int | None]]:
    """Return each label's name and grade: what judgments mean, as opposed to how labels look."""
    return [(label.name, label.grade) for label in settings.labels]


def locked_changes(old: StudySettings, new: StudySettings) -> list[str]:
    """Return the settings that `new` changes but a study that has started can't change.

    Labels count as changed only when a name or grade differs; colours, short names and icons can change.
    """
    changed = [
        field
        for field in StudySettings.model_fields
        if field not in EDITABLE_AFTER_LOCK
        and field != "labels"
        and getattr(old, field) != getattr(new, field)
    ]
    return changed + (["labels"] if label_meaning(old) != label_meaning(new) else [])
