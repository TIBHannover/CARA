"""The initial schema: CARA's tables as of the first release, in one migration.

Revision ID: d792db67105e
Revises:
Create Date: 2026-10-18 15:35:56.320271

The per-encoder HNSW indexes on `embeddings` are not made here: `cara.repositories.images.ensure_hnsw_index`
creates each one when an encoder's embeddings are first stored.
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d792db67105e"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the pgvector extension and every table."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("salt", sa.LargeBinary(length=16), nullable=False),
        sa.Column("password_hash", sa.LargeBinary(length=64), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("is_corpus", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "external_id"),
        sa.UniqueConstraint("dataset_id", "path"),
    )
    op.create_index(op.f("ix_images_dataset_id"), "images", ["dataset_id"], unique=False)
    op.create_table(
        "studies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("query_set", sa.String(length=64), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_studies_dataset_id"), "studies", ["dataset_id"], unique=False)
    op.create_table(
        "dataset_queries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("query_set", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "query_set", "external_id"),
    )
    op.create_index(op.f("ix_dataset_queries_dataset_id"), "dataset_queries", ["dataset_id"], unique=False)
    op.create_table(
        "embeddings",
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("encoder", sa.String(length=128), nullable=False),
        sa.Column("vec", pgvector.sqlalchemy.vector.VECTOR(), nullable=False),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
        ),
        sa.PrimaryKeyConstraint("image_id", "encoder"),
    )
    op.create_index("ix_embeddings_encoder", "embeddings", ["encoder"], unique=False)
    op.create_table(
        "labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("study_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("colour", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "name"),
    )
    op.create_index(op.f("ix_labels_study_id"), "labels", ["study_id"], unique=False)
    op.create_table(
        "study_members",
        sa.Column("study_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Enum("admin", "annotator", name="role", native_enum=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("study_id", "user_id"),
    )
    op.create_table(
        "queries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("study_id", sa.Integer(), nullable=False),
        sa.Column("dataset_query_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("is_pilot", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_query_id"],
            ["dataset_queries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
        ),
        sa.ForeignKeyConstraint(
            ["study_id"],
            ["studies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "external_id"),
    )
    op.create_index(op.f("ix_queries_study_id"), "queries", ["study_id"], unique=False)
    op.create_table(
        "query_embeddings",
        sa.Column("dataset_query_id", sa.Integer(), nullable=False),
        sa.Column("encoder", sa.String(length=128), nullable=False),
        sa.Column("vec", pgvector.sqlalchemy.vector.VECTOR(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_query_id"],
            ["dataset_queries.id"],
        ),
        sa.PrimaryKeyConstraint("dataset_query_id", "encoder"),
    )
    op.create_table(
        "actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("query_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("label", "split", "unsplit", "review_done", name="actionkind", native_enum=False),
            nullable=False,
        ),
        sa.Column("label_id", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("group", "item", "review", "suggestion", name="source", native_enum=False),
            nullable=True,
        ),
        sa.Column("group_position", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
        ),
        sa.ForeignKeyConstraint(
            ["query_id"],
            ["queries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_actions_query_id"), "actions", ["query_id"], unique=False)
    op.create_index(op.f("ix_actions_user_id"), "actions", ["user_id"], unique=False)
    op.create_table(
        "assignments",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("query_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["query_id"],
            ["queries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "query_id"),
    )
    op.create_table(
        "pools",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query_id", sa.Integer(), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["query_id"],
            ["queries.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id"),
    )
    op.create_table(
        "pool_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pool_id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Double(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["images.id"],
        ),
        sa.ForeignKeyConstraint(["pool_id"], ["pools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pool_id", "image_id"),
        sa.UniqueConstraint("pool_id", "rank"),
    )
    op.create_index(op.f("ix_pool_members_pool_id"), "pool_members", ["pool_id"], unique=False)
    op.create_table(
        "action_members",
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("pool_member_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["actions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["pool_member_id"],
            ["pool_members.id"],
        ),
        sa.PrimaryKeyConstraint("action_id", "pool_member_id"),
    )
    op.create_table(
        "adjudications",
        sa.Column("pool_member_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
        ),
        sa.ForeignKeyConstraint(
            ["pool_member_id"],
            ["pool_members.id"],
        ),
        sa.PrimaryKeyConstraint("pool_member_id"),
    )
    op.create_table(
        "judgments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pool_member_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("group", "item", "review", "suggestion", name="source", native_enum=False),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
        ),
        sa.ForeignKeyConstraint(
            ["pool_member_id"],
            ["pool_members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "pool_member_id"),
    )
    op.create_index(op.f("ix_judgments_pool_member_id"), "judgments", ["pool_member_id"], unique=False)
    op.create_index(op.f("ix_judgments_user_id"), "judgments", ["user_id"], unique=False)


def downgrade() -> None:
    """Drop every table; the pgvector extension stays, as other databases' objects may use it."""
    op.drop_index(op.f("ix_judgments_user_id"), table_name="judgments")
    op.drop_index(op.f("ix_judgments_pool_member_id"), table_name="judgments")
    op.drop_table("judgments")
    op.drop_table("adjudications")
    op.drop_table("action_members")
    op.drop_index(op.f("ix_pool_members_pool_id"), table_name="pool_members")
    op.drop_table("pool_members")
    op.drop_table("pools")
    op.drop_table("assignments")
    op.drop_index(op.f("ix_actions_user_id"), table_name="actions")
    op.drop_index(op.f("ix_actions_query_id"), table_name="actions")
    op.drop_table("actions")
    op.drop_table("query_embeddings")
    op.drop_index(op.f("ix_queries_study_id"), table_name="queries")
    op.drop_table("queries")
    op.drop_table("study_members")
    op.drop_index(op.f("ix_labels_study_id"), table_name="labels")
    op.drop_table("labels")
    op.drop_index("ix_embeddings_encoder", table_name="embeddings")
    op.drop_table("embeddings")
    op.drop_index(op.f("ix_dataset_queries_dataset_id"), table_name="dataset_queries")
    op.drop_table("dataset_queries")
    op.drop_index(op.f("ix_studies_dataset_id"), table_name="studies")
    op.drop_table("studies")
    op.drop_index(op.f("ix_images_dataset_id"), table_name="images")
    op.drop_table("images")
    op.drop_table("users")
    op.drop_table("datasets")
