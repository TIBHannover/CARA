"""What annotators did: judgments, the action log, assignments and adjudications."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from cara.core.pilot import Action
from cara.db.models import (
    ActionKind,
    ActionRow,
    AdjudicationRow,
    AssignmentRow,
    ImageRow,
    JudgmentRow,
    LabelRow,
    PoolMemberRow,
    PoolRow,
    QueryRow,
    Source,
    UserRow,
)
from cara.repositories.base import Repository


@dataclass(frozen=True, slots=True)
class JudgmentRecord:
    """One judgment with the names the agreement and export code need.

    Attributes:
        query_external_id: The query's id in the dataset's files.
        member_id: The pool image's id in the database.
        doc_id: The image's id in the dataset's files.
    """

    username: str
    query_id: int
    query_external_id: str
    member_id: int
    doc_id: str
    label: str


class Judgments(Repository[JudgmentRow]):
    """Annotators' judgments, and what goes with them.

    The action log records how they were given, the assignments say who judges what, and adjudications are
    admins' final labels.
    """

    model = JudgmentRow
    noun = "judgment"

    def upsert(self, user_id: int, member_ids: list[int], label_id: int, source: Source) -> None:
        """Set the annotator's label for these pool images.

        A group label (`Source.GROUP`) never overwrites an image the annotator labelled one by one, in review
        or by accepting a suggestion; any other source overwrites everything. The rule is in the SQL, so it
        holds when two clicks race.
        """
        statement = insert(JudgmentRow).values(
            [
                {"user_id": user_id, "pool_member_id": m, "label_id": label_id, "source": source}
                for m in member_ids
            ]
        )
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "pool_member_id"],
                set_={
                    "label_id": statement.excluded.label_id,
                    "source": statement.excluded.source,
                    "updated_at": func.now(),
                },
                where=or_(JudgmentRow.source == Source.GROUP, statement.excluded.source != Source.GROUP),
            )
        )

    def add_action(
        self,
        user_id: int,
        query_id: int,
        kind: ActionKind,
        members: list[PoolMemberRow],
        label_id: int | None = None,
        source: Source | None = None,
        group_position: int | None = None,
    ) -> None:
        """Log one action of an annotator.

        Args:
            members: The pool images it touched.
            label_id: The label given; None for a split, an undone split or a finished review.
            source: How the images got the label; None when no label was given.
            group_position: The group's place on the judge page, from 1; None outside groups.
        """
        self.session.add(
            ActionRow(
                user_id=user_id,
                query_id=query_id,
                kind=kind,
                label_id=label_id,
                source=source,
                group_position=group_position,
                members=members,
            )
        )

    def labels_in_pool(self, user_id: int, pool_id: int) -> dict[int, tuple[str, Source]]:
        """Return the annotator's label and its source for each image of the pool they have labelled."""
        rows = self.session.execute(
            select(JudgmentRow.pool_member_id, LabelRow.name, JudgmentRow.source)
            .join(LabelRow, LabelRow.id == JudgmentRow.label_id)
            .join(PoolMemberRow, PoolMemberRow.id == JudgmentRow.pool_member_id)
            .where(JudgmentRow.user_id == user_id, PoolMemberRow.pool_id == pool_id)
        )
        return {member_id: (label, source) for member_id, label, source in rows}

    def judged_counts(self, user_id: int, study_id: int) -> dict[int, int]:
        """Return how many images the annotator has labelled in each query of the study they have started."""
        rows = self.session.execute(
            select(PoolRow.query_id, func.count(JudgmentRow.id))
            .join(PoolMemberRow, PoolMemberRow.pool_id == PoolRow.id)
            .join(JudgmentRow, JudgmentRow.pool_member_id == PoolMemberRow.id)
            .join(QueryRow, QueryRow.id == PoolRow.query_id)
            .where(JudgmentRow.user_id == user_id, QueryRow.study_id == study_id)
            .group_by(PoolRow.query_id)
        )
        return {query_id: count for query_id, count in rows}

    def reviewed_queries(self, user_id: int, study_id: int) -> set[int]:
        """Return the study's queries whose review the annotator has finished."""
        return set(
            self.session.scalars(
                select(ActionRow.query_id)
                .join(QueryRow, QueryRow.id == ActionRow.query_id)
                .where(
                    ActionRow.user_id == user_id,
                    ActionRow.kind == ActionKind.REVIEW_DONE,
                    QueryRow.study_id == study_id,
                )
            )
        )

    def has_assignments(self, study_id: int) -> bool:
        """Tell whether any query of the study is assigned to anyone."""
        assigned = select(AssignmentRow.query_id).join(QueryRow).where(QueryRow.study_id == study_id)
        return self.session.scalar(select(assigned.exists())) or False

    def assignments_of(self, user_id: int, study_id: int) -> set[int]:
        """Return the study's queries assigned to the person."""
        return set(
            self.session.scalars(
                select(AssignmentRow.query_id)
                .join(QueryRow, QueryRow.id == AssignmentRow.query_id)
                .where(AssignmentRow.user_id == user_id, QueryRow.study_id == study_id)
            )
        )

    def count_in_study(self, study_id: int) -> int:
        """Count the study's judgments, by every annotator."""
        count: int = (
            self.session.scalar(
                select(func.count(JudgmentRow.id))
                .join(PoolMemberRow, PoolMemberRow.id == JudgmentRow.pool_member_id)
                .join(PoolRow, PoolRow.id == PoolMemberRow.pool_id)
                .join(QueryRow, QueryRow.id == PoolRow.query_id)
                .where(QueryRow.study_id == study_id)
            )
            or 0
        )
        return count

    def labels_by_member(self, pool_id: int, user_ids: set[int] | None = None) -> dict[int, list[str]]:
        """Return every label given to each image of the pool, one per annotator.

        Args:
            user_ids: Keep only these annotators' labels; None keeps everyone's.
        """
        query = (
            select(JudgmentRow.pool_member_id, LabelRow.name)
            .join(LabelRow, LabelRow.id == JudgmentRow.label_id)
            .join(PoolMemberRow, PoolMemberRow.id == JudgmentRow.pool_member_id)
            .where(PoolMemberRow.pool_id == pool_id)
        )
        if user_ids is not None:
            query = query.where(JudgmentRow.user_id.in_(user_ids))
        rows = self.session.execute(query)
        labels: dict[int, list[str]] = {}
        for member_id, label in rows:
            labels.setdefault(member_id, []).append(label)
        return labels

    def in_study(self, study_id: int) -> list[JudgmentRecord]:
        """Return every judgment of the study, by query and then by pool rank."""
        rows = self.session.execute(
            select(
                UserRow.username,
                QueryRow.id,
                QueryRow.external_id,
                PoolMemberRow.id,
                ImageRow.external_id,
                LabelRow.name,
            )
            .select_from(JudgmentRow)
            .join(UserRow, UserRow.id == JudgmentRow.user_id)
            .join(LabelRow, LabelRow.id == JudgmentRow.label_id)
            .join(PoolMemberRow, PoolMemberRow.id == JudgmentRow.pool_member_id)
            .join(ImageRow, ImageRow.id == PoolMemberRow.image_id)
            .join(PoolRow, PoolRow.id == PoolMemberRow.pool_id)
            .join(QueryRow, QueryRow.id == PoolRow.query_id)
            .where(QueryRow.study_id == study_id)
            .order_by(QueryRow.id, PoolMemberRow.rank)
        )
        return [JudgmentRecord(*row) for row in rows]

    def action_times(self, study_id: int) -> dict[str, list[datetime]]:
        """Return when each annotator acted in the study, in time order, by username."""
        rows = self.session.execute(
            select(UserRow.username, ActionRow.created_at)
            .join(UserRow, UserRow.id == ActionRow.user_id)
            .join(QueryRow, QueryRow.id == ActionRow.query_id)
            .where(QueryRow.study_id == study_id)
            .order_by(UserRow.username, ActionRow.created_at)
        )
        times: dict[str, list[datetime]] = {}
        for username, created_at in rows:
            times.setdefault(username, []).append(created_at)
        return times

    def adjudications(self, study_id: int) -> dict[int, str]:
        """Return the adjudicated label of each pool image in the study that has one."""
        rows = self.session.execute(
            select(AdjudicationRow.pool_member_id, LabelRow.name)
            .join(LabelRow, LabelRow.id == AdjudicationRow.label_id)
            .join(PoolMemberRow, PoolMemberRow.id == AdjudicationRow.pool_member_id)
            .join(PoolRow, PoolRow.id == PoolMemberRow.pool_id)
            .join(QueryRow, QueryRow.id == PoolRow.query_id)
            .where(QueryRow.study_id == study_id)
        )
        return {member_id: label for member_id, label in rows}

    def set_adjudication(self, member_id: int, label_id: int, admin_id: int) -> None:
        """Set the final label of a pool image, replacing an earlier adjudication."""
        statement = insert(AdjudicationRow).values(
            pool_member_id=member_id, label_id=label_id, admin_id=admin_id
        )
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["pool_member_id"],
                set_={"label_id": label_id, "admin_id": admin_id, "created_at": func.now()},
            )
        )

    def replace_assignments(self, study_id: int, pairs: list[tuple[int, int]]) -> None:
        """Replace every assignment in the study with these (user id, query id) pairs; judgments are kept."""
        query_ids = select(QueryRow.id).where(QueryRow.study_id == study_id)
        self.session.execute(delete(AssignmentRow).where(AssignmentRow.query_id.in_(query_ids)))
        if pairs:
            self.session.execute(insert(AssignmentRow), [{"user_id": u, "query_id": q} for u, q in pairs])

    def assignment_pairs(self, study_id: int) -> list[tuple[int, int]]:
        """Return the study's assignments as (user id, query id) pairs."""
        rows = self.session.execute(
            select(AssignmentRow.user_id, AssignmentRow.query_id)
            .join(QueryRow, QueryRow.id == AssignmentRow.query_id)
            .where(QueryRow.study_id == study_id)
        )
        return [(user_id, query_id) for user_id, query_id in rows]

    def assignment_counts(self, study_id: int) -> dict[str, int]:
        """Return how many of the study's queries are assigned to each annotator, by username."""
        rows = self.session.execute(
            select(UserRow.username, func.count())
            .select_from(AssignmentRow)
            .join(UserRow, UserRow.id == AssignmentRow.user_id)
            .join(QueryRow, QueryRow.id == AssignmentRow.query_id)
            .where(QueryRow.study_id == study_id)
            .group_by(UserRow.username)
        )
        return {username: count for username, count in rows}

    def actions_in_study(self, study_id: int) -> list[dict[str, object]]:
        """Return the study's action log for export, oldest first.

        Users, labels, queries and images appear by name or by the dataset's ids, not by database ids.
        """
        rows = self.session.scalars(
            select(ActionRow)
            .join(QueryRow, QueryRow.id == ActionRow.query_id)
            .where(QueryRow.study_id == study_id)
            .options(selectinload(ActionRow.members).selectinload(PoolMemberRow.image))
            .order_by(ActionRow.created_at)
        )
        names = dict(self.session.execute(select(UserRow.id, UserRow.username)).all())
        labels = dict(self.session.execute(select(LabelRow.id, LabelRow.name)).all())
        queries = dict(
            self.session.execute(
                select(QueryRow.id, QueryRow.external_id).where(QueryRow.study_id == study_id)
            ).all()
        )
        return [
            {
                "username": names[row.user_id],
                "query_id": queries[row.query_id],
                "kind": row.kind,
                "label": labels.get(row.label_id) if row.label_id else None,
                "source": row.source,
                "group_position": row.group_position,
                "doc_ids": [member.image.external_id for member in row.members],
                "time": row.created_at.isoformat(),
            }
            for row in rows
        ]

    def split_history(self, user_id: int, query_id: int) -> list[tuple[ActionKind, set[int]]]:
        """Return the annotator's splits and undone splits in the query, oldest first.

        Each comes with the pool images it touched; replaying them rebuilds the groups the annotator sees.
        """
        actions = self.session.scalars(
            select(ActionRow)
            .where(
                ActionRow.user_id == user_id,
                ActionRow.query_id == query_id,
                ActionRow.kind.in_([ActionKind.SPLIT, ActionKind.UNSPLIT]),
            )
            .options(selectinload(ActionRow.members))
            .order_by(ActionRow.id)
        )
        return [(action.kind, {member.id for member in action.members}) for action in actions]

    def actions_on(self, query_ids: list[int]) -> list[Action]:
        """Return every action on these queries.

        The images each action touched are given as (query id, doc id) pairs from the dataset's files.
        """
        rows = self.session.scalars(
            select(ActionRow)
            .where(ActionRow.query_id.in_(query_ids))
            .options(selectinload(ActionRow.members).selectinload(PoolMemberRow.image))
        )
        names = dict(self.session.execute(select(UserRow.id, UserRow.username)).all())
        labels = dict(self.session.execute(select(LabelRow.id, LabelRow.name)).all())
        queries = dict(
            self.session.execute(
                select(QueryRow.id, QueryRow.external_id).where(QueryRow.id.in_(query_ids))
            ).all()
        )
        return [
            Action(
                names[row.user_id],
                row.created_at.timestamp(),
                labels[row.label_id] if row.kind == ActionKind.LABEL and row.label_id else None,
                tuple((queries[row.query_id], member.image.external_id) for member in row.members),
            )
            for row in rows
        ]
