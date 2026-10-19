"""Studies, with their labels, queries, pools and members."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from cara.db.models import (
    ActionRow,
    AdjudicationRow,
    AssignmentRow,
    DatasetQueryRow,
    JudgmentRow,
    LabelRow,
    PoolMemberRow,
    PoolRow,
    QueryRow,
    StudyMemberRow,
    StudyRow,
    action_members,
)
from cara.repositories.base import Repository
from cara.settings import StudySettings


class Studies(Repository[StudyRow]):
    """Studies, and everything that belongs to one: labels, queries, pools and their images, members."""

    model = StudyRow
    noun = "study"

    def create(self, settings: StudySettings, dataset_id: int, query_set: str) -> StudyRow:
        """Add a study with its labels, in the settings' order, and flush, so it has its id.

        Raises:
            sqlalchemy.exc.IntegrityError: A study with this name exists.
        """
        study = StudyRow(
            name=settings.name,
            settings=settings.model_dump(mode="json"),
            dataset_id=dataset_id,
            query_set=query_set,
            labels=[
                LabelRow(name=label.name, grade=label.grade, colour=label.colour, position=position)
                for position, label in enumerate(settings.labels)
            ],
        )
        return self.add(study)

    def list_for_member(self, user_id: int) -> list[StudyRow]:
        """Return the studies the person is a member of, oldest first."""
        return list(
            self.session.scalars(
                select(StudyRow)
                .join(StudyMemberRow, StudyMemberRow.study_id == StudyRow.id)
                .where(StudyMemberRow.user_id == user_id)
                .order_by(StudyRow.id)
            )
        )

    def save_settings(self, study: StudyRow, settings: StudySettings) -> None:
        """Store new settings, and the label colours with them.

        Label names and grades are not touched here: they can't change once judgments point at them (see
        `cara.settings.locked_changes`).
        """
        study.name = settings.name
        study.settings = settings.model_dump(mode="json")
        for row, label in zip(study.labels, settings.labels, strict=True):
            row.colour = label.colour

    def add_queries(self, study_id: int, queries: list[DatasetQueryRow]) -> None:
        """Copy dataset queries into the study and flush, so they have their ids."""
        self.session.add_all(
            QueryRow(
                study_id=study_id,
                dataset_query_id=query.id,
                external_id=query.external_id,
                image_id=query.image_id,
                text=query.text,
            )
            for query in queries
        )
        self.session.flush()

    def list_queries(self, study_id: int) -> list[QueryRow]:
        """Return the study's queries, in the order they were added."""
        return list(
            self.session.scalars(select(QueryRow).where(QueryRow.study_id == study_id).order_by(QueryRow.id))
        )

    def delete_pools(self, study_id: int) -> None:
        """Delete every pool of the study, and their members with them."""
        query_ids = select(QueryRow.id).where(QueryRow.study_id == study_id)
        self.session.execute(delete(PoolRow).where(PoolRow.query_id.in_(query_ids)))

    def delete_study(self, study_id: int) -> None:
        """Delete the study and everything recorded in it, children first.

        Its judgments, actions, adjudications, assignments, pools, queries, labels and members go with it;
        the dataset, its images and the accounts stay.
        """
        query_ids = select(QueryRow.id).where(QueryRow.study_id == study_id)
        member_ids = select(PoolMemberRow.id).join(PoolRow).where(PoolRow.query_id.in_(query_ids))
        action_ids = select(ActionRow.id).where(ActionRow.query_id.in_(query_ids))
        for statement in (
            delete(action_members).where(action_members.c.action_id.in_(action_ids)),
            delete(ActionRow).where(ActionRow.query_id.in_(query_ids)),
            delete(AdjudicationRow).where(AdjudicationRow.pool_member_id.in_(member_ids)),
            delete(JudgmentRow).where(JudgmentRow.pool_member_id.in_(member_ids)),
            delete(AssignmentRow).where(AssignmentRow.query_id.in_(query_ids)),
            delete(PoolRow).where(PoolRow.query_id.in_(query_ids)),
            delete(QueryRow).where(QueryRow.study_id == study_id),
            delete(LabelRow).where(LabelRow.study_id == study_id),
            delete(StudyMemberRow).where(StudyMemberRow.study_id == study_id),
            delete(StudyRow).where(StudyRow.id == study_id),
        ):
            self.session.execute(statement)

    def add_pool(self, query_id: int, image_ids: list[int]) -> None:
        """Add a query's pool, ranked in the order of `image_ids`, without groups yet."""
        self.session.add(
            PoolRow(
                query_id=query_id,
                members=[
                    PoolMemberRow(image_id=image_id, rank=rank) for rank, image_id in enumerate(image_ids)
                ],
            )
        )

    def list_pools(self, study_id: int) -> list[PoolRow]:
        """Return the study's pools with their queries and members loaded, in the order of the queries."""
        return list(
            self.session.scalars(
                select(PoolRow)
                .join(PoolRow.query)
                .where(QueryRow.study_id == study_id)
                .options(selectinload(PoolRow.members), selectinload(PoolRow.query))
                .order_by(QueryRow.id)
            )
        )

    def pool_sizes(self, study_id: int) -> list[tuple[QueryRow, int]]:
        """Return each query of the study that has a pool, with the pool's size.

        The sizes are counted in SQL, without loading the members.
        """
        rows = self.session.execute(
            select(QueryRow, func.count(PoolMemberRow.id))
            .join(PoolRow, PoolRow.query_id == QueryRow.id)
            .join(PoolMemberRow, PoolMemberRow.pool_id == PoolRow.id)
            .where(QueryRow.study_id == study_id)
            .group_by(QueryRow.id)
            .order_by(QueryRow.id)
        )
        return [(query, size) for query, size in rows]

    def pool_of(self, query_id: int) -> PoolRow | None:
        """Return the query's pool with its members and their images loaded, or None if it has no pool yet."""
        return self.session.scalar(
            select(PoolRow)
            .where(PoolRow.query_id == query_id)
            .options(selectinload(PoolRow.members).selectinload(PoolMemberRow.image))
        )

    def set_pilot(self, study_id: int, query_ids: set[int]) -> None:
        """Make exactly these queries the study's pilot queries."""
        for query in self.list_queries(study_id):
            query.is_pilot = query.id in query_ids

    def query(self, query_id: int) -> QueryRow | None:
        """Return the query, or None if there is none with this id."""
        return self.session.get(QueryRow, query_id)

    def members_in_query(self, query_id: int, member_ids: list[int]) -> list[PoolMemberRow]:
        """Return those of `member_ids` that belong to the query's pool; the others are left out silently."""
        return list(
            self.session.scalars(
                select(PoolMemberRow)
                .join(PoolRow, PoolRow.id == PoolMemberRow.pool_id)
                .where(PoolRow.query_id == query_id, PoolMemberRow.id.in_(member_ids))
            )
        )

    def cover_images(self, study_id: int, count: int = 4) -> list[int]:
        """Return up to `count` images that stand for the study.

        The first query's image, if it has one, then the top of its pool.
        """
        first = self.session.scalar(
            select(QueryRow).where(QueryRow.study_id == study_id).order_by(QueryRow.id).limit(1)
        )
        if first is None:
            return []
        candidates = self.session.scalars(
            select(PoolMemberRow.image_id)
            .join(PoolRow, PoolRow.id == PoolMemberRow.pool_id)
            .where(PoolRow.query_id == first.id)
            .order_by(PoolMemberRow.rank)
            .limit(count)
        )
        return ([first.image_id] if first.image_id is not None else []) + list(candidates)[
            : count - (first.image_id is not None)
        ]

    def has_image(self, study_id: int, image_id: int) -> bool:
        """Tell whether the image is one of the study's query or pool images, not just in its dataset.

        Members of a study may see only these images.
        """
        query_image = select(QueryRow.id).where(QueryRow.study_id == study_id, QueryRow.image_id == image_id)
        pooled = (
            select(PoolMemberRow.id)
            .join(PoolRow, PoolRow.id == PoolMemberRow.pool_id)
            .join(QueryRow, QueryRow.id == PoolRow.query_id)
            .where(QueryRow.study_id == study_id, PoolMemberRow.image_id == image_id)
        )
        return self.session.scalar(select(query_image.exists() | pooled.exists())) or False

    def has_pilot(self, study_id: int) -> bool:
        """Tell whether any query of the study is a pilot query."""
        pilot = select(QueryRow.id).where(QueryRow.study_id == study_id, QueryRow.is_pilot)
        return self.session.scalar(select(pilot.exists())) or False
