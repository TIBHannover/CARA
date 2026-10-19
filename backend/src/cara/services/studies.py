"""Studies: creating them, their settings, who sees which queries, and where a study stands."""

from dataclasses import dataclass
from typing import Literal

from cara.db.models import PoolRow, QueryRow, Role, StudyRow, UserRow
from cara.errors import Conflict, Forbidden, NotFound
from cara.repositories.database import Database
from cara.settings import StudySettings, locked_changes

Stage = Literal["new", "pilot", "annotation", "done"]


@dataclass(frozen=True, slots=True)
class Overview:
    """Where a study stands, derived from its pilot flags, assignments and judgments; no stage is stored.

    Attributes:
        pilot_judged: Pilot queries every image of which one annotator has judged.
        annotation_assignments: (annotator, annotation query) pairs; without assignments every annotator has
            every query.
        annotation_complete: Of those pairs, the ones fully judged.
    """

    stage: Stage
    pilot_queries: int
    pilot_judged: int
    annotation_queries: int
    annotation_assignments: int
    annotation_complete: int


def settings_of(study: StudyRow) -> StudySettings:
    """Return a study's settings, validated from its stored JSON."""
    return StudySettings.model_validate(study.settings)


class StudyService:
    """Studies and their settings."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, settings: StudySettings, dataset_id: int, query_set: str) -> StudyRow:
        """Create a study on one query set of a dataset, without queries yet (see `PipelineService`).

        Raises:
            Conflict: A study with this name exists.
            NotFound: The dataset has no such query set.
        """
        if any(study.name == settings.name for study in self.db.studies.list_all()):
            raise Conflict(f"study {settings.name!r} already exists")
        if query_set not in self.db.datasets.query_sets(dataset_id):
            raise NotFound(f"dataset {dataset_id} has no query set {query_set!r}")
        return self.db.studies.create(settings, dataset_id, query_set)

    def get(self, study_id: int) -> StudyRow:
        """Return the study.

        Raises:
            NotFound: It doesn't exist.
        """
        return self.db.studies.get(study_id)

    def delete(self, study_id: int) -> None:
        """Delete the study with every judgment in it; the dataset and the accounts stay.

        Raises:
            NotFound: The study doesn't exist.
        """
        self.get(study_id)
        self.db.studies.delete_study(study_id)

    def list_for(self, user: UserRow) -> list[StudyRow]:
        """Return the studies the person may open: every study for a superuser, else those they belong to."""
        return self.db.studies.list_all() if user.is_superuser else self.db.studies.list_for_member(user.id)

    def update_settings(self, study_id: int, new: StudySettings) -> StudyRow:
        """Store new settings for the study.

        Raises:
            NotFound: The study doesn't exist.
            Conflict: Judging has started and `new` changes a locked setting (the message lists them), or
                `new` renames a label or changes its grade, which judgments depend on.
        """
        study = self.get(study_id)
        changed = locked_changes(settings_of(study), new)
        if study.locked_at is not None and changed:
            raise Conflict(f"judging has started; these settings are locked: {changed}")
        if "labels" in changed:
            raise Conflict(
                "label names and grades are set when the study is created; colours and short names can change"
            )
        self.db.studies.save_settings(study, new)
        return study

    def visible_queries(self, user_id: int, study_id: int) -> set[int] | None:
        """Return the queries the person may see in the study.

        Returns:
            Their assigned queries; None, meaning every query, only in a study with neither assignments nor
            pilot queries. Once a pilot is chosen, each annotator sees just what is assigned to them, so the
            annotation queries stay hidden until annotation starts.
        """
        if self.db.judgments.has_assignments(study_id):
            return self.db.judgments.assignments_of(user_id, study_id)
        return set() if self.db.studies.has_pilot(study_id) else None

    def query_for(self, user: UserRow, study_id: int, query_id: int) -> QueryRow:
        """Return the query, if it is in the study and the person may see it.

        Raises:
            NotFound: The query isn't in the study.
            Forbidden: It isn't assigned to them.
        """
        query = self.db.studies.query(query_id)
        if query is None or query.study_id != study_id:
            raise NotFound(f"query {query_id} is not in study {study_id}")
        visible = self.visible_queries(user.id, study_id)
        if visible is not None and query_id not in visible:
            raise Forbidden(f"query {query_id} is not assigned to {user.username}")
        return query

    def pool_for(self, user: UserRow, study_id: int, query_id: int) -> tuple[QueryRow, PoolRow]:
        """Return the query and its pool, if the person may see the query.

        Raises:
            NotFound: The query isn't in the study or has no pool.
            Forbidden: It isn't assigned to them.
        """
        query = self.query_for(user, study_id, query_id)
        pool = self.db.studies.pool_of(query_id)
        if pool is None:
            raise NotFound(f"query {query_id} has no pool")
        return query, pool

    def overview(self, study_id: int) -> Overview:
        """Work out where the study stands: its stage, and how far its pilot and annotation are."""
        sizes = {query.id: size for query, size in self.db.studies.pool_sizes(study_id)}
        pilot = {
            query.id
            for query in self.db.studies.list_queries(study_id)
            if query.is_pilot and query.id in sizes
        }
        annotation = set(sizes) - pilot
        annotators = [
            self.db.users.named(name)
            for name, role in self.db.users.members(study_id)
            if role == Role.ANNOTATOR
        ]
        pilot_done: set[int] = set()
        pairs = complete = 0
        for user in annotators:
            if user is None:
                continue
            judged = self.db.judgments.judged_counts(user.id, study_id)
            assigned = self.visible_queries(user.id, study_id)
            mine = annotation if assigned is None else annotation & assigned
            done = {q for q, n in judged.items() if n == sizes.get(q)}
            pilot_done |= done & pilot
            if assigned is not None or judged.keys() & annotation:
                pairs += len(mine)
                complete += len(done & mine)
        stage: Stage = (
            "done" if pairs and complete == pairs else "annotation" if pairs else "pilot" if pilot else "new"
        )
        return Overview(stage, len(pilot), len(pilot_done), len(annotation), pairs, complete)

    def query_kind(self, study_id: int) -> Literal["image", "text", "image + text"] | None:
        """Return what the study's queries are, judged from the first; None for a study without queries."""
        first = next(iter(self.db.studies.list_queries(study_id)), None)
        if first is None:
            return None
        return "image + text" if first.image_id and first.text else "image" if first.image_id else "text"

    def cover_images(self, study_id: int) -> list[int]:
        """Return up to four images that stand for the study on its card."""
        return self.db.studies.cover_images(study_id)
