"""The settings simulator as the API and CLI use it: what it can work with, what the pilot shows, and a run.

A run replays against ground truth from an uploaded qrels file, the judged pilot queries, or none (group
structure only).
"""

import random
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from cara.core.agreement import alpha, pairwise_kappa
from cara.core.export import consensus
from cara.core.pilot import AnnotatorStats, annotator_stats
from cara.db.models import PoolRow
from cara.errors import Invalid, NotFound
from cara.repositories.database import Database
from cara.services.simulator.plan import MAX_CANDIDATES, SimulatorPlan, Source, default_plan
from cara.services.simulator.results import SettingResult
from cara.services.simulator.run import SimulationRun, SimulatorEvent
from cara.services.studies import StudyService, settings_of
from cara.services.users import UserService

SOURCE_NAMES = {
    "qrels": "the uploaded qrels file",
    "pilot": "the judged pilot queries",
    "none": "no labels (group structure only)",
}
EMPTY = {
    "qrels": "no query in the qrels file has a pool in this study",
    "pilot": "no pilot pool is fully judged yet (each image needs a label; ties are undecided)",
    "none": "the study has no pools; build or ingest them first",
}


@dataclass(frozen=True, slots=True)
class PilotAnnotator:
    """How one pilot annotator did.

    Attributes:
        judged: Pilot queries every image of which they labelled.
        kappa: Their mean Cohen's kappa with the other pilot annotators, on the images they share.
    """

    username: str
    judged: int
    kappa: float | None


@dataclass(frozen=True, slots=True)
class Scope:
    """What the simulator can work with in a study.

    Attributes:
        labelled_pilot_queries: Pilot queries with a majority label for every image, from the chosen pilot
            annotators.
    """

    queries: int
    images: int
    pilot_queries: int
    labelled_pilot_queries: int
    pilot_annotators: list[PilotAnnotator]


@dataclass(frozen=True, slots=True)
class PilotReport:
    """How the pilot went: alpha over it, and each annotator's speed, corrections and accuracy.

    Attributes:
        alpha: Krippendorff's alpha over every pilot image with two or more labels.
    """

    pilot_queries: int
    alpha: float | None
    annotators: list[AnnotatorStats]


def parse_qrels(text: str) -> dict[str, set[str]]:
    """Read the relevant images per query from TREC qrels.

    Every query in the file gets an entry, even one with no relevant image.

    Args:
        text: Lines of `query_id 0 doc_id grade`; grade above 0 is relevant. Blank lines are skipped.

    Returns:
        The relevant doc ids of each query id.

    Raises:
        Invalid: A line doesn't have four fields, or its grade isn't a whole number; the message names the
            line number and the line.
    """
    positives: dict[str, set[str]] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 4:
            raise Invalid(f"qrels line {number} needs 'query_id 0 doc_id grade', got {line!r}")
        query_id, _, doc_id, grade = fields
        if not grade.lstrip("-").isdigit():
            raise Invalid(f"qrels line {number}: the grade must be a whole number, got {line!r}")
        positives.setdefault(query_id, set())
        if int(grade) > 0:
            positives[query_id].add(doc_id)
    return positives


class SimulatorService:
    """The settings simulator for one database: scope, pilot report, sample qrels, and runs."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.studies = StudyService(db)
        self.users = UserService(db)

    def scope(self, study_id: int, pilot_users: list[str] | None = None) -> Scope:
        """Return what the simulator can work with in the study.

        Args:
            pilot_users: Whose pilot labels count for the labelled pilot queries; None means everyone's.

        Raises:
            NotFound: The study or one of the users doesn't exist.
        """
        settings = settings_of(self.studies.get(study_id))
        grade_of = {label.name: label.grade for label in settings.labels}
        sizes = self.db.studies.pool_sizes(study_id)
        pilot_pools = [pool for pool in self.db.studies.list_pools(study_id) if pool.query.is_pilot]
        user_ids = self._user_ids(pilot_users)
        labelled = sum(self._pilot_truth(pool, grade_of, user_ids) is not None for pool in pilot_pools)
        size_of = {pool.query.external_id: len(pool.members) for pool in pilot_pools}
        labels: dict[str, dict[tuple[str, str], str]] = {}
        for record in self.db.judgments.in_study(study_id):
            if record.query_external_id in size_of:
                labels.setdefault(record.username, {})[record.query_external_id, record.doc_id] = record.label
        kappas = pairwise_kappa(labels)
        annotators = []
        for name, given in sorted(labels.items()):
            per_query = Counter(query_id for query_id, _ in given)
            mine = [k for pair, k in kappas.items() if name in pair and k is not None]
            annotators.append(
                PilotAnnotator(
                    name,
                    sum(per_query[q] == n for q, n in size_of.items()),
                    sum(mine) / len(mine) if mine else None,
                )
            )
        return Scope(len(sizes), sum(size for _, size in sizes), len(pilot_pools), labelled, annotators)

    def pilot_report(self, study_id: int) -> PilotReport:
        """Report how each annotator worked on the pilot queries.

        The measured speed and accuracy can become a simulated annotator type.

        Raises:
            NotFound: The study doesn't exist.
        """
        settings = settings_of(self.studies.get(study_id))
        grade_of = {label.name: label.grade for label in settings.labels}
        pilot_pools = [pool for pool in self.db.studies.list_pools(study_id) if pool.query.is_pilot]
        size_of = {pool.query.external_id: len(pool.members) for pool in pilot_pools}
        labels: dict[str, dict[tuple[str, str], str]] = {}
        for record in self.db.judgments.in_study(study_id):
            if record.query_external_id in size_of:
                labels.setdefault(record.username, {})[record.query_external_id, record.doc_id] = record.label
        actions = self.db.judgments.actions_on([pool.query_id for pool in pilot_pools])
        return PilotReport(
            len(pilot_pools),
            alpha(labels, list(grade_of)) if labels else None,
            annotator_stats(actions, labels, size_of, grade_of),
        )

    def sample_qrels(self, image_root: Path, study_id: int) -> str:
        """Return the example labels the dataset ships for the study's query set.

        They are `qrels/<query set>.qrels` in the dataset's folder, or `sample.qrels` in a dataset with a
        single query set.

        Raises:
            NotFound: The study doesn't exist, or its dataset ships no sample qrels.
        """
        study = self.studies.get(study_id)
        folder = image_root / self.db.datasets.get(study.dataset_id).path
        for path in (folder / "qrels" / f"{study.query_set}.qrels", folder / "sample.qrels"):
            if path.is_file():
                return path.read_text()
        raise NotFound(
            f"study {study_id} has no sample qrels: its dataset has no qrels/{study.query_set}.qrels"
        )

    def simulate_steps(
        self,
        study_id: int,
        source: Source,
        qrels: str | None,
        max_queries: int,
        plan: SimulatorPlan | None = None,
        seed: int = 0,
        pilot_users: list[str] | None = None,
    ) -> Iterator[SimulatorEvent]:
        """Run the simulation step by step, yielding progress events; the last one carries the results.

        Args:
            source: Where the ground truth comes from: `qrels`, `pilot` or `none`.
            qrels: The qrels text, for `source="qrels"`.
            max_queries: How many usable queries to replay, drawn at random with `seed`.
            plan: What to compare; None compares a fixed set of common settings (`default_plan`).
            pilot_users: For `source="pilot"`, whose labels count; None means everyone's.

        Raises:
            Invalid: The plan has more than `MAX_CANDIDATES` settings, the qrels text is missing or malformed,
                or no query has usable labels (the message says why for each source).
            NotFound: The study or one of the users doesn't exist.
        """
        started = time.perf_counter()
        settings = settings_of(self.studies.get(study_id))
        plan = plan or default_plan(settings)
        candidates = plan.candidates(settings)
        if len(candidates) > MAX_CANDIDATES:
            raise Invalid(f"{len(candidates)} candidate settings; choose at most {MAX_CANDIDATES}")
        yield SimulatorEvent("labels", "Reading labels", 0, 1, f"Labels from {SOURCE_NAMES[source]}")
        grade_of = {label.name: label.grade for label in settings.labels}
        found = self._truths(study_id, source, qrels, grade_of, self._user_ids(pilot_users))
        if not found:
            raise Invalid(EMPTY[source])
        sampled = random.Random(seed).sample(found, min(max_queries, len(found)))
        yield SimulatorEvent(
            "labels",
            "Reading labels",
            1,
            1,
            f"{len(found)} queries usable; replaying a random sample of {len(sampled)}",
        )
        run = SimulationRun(self.db, study_id, settings, plan, candidates, sampled, source, seed, started)
        yield from run.steps()

    def simulate(
        self,
        study_id: int,
        source: Source,
        qrels: str | None,
        max_queries: int,
        plan: SimulatorPlan | None = None,
        seed: int = 0,
        pilot_users: list[str] | None = None,
    ) -> list[SettingResult]:
        """Run the simulation to the end and return its results (see `simulate_steps`)."""
        results: list[SettingResult] = []
        for event in self.simulate_steps(study_id, source, qrels, max_queries, plan, seed, pilot_users):
            results = event.results or results
        return results

    def _user_ids(self, usernames: list[str] | None) -> set[int] | None:
        return None if usernames is None else {self.users.get(name).id for name in usernames}

    def _pilot_truth(
        self, pool: PoolRow, grade_of: dict[str, int | None], user_ids: set[int] | None
    ) -> npt.NDArray[np.bool_] | None:
        labels = self.db.judgments.labels_by_member(pool.id, user_ids)
        decided = [consensus(labels.get(member.id, []), None) for member in pool.members]
        if any(label is None for label in decided):
            return None
        return np.array([(grade_of[label] or 0) > 0 for label in decided if label is not None])

    def _truths(
        self,
        study_id: int,
        source: Source,
        qrels: str | None,
        grade_of: dict[str, int | None],
        user_ids: set[int] | None,
    ) -> list[tuple[PoolRow, npt.NDArray[np.bool_] | None]]:
        all_pools = self.db.studies.list_pools(study_id)
        if source == "none":
            return [(pool, None) for pool in all_pools]
        if source == "qrels":
            if qrels is None:
                raise Invalid("source 'qrels' needs the qrels text")
            positives = parse_qrels(qrels)
            return [
                (
                    pool,
                    np.array(
                        [m.image.external_id in positives[pool.query.external_id] for m in pool.members]
                    ),
                )
                for pool in all_pools
                if pool.query.external_id in positives
            ]
        labelled: list[tuple[PoolRow, npt.NDArray[np.bool_] | None]] = []
        for pool in all_pools:
            if pool.query.is_pilot and (truth := self._pilot_truth(pool, grade_of, user_ids)) is not None:
                labelled.append((pool, truth))
        return labelled
