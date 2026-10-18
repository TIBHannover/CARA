"""What annotators see and do: their queue, a query's groups, labelling, splits and review.

Similar images and Suggest mode are in `similarity.py`.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from cara.db.models import ActionKind, LabelRow, PoolMemberRow, PoolRow, Source, UserRow
from cara.errors import Conflict, NotFound
from cara.repositories.database import Database
from cara.services.studies import StudyService, settings_of
from cara.settings import StudySettings


@dataclass(frozen=True, slots=True)
class QueueItem:
    """One query in an annotator's queue, with how far they got."""

    query_id: int
    external_id: str
    pool_size: int
    judged: int
    reviewed: bool
    is_pilot: bool
    image_id: int | None
    text: str | None


@dataclass(frozen=True, slots=True)
class Member:
    """One pool image as an annotator sees it, with their label and how they gave it.

    Attributes:
        score: Its similarity to the query; minus its rank when the query has no embedding.
    """

    member_id: int
    image_id: int
    doc_id: str
    score: float
    label: str | None
    source: Source | None


@dataclass(frozen=True, slots=True)
class Group:
    """A group as shown on the judge page, most similar to the query first."""

    group_id: int | None
    members: list[Member]


@dataclass(frozen=True, slots=True)
class QueryView:
    """A query as an annotator sees it.

    Its groups (with the annotator's own splits replayed), the images judged alone, and their progress.

    Attributes:
        undoable_splits: How many of their splits can still be undone, newest first.
    """

    query_id: int
    external_id: str
    image_id: int | None
    text: str | None
    groups: list[Group]
    individual: list[Member]
    judged: int
    pool_size: int
    reviewed: bool
    is_pilot: bool
    undoable_splits: int


def _by_score(members: list[Member]) -> list[Member]:
    return sorted(members, key=lambda m: (-m.score, m.member_id))


def _members(pool: PoolRow, member_ids: list[int]) -> list[PoolMemberRow]:
    by_id = {m.id: m for m in pool.members}
    unknown = set(member_ids) - by_id.keys()
    if unknown or not member_ids:
        raise NotFound(f"members {sorted(unknown)} are not in the pool of query {pool.query_id}")
    return [by_id[m] for m in member_ids]


def _open_splits(history: list[tuple[ActionKind, set[int]]]) -> list[set[int]]:
    stack: list[set[int]] = []
    for kind, member_set in history:
        if kind == ActionKind.SPLIT:
            stack.append(member_set)
        elif stack:
            stack.pop()
    return stack


class AnnotationService:
    """An annotator's work on a study. Every method checks that the query is one the annotator may see."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.studies = StudyService(db)

    def queue(self, user: UserRow, study_id: int) -> list[QueueItem]:
        """Return the queries the annotator may see, pilot queries first.

        With `query_order: shuffled`, each annotator gets their own fixed random order, the same in every
        session and unchanged when queries are added (a hash of the user and the query).
        """
        settings = settings_of(self.studies.get(study_id))
        visible = self.studies.visible_queries(user.id, study_id)
        judged = self.db.judgments.judged_counts(user.id, study_id)
        reviewed = self.db.judgments.reviewed_queries(user.id, study_id)
        mine = [(q, n) for q, n in self.db.studies.pool_sizes(study_id) if visible is None or q.id in visible]
        if settings.query_order == "shuffled":
            mine.sort(key=lambda item: hashlib.sha256(f"{user.id}:{item[0].id}".encode()).digest())
        return [
            QueueItem(
                query_id=query.id,
                external_id=query.external_id,
                pool_size=size,
                judged=judged.get(query.id, 0),
                reviewed=query.id in reviewed,
                is_pilot=query.is_pilot,
                image_id=query.image_id,
                text=query.text,
            )
            for query, size in sorted(mine, key=lambda item: not item[0].is_pilot)
        ]

    def query_view(self, user: UserRow, study_id: int, query_id: int) -> QueryView:
        """Return a query as the annotator sees it.

        Pilot queries show every image on its own: they are the simulator's ground truth. The annotator's
        splits and undone splits are replayed from the action log, so they survive a reload or a new session.

        Raises:
            NotFound: The query isn't in the study or has no pool.
            Forbidden: The annotator may not see it.
        """
        query, pool = self.studies.pool_for(user, study_id, query_id)
        labels = self.db.judgments.labels_in_pool(user.id, pool.id)

        def member(row: PoolMemberRow) -> Member:
            label, source = labels.get(row.id, (None, None))
            score = row.score if row.score is not None else float(-row.rank)
            return Member(row.id, row.image_id, row.image.external_id, score, label, source)

        by_group: dict[int, list[Member]] = {}
        individual: list[Member] = []
        for row in pool.members:
            if query.is_pilot or row.group_id is None:
                individual.append(member(row))
            else:
                by_group.setdefault(row.group_id, []).append(member(row))
        groups = [Group(g, _by_score(members)) for g, members in sorted(by_group.items())]
        history = self.db.judgments.split_history(user.id, query_id)
        if history:
            groups = self._replay_splits(settings_of(self.studies.get(study_id)), pool, groups, history)
        return QueryView(
            query_id=query.id,
            external_id=query.external_id,
            image_id=query.image_id,
            text=query.text,
            groups=groups,
            individual=_by_score(individual),
            judged=len(labels),
            pool_size=len(pool.members),
            reviewed=query.id in self.db.judgments.reviewed_queries(user.id, study_id),
            is_pilot=query.is_pilot,
            undoable_splits=len(_open_splits(history)),
        )

    def _replay_splits(
        self,
        settings: StudySettings,
        pool: PoolRow,
        groups: list[Group],
        history: list[tuple[ActionKind, set[int]]],
    ) -> list[Group]:
        """Apply the annotator's splits and undone splits, oldest first, to the pool's groups.

        A split or merge whose members no longer form a group (the pool was regrouped since) is skipped.
        """
        row_of = {row.id: row for row in pool.members}
        for kind, member_set in history:
            if kind == ActionKind.SPLIT:
                index = next(
                    (i for i, g in enumerate(groups) if {m.member_id for m in g.members} == member_set),
                    None,
                )
                if index is None:
                    continue
                group = groups[index]
                by_id = {m.member_id: m for m in group.members}
                halves = self._halves(settings, [row_of[m.member_id] for m in group.members])
                groups[index : index + 1] = [
                    Group(group.group_id, [by_id[i] for i in half]) for half in halves
                ]
            else:
                parts = [i for i, g in enumerate(groups) if {m.member_id for m in g.members} <= member_set]
                merged = [m for i in parts for m in groups[i].members]
                if not parts or {m.member_id for m in merged} != member_set:
                    continue
                groups[parts[0]] = Group(groups[parts[0]].group_id, _by_score(merged))
                groups = [g for i, g in enumerate(groups) if i not in parts[1:]]
        return groups

    def judge(
        self,
        user: UserRow,
        study_id: int,
        query_id: int,
        member_ids: list[int],
        label: str,
        source: Source,
        group_position: int | None,
    ) -> None:
        """Label pool images, and log the action.

        The first judgment of an annotation query locks the study: its pools, grouping and label meanings
        no longer change. A group label never overwrites an image labelled any other way (see
        `Judgments.upsert`).

        Args:
            group_position: The group's place on the judge page, from 1; None outside groups.

        Raises:
            NotFound: The query isn't in the study, the label doesn't exist (the message lists the labels), or
                some images aren't in the query's pool (the message lists them).
            Forbidden: The annotator may not see the query.
        """
        study = self.studies.get(study_id)
        query = self.studies.query_for(user, study_id, query_id)
        label_row = next((row for row in study.labels if row.name == label), None)
        if label_row is None:
            raise NotFound(f"unknown label {label!r}; labels are {[row.name for row in study.labels]}")
        members = self.db.studies.members_in_query(query_id, member_ids)
        if not member_ids or len(members) != len(set(member_ids)):
            unknown = sorted(set(member_ids) - {m.id for m in members})
            raise NotFound(f"members {unknown} are not in the pool of query {query_id}")
        if study.locked_at is None and not query.is_pilot:
            study.locked_at = datetime.now(UTC)
        self.db.judgments.upsert(user.id, member_ids, label_row.id, source)
        self.db.judgments.add_action(
            user.id, query_id, ActionKind.LABEL, members, label_row.id, source, group_position
        )

    def _halves(self, settings: StudySettings, members: list[PoolMemberRow]) -> list[list[int]]:
        emb_nd = self.db.datasets.embeddings(settings.encoder, [m.image_id for m in members])
        score_n = np.array([m.score if m.score is not None else -m.rank for m in members], dtype=np.float32)
        halves = settings.grouping.split(emb_nd, score_n, list(range(len(members))))
        return [[members[c].id for c in half] for half in halves]

    def split(self, user: UserRow, study_id: int, query_id: int, member_ids: list[int]) -> list[list[int]]:
        """Split a group in two by its own linkage, log it, and return the halves' members."""
        settings = settings_of(self.studies.get(study_id))
        _, pool = self.studies.pool_for(user, study_id, query_id)
        members = _members(pool, member_ids)
        self.db.judgments.add_action(user.id, query_id, ActionKind.SPLIT, members)
        return self._halves(settings, members)

    def undo_split(self, user: UserRow, study_id: int, query_id: int) -> list[int]:
        """Merge back the annotator's most recent split in the query that isn't undone yet.

        Returns:
            The merged group's members.

        Raises:
            Conflict: There is no split to undo.
        """
        _, pool = self.studies.pool_for(user, study_id, query_id)
        stack = _open_splits(self.db.judgments.split_history(user.id, query_id))
        if not stack:
            raise Conflict(f"query {query_id} has no split to undo")
        members = _members(pool, sorted(stack[-1]))
        self.db.judgments.add_action(user.id, query_id, ActionKind.UNSPLIT, members)
        return [m.id for m in members]

    def finish_review(self, user: UserRow, study_id: int, query_id: int) -> None:
        """Mark the annotator's review of the query as done.

        Raises:
            Conflict: Some images of the pool are still unjudged.
        """
        _, pool = self.studies.pool_for(user, study_id, query_id)
        if len(self.db.judgments.labels_in_pool(user.id, pool.id)) < len(pool.members):
            raise Conflict(f"query {query_id} still has unjudged candidates")
        self.db.judgments.add_action(user.id, query_id, ActionKind.REVIEW_DONE, [])

    def judge_from_labels(
        self, user: UserRow, study_id: int, positives: dict[str, set[str]], query_ids: set[int]
    ) -> int:
        """Judge every image of these queries as `user` from known labels, standing in for a person.

        Images in `positives` get the first label of grade 1 or more, all others the first label of grade 0.

        Returns:
            How many images were judged.

        Raises:
            NotFound: One of the queries has no entry in `positives`.
        """
        study = self.studies.get(study_id)
        relevant = next(row.name for row in study.labels if (row.grade or 0) >= 1)
        not_relevant = next(row.name for row in study.labels if row.grade == 0)
        count = 0
        for pool in self.db.studies.list_pools(study_id):
            if pool.query_id not in query_ids:
                continue
            found = positives.get(pool.query.external_id)
            if found is None:
                raise NotFound(f"query {pool.query.external_id} has no labels")
            for member in pool.members:
                label = relevant if member.image.external_id in found else not_relevant
                self.judge(user, study_id, pool.query_id, [member.id], label, Source.ITEM, None)
                count += 1
        return count

    def labels(self, study_id: int) -> list[LabelRow]:
        """Return the study's labels, in their order."""
        return self.studies.get(study_id).labels
