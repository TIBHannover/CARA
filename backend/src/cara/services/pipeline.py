"""Setting up a study's queries and pools.

Creating a study, sampling its queries, building and grouping its pools, and choosing its pilot queries.
"""

import logging
import random
from pathlib import Path

from cara.db.models import Role, StudyRow
from cara.errors import Conflict, Invalid
from cara.grouping import scores
from cara.repositories.database import Database
from cara.services.datasets import LEGACY_SET, DatasetService, dataset_yaml
from cara.services.studies import StudyService, settings_of
from cara.services.users import UserService
from cara.settings import STANDARD_LABELS, PoolSettings, StudySettings

logger = logging.getLogger(__name__)


class PipelineService:
    """A study's queries, pools and groups, from creation until judging starts."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.studies = StudyService(db)
        self.datasets = DatasetService(db)
        self.users = UserService(db)

    def _unlocked(self, study_id: int) -> StudyRow:
        study = self.studies.get(study_id)
        if study.locked_at is not None:
            raise Conflict(f"judging has started in study {study_id}; pools and groups are locked")
        return study

    def new_study(
        self,
        name: str,
        dataset_id: int,
        query_set: str,
        encoder: str,
        k: int | None,
        count: int | None,
        seed: int,
        unsure: bool,
        annotators: list[str],
        admins: list[str],
    ) -> StudyRow:
        """Create a study from the New study page, with the standard labels.

        Args:
            k: None pools each query with its given candidates; a number pools it with its `k` nearest images.
            count: How many queries to sample from the set; None takes all.
            unsure: Whether the Unsure label is offered.

        Raises:
            Invalid: The dataset has no such query set, or `encoder` can't pool or group it; the message says
                which and that `cara encode` makes the embeddings.
        """
        info = next((s for s in self.datasets.query_sets(dataset_id) if s.name == query_set), None)
        if info is None:
            raise Invalid(f"dataset {dataset_id} has no query set {query_set!r}")
        allowed = info.knn_encoders if k is not None else info.given_encoders
        if encoder not in allowed:
            how = (
                f"pooled by nearest neighbours with {encoder}" if k is not None else f"grouped with {encoder}"
            )
            raise Invalid(f"query set {query_set!r} cannot be {how}; run cara encode on the dataset")
        labels = [
            label.model_copy(update={"offered": unsure or label.grade is not None})
            for label in STANDARD_LABELS
        ]
        settings = StudySettings(
            name=name,
            labels=labels,
            encoder=encoder,
            pool=PoolSettings(source="file", k=None) if k is None else PoolSettings(source="knn", k=k),
            order="similarity" if encoder in info.knn_encoders else "pool_rank",
        )
        return self.setup_study(settings, dataset_id, query_set, count, seed, annotators, tuple(admins))

    def setup_study(
        self,
        settings: StudySettings,
        dataset_id: int,
        query_set: str,
        count: int | None,
        seed: int,
        annotators: list[str],
        admins: tuple[str, ...] = (),
    ) -> StudyRow:
        """Create a study that is ready to judge: queries sampled, pools built and grouped, people added."""
        study = self.studies.create(settings, dataset_id, query_set)
        self.add_queries(study.id, count, seed)
        if settings.pool.source == "knn":
            self.build_pools(study.id)
        self.cluster(study.id)
        for username in annotators:
            self.users.set_role(study.id, username, Role.ANNOTATOR)
        for username in admins:
            self.users.set_role(study.id, username, Role.ADMIN)
        logger.info("study %d (%s) is ready", study.id, study.name)
        return study

    def load_folder(self, folder: Path, image_dir: str, annotators: list[str]) -> StudyRow:
        """Add a dataset and a study in one step, from a single folder with `cara.yaml`.

        A dataset of the same name is reused, so with another study name in `cara.yaml` the folder loads again
        as a second study on the same dataset.
        """
        settings = StudySettings.from_yaml(folder / "cara.yaml")
        dataset = self.db.datasets.named(dataset_yaml(folder).get("name", folder.name))
        if dataset is None:
            dataset = self.datasets.add_folder(folder, None, image_dir, settings.encoder)
        return self.setup_study(settings, dataset.id, LEGACY_SET, None, 0, annotators)

    def add_queries(self, study_id: int, count: int | None, seed: int) -> int:
        """Take `count` random queries of the study's query set, all of them if None.

        With `pool.source: file`, each query's pool is the candidates the set comes with.

        Returns:
            How many queries were added.

        Raises:
            Conflict: The study has queries already, or judging has started.
            Invalid: The set has fewer than `count` queries, or `pool.source` is `file` but the set has no
                candidates.
        """
        study = self._unlocked(study_id)
        if self.db.studies.list_queries(study_id):
            raise Conflict(f"study {study_id} already has queries; create a new study to start over")
        every = self.db.datasets.list_queries(study.dataset_id, study.query_set)
        if count is not None and count > len(every):
            raise Invalid(f"asked for {count} queries but query set {study.query_set!r} has {len(every)}")
        chosen = (
            every if count is None else sorted(random.Random(seed).sample(every, count), key=lambda q: q.id)
        )
        source = settings_of(study).pool.source
        if source == "file" and not all(query.candidates for query in chosen):
            raise Invalid(f"pool.source is 'file', but query set {study.query_set!r} has no candidates")
        self.db.studies.add_queries(study_id, chosen)
        if source == "file":
            for query, row in zip(chosen, self.db.studies.list_queries(study_id), strict=True):
                self.db.studies.add_pool(row.id, query.candidates or [])
        logger.info("study %d: %d queries from set %r", study_id, len(chosen), study.query_set)
        return len(chosen)

    def build_pools(self, study_id: int) -> None:
        """Rebuild every pool of the study from its queries' nearest neighbours (`pool.source: knn`).

        Raises:
            Conflict: Judging has started, a pilot query has judgments, or `pool.source` is `file`.
            Invalid: A query has no embedding by the study's encoder, or `pool.k` is null and the corpus is
                larger than `pool.max_size`.
        """
        study = self._unlocked(study_id)
        settings = settings_of(study)
        if settings.pool.source == "file":
            raise Conflict("pool.source is 'file': pools come from the query file's candidates")
        if self.db.judgments.count_in_study(study_id):
            raise Conflict(
                "pilot queries have judgments, so the pools are fixed; cluster settings can still change"
            )
        corpus = self.db.datasets.corpus_ids(study.dataset_id)
        if settings.pool.k is None and len(corpus) > settings.pool.max_size:
            raise Invalid(
                f"pool.k is null (whole corpus) but the corpus has {len(corpus)} images, more than "
                f"pool.max_size={settings.pool.max_size}; set pool.k"
            )
        self.db.studies.delete_pools(study_id)
        for query in self.db.studies.list_queries(study_id):
            if settings.pool.k is None:
                members = corpus
            elif (query_vec := self.datasets.query_vector(query, settings.encoder)) is None:
                raise Invalid(
                    f"query {query.external_id} has no {settings.encoder} embedding; "
                    "run cara encode on its dataset"
                )
            else:
                nearest = self.db.datasets.nearest(
                    study.dataset_id, settings.encoder, query_vec, settings.pool.k
                )
                members = [i for i, _ in nearest]
            self.db.studies.add_pool(query.id, members)
        logger.info("built pools for study %d", study_id)

    def cluster(self, study_id: int) -> None:
        """Group every pool of the study with its grouping settings, and store each image's score.

        Raises:
            Conflict: Judging has started.
            KeyError: An image has no embedding by the study's encoder.
        """
        settings = settings_of(self._unlocked(study_id))
        for pool in self.db.studies.list_pools(study_id):
            members = sorted(pool.members, key=lambda m: m.rank)
            emb_nd = self.db.datasets.embeddings(settings.encoder, [m.image_id for m in members])
            query_emb_d = (
                self.datasets.query_vector(pool.query, settings.encoder)
                if settings.order == "similarity"
                else None
            )
            score_n = scores(settings.order, emb_nd, query_emb_d)
            grouped = settings.grouping.group(
                emb_nd, score_n, settings.solo.percentile, settings.top_k_individual
            )
            group_of = {c: g for g, group in enumerate(grouped.groups) for c in group}
            for c, member in enumerate(members):
                member.score = float(score_n[c])
                member.group_id = group_of.get(c)
        logger.info("clustered study %d with %s", study_id, settings.grouping.method)

    def set_pilot(self, study_id: int, count: int, seed: int, among: set[str] | None = None) -> list[str]:
        """Mark `count` random queries that have pools as the pilot queries.

        Args:
            among: Draw only from these query ids (from the query file), such as those a qrels file covers.

        Returns:
            The pilot queries' ids, sorted.

        Raises:
            Conflict: Judging has started, or the current pilot queries have judgments.
            Invalid: Fewer than `count` queries have pools.
        """
        self._unlocked(study_id)
        if self.db.judgments.count_in_study(study_id):
            raise Conflict("pilot queries already have judgments; keep that pilot set")
        pooled = [
            pool.query
            for pool in self.db.studies.list_pools(study_id)
            if among is None or pool.query.external_id in among
        ]
        if count > len(pooled):
            raise Invalid(f"asked for {count} pilot queries but only {len(pooled)} queries have pools")
        chosen = random.Random(seed).sample(pooled, count)
        self.db.studies.set_pilot(study_id, {query.id for query in chosen})
        logger.info("study %d: %d pilot queries", study_id, count)
        return sorted(query.external_id for query in chosen)

    def pilot_queries(self, study_id: int) -> list[str]:
        """Return the ids (from the query file) of the study's pilot queries, in query order."""
        return [
            pool.query.external_id for pool in self.db.studies.list_pools(study_id) if pool.query.is_pilot
        ]
