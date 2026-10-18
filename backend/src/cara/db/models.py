"""The database tables, as SQLAlchemy models. Every query against them lives in `cara.repositories`."""

from datetime import UTC, datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Role(StrEnum):
    """A person's role in one study: admins manage it, annotators judge it."""

    ADMIN = "admin"
    ANNOTATOR = "annotator"


class Source(StrEnum):
    """How an image got its label.

    With its group, one by one, in the review round, or as an accepted suggestion in Suggest mode. A group
    label never overwrites a label from any other source.
    """

    GROUP = "group"
    ITEM = "item"
    REVIEW = "review"
    SUGGESTION = "suggestion"


class ActionKind(StrEnum):
    """What an annotator did: labelled images, split a group, undid a split, or finished a review."""

    LABEL = "label"
    SPLIT = "split"
    UNSPLIT = "unsplit"
    REVIEW_DONE = "review_done"


def _now() -> datetime:
    return datetime.now(UTC)


def _enum[E: StrEnum](enum: type[E]) -> Enum:
    """Store an enum as its values in a plain string column.

    Not as a Postgres enum type, so adding a value needs no migration of the type.
    """
    return Enum(
        enum, native_enum=False, validate_strings=True, values_callable=lambda e: [m.value for m in e]
    )


class Base(DeclarativeBase):
    """The models' base: every `datetime` column is stored with its time zone."""

    type_annotation_map = {datetime: DateTime(timezone=True)}


class UserRow(Base):
    """An account. The password is stored as a salted scrypt hash (see `cara.services.users`).

    Attributes:
        is_superuser: Whether the account may add datasets, create studies and create accounts.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    salt: Mapped[bytes] = mapped_column(LargeBinary(16))
    password_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    is_superuser: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class DatasetRow(Base):
    """A dataset: its images and query sets, shared by the studies made on it.

    Attributes:
        path: The dataset's folder, relative to `CARA_IMAGE_ROOT`.
    """

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True)
    path: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class StudyRow(Base):
    """A study: one query set of a dataset, judged with its own settings.

    Attributes:
        settings: The `StudySettings`, as JSON.
        query_set: The dataset's query set the study's queries come from.
        locked_at: When the first annotation query was judged, which fixed the pools, the grouping and the
            label meanings; None before.
    """

    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True)
    settings: Mapped[dict[str, object]] = mapped_column(JSONB)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    query_set: Mapped[str] = mapped_column(String(64))
    locked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=_now)
    labels: Mapped[list["LabelRow"]] = relationship(order_by="LabelRow.position")
    dataset: Mapped[DatasetRow] = relationship()


class StudyMemberRow(Base):
    """A person's role in a study."""

    __tablename__ = "study_members"

    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[Role] = mapped_column(_enum(Role))
    user: Mapped[UserRow] = relationship()


class LabelRow(Base):
    """A study's label, so judgments can point at it; its other settings stay in the study's JSON.

    Attributes:
        position: The label's place in the study's list, which sets the order of the buttons.
    """

    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("study_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    grade: Mapped[int | None]
    colour: Mapped[str] = mapped_column(String(32))
    position: Mapped[int]


class ImageRow(Base):
    """An image of a dataset.

    Attributes:
        external_id: The id the dataset's files use for it (`doc_id`).
        path: The image file, relative to the dataset's folder.
        is_corpus: False for an image that is only a query, not something to retrieve.
    """

    __tablename__ = "images"
    __table_args__ = (UniqueConstraint("dataset_id", "external_id"), UniqueConstraint("dataset_id", "path"))

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(Text)
    is_corpus: Mapped[bool] = mapped_column(default=True)


class EmbeddingRow(Base):
    """An image's embedding by one encoder, unit length; images have one row per encoder."""

    __tablename__ = "embeddings"

    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), primary_key=True)
    encoder: Mapped[str] = mapped_column(String(128), primary_key=True)
    vec: Mapped[list[float]] = mapped_column(Vector())


class DatasetQueryRow(Base):
    """A query of a dataset's query set; studies copy the ones they use into `queries`.

    Attributes:
        image_id: The query image, for image and composed queries.
        candidates: The image ids of the query's given pool, in rank order; None when the pool is built from
            nearest neighbours.
    """

    __tablename__ = "dataset_queries"
    __table_args__ = (UniqueConstraint("dataset_id", "query_set", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    query_set: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(256))
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"))
    text: Mapped[str | None] = mapped_column(Text)
    candidates: Mapped[list[int] | None] = mapped_column(JSONB)


class QueryEmbeddingRow(Base):
    """A query's own embedding (text or composed queries); image queries use their image's embedding."""

    __tablename__ = "query_embeddings"

    dataset_query_id: Mapped[int] = mapped_column(ForeignKey("dataset_queries.id"), primary_key=True)
    encoder: Mapped[str] = mapped_column(String(128), primary_key=True)
    vec: Mapped[list[float]] = mapped_column(Vector())


class QueryRow(Base):
    """A study's query.

    Attributes:
        is_pilot: Whether it is a pilot query: judged one image at a time, and never locking the study.
    """

    __tablename__ = "queries"
    __table_args__ = (UniqueConstraint("study_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    dataset_query_id: Mapped[int] = mapped_column(ForeignKey("dataset_queries.id"))
    external_id: Mapped[str] = mapped_column(String(256))
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"))
    text: Mapped[str | None] = mapped_column(Text)
    is_pilot: Mapped[bool] = mapped_column(default=False, server_default=false())
    image: Mapped[ImageRow | None] = relationship()


class PoolRow(Base):
    """The images judged for one query; rebuilt only before the study is locked."""

    __tablename__ = "pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id"), unique=True)
    built_at: Mapped[datetime] = mapped_column(default=_now)
    query: Mapped[QueryRow] = relationship()
    members: Mapped[list["PoolMemberRow"]] = relationship(order_by="PoolMemberRow.rank")


class PoolMemberRow(Base):
    """One image of a pool.

    Attributes:
        rank: Its place in the pool, from 0, by similarity to the query or in the given order.
        score: Its similarity to the query; None when the query has no embedding of its own.
        group_id: The group it is shown in; None when it is judged one by one.
    """

    __tablename__ = "pool_members"
    __table_args__ = (UniqueConstraint("pool_id", "image_id"), UniqueConstraint("pool_id", "rank"))

    id: Mapped[int] = mapped_column(primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("pools.id", ondelete="CASCADE"), index=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"))
    rank: Mapped[int]
    score: Mapped[float | None]
    group_id: Mapped[int | None]
    image: Mapped[ImageRow] = relationship()


class AssignmentRow(Base):
    """A query given to an annotator. Once a study has a pilot, annotators see only their assigned queries."""

    __tablename__ = "assignments"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id"), primary_key=True)


class JudgmentRow(Base):
    """An annotator's current label for one pool image.

    Relabelling updates it; the action log keeps the history.
    """

    __tablename__ = "judgments"
    __table_args__ = (UniqueConstraint("user_id", "pool_member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    pool_member_id: Mapped[int] = mapped_column(ForeignKey("pool_members.id"), index=True)
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id"))
    source: Mapped[Source] = mapped_column(_enum(Source))
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


action_members = Table(
    "action_members",
    Base.metadata,
    Column("action_id", ForeignKey("actions.id"), primary_key=True),
    Column("pool_member_id", ForeignKey("pool_members.id"), primary_key=True),
)


class ActionRow(Base):
    """One click of an annotator, kept for the effort analysis and to replay splits.

    Attributes:
        label_id: The label given; None for a split, an undone split or a finished review.
        source: How the images got the label; None when no label was given.
        group_position: The group's place on the judge page, from 1; None outside groups.
    """

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id"), index=True)
    kind: Mapped[ActionKind] = mapped_column(_enum(ActionKind))
    label_id: Mapped[int | None] = mapped_column(ForeignKey("labels.id"))
    source: Mapped[Source | None] = mapped_column(_enum(Source))
    group_position: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=_now)
    members: Mapped[list[PoolMemberRow]] = relationship(secondary=action_members)


class AdjudicationRow(Base):
    """An admin's final label for a pool image the annotators disagree on.

    It overrides their majority in the consensus qrels.
    """

    __tablename__ = "adjudications"

    pool_member_id: Mapped[int] = mapped_column(ForeignKey("pool_members.id"), primary_key=True)
    label_id: Mapped[int] = mapped_column(ForeignKey("labels.id"))
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=_now)


Index("ix_embeddings_encoder", EmbeddingRow.encoder)
