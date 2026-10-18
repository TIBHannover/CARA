"""Datasets: adding them, their query sets and embeddings, and what a new study can do with each query set."""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import yaml

from cara.db.models import DatasetQueryRow, DatasetRow, QueryRow
from cara.errors import Conflict, NotFound
from cara.inputs import CorpusItem, QueryIn, read_corpus, read_embeddings, read_queries
from cara.repositories.database import Database

logger = logging.getLogger(__name__)

LEGACY_SET = "default"
"""The query set of a single-folder dataset (one `queries.jsonl`)."""


@dataclass(frozen=True, slots=True)
class QuerySetInfo:
    """What a new study can do with one query set.

    Attributes:
        kind: `image`, `text` or `image + text`, judged from the first query.
        given_pools: Whether every query comes with its candidates.
        knn_encoders: Encoders that give every query a vector, so pools can be built by nearest neighbours.
        given_encoders: Encoders that embed every candidate, so the given pools can be grouped.
    """

    name: str
    queries: int
    kind: str
    given_pools: bool
    knn_encoders: list[str]
    given_encoders: list[str]


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    """A dataset at a glance: corpus size, query sets, encoders with their coverage, studies using it."""

    id: int
    name: str
    description: str
    images: int
    query_sets: dict[str, int]
    encoders: dict[str, int]
    studies: int


def dataset_yaml(folder: Path) -> dict[str, str]:
    """Return the folder's `dataset.yaml` (name, description), or nothing if it has none."""
    file = folder / "dataset.yaml"
    return yaml.safe_load(file.read_text()) if file.exists() else {}


def _kind(query: DatasetQueryRow) -> str:
    if query.image_id and query.text:
        return "image + text"
    return "image" if query.image_id else "text"


class DatasetService:
    """Datasets and their embeddings."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, name: str, path: str, description: str = "") -> DatasetRow:
        """Register a dataset, without images or queries yet (see `ingest`).

        Raises:
            Conflict: A dataset with this name exists.
        """
        if self.db.datasets.named(name) is not None:
            raise Conflict(f"dataset {name!r} already exists")
        return self.db.datasets.create(name, path, description)

    def add_folder(
        self, folder: Path, name: str | None, path: str | None, legacy_encoder: str | None
    ) -> DatasetRow:
        """Register a dataset folder: its images, query sets and embeddings.

        The folder holds:

        - `dataset.yaml` (optional): name, description;
        - `corpus.jsonl` (optional): doc_id, image;
        - `queries/<set>.jsonl`, one per query set, or a single `queries.jsonl` (set "default");
        - `index/<encoder>/corpus.npz` and `index/<encoder>/queries-<set>.npz` (optional, from your own
          pipeline), or a single `embeddings.npz` with `legacy_encoder`.

        Args:
            name: Default: `dataset.yaml`'s name, else the folder name.
            path: The image folder relative to the image root; default: the folder name.

        Raises:
            ValueError: The folder has `embeddings.npz` but no `legacy_encoder` was given, or a file in it is
                malformed (the message names the file and line).
            Conflict: A dataset with this name exists.
        """
        meta = dataset_yaml(folder)
        dataset = self.add(
            name or meta.get("name", folder.name), path or folder.name, meta.get("description", "")
        )
        corpus = read_corpus(folder / "corpus.jsonl") if (folder / "corpus.jsonl").exists() else []
        query_files = sorted((folder / "queries").glob("*.jsonl")) if (folder / "queries").is_dir() else []
        sets = {file.stem: file for file in query_files} or {LEGACY_SET: folder / "queries.jsonl"}
        for query_set, file in sets.items():
            self.ingest(dataset.id, query_set, read_queries(file), corpus)
            corpus = []
        for index in sorted((folder / "index").glob("*/")) if (folder / "index").is_dir() else []:
            if (index / "corpus.npz").exists():
                self.load_embeddings(dataset.id, index.name, *read_embeddings(index / "corpus.npz"))
            for query_set in sets:
                if (index / f"queries-{query_set}.npz").exists():
                    ids, emb_nd = read_embeddings(index / f"queries-{query_set}.npz")
                    self.load_query_embeddings(dataset.id, query_set, index.name, ids, emb_nd)
        if (folder / "embeddings.npz").exists():
            if legacy_encoder is None:
                raise ValueError("embeddings.npz needs --encoder, the encoder that made it")
            self.load_embeddings(dataset.id, legacy_encoder, *read_embeddings(folder / "embeddings.npz"))
        logger.info("dataset %d (%s) is ready: query sets %s", dataset.id, dataset.name, ", ".join(sets))
        return dataset

    def get(self, dataset_id: int) -> DatasetRow:
        """Return the dataset.

        Raises:
            NotFound: It doesn't exist.
        """
        return self.db.datasets.get(dataset_id)

    def named(self, name: str) -> DatasetRow:
        """Return the dataset with this name.

        Raises:
            NotFound: There is none.
        """
        dataset = self.db.datasets.named(name)
        if dataset is None:
            raise NotFound(f"dataset {name!r} doesn't exist; `cara datasets` lists them")
        return dataset

    def summaries(self) -> list[DatasetSummary]:
        """Return every dataset at a glance, oldest first."""
        studies = self.db.studies.list_all()
        return [
            DatasetSummary(
                dataset.id,
                dataset.name,
                dataset.description,
                self.db.datasets.image_count(dataset.id),
                self.db.datasets.query_sets(dataset.id),
                self.db.datasets.encoders(dataset.id),
                sum(study.dataset_id == dataset.id for study in studies),
            )
            for dataset in self.db.datasets.list_all()
        ]

    def query_sets(self, dataset_id: int) -> list[QuerySetInfo]:
        """Return what a new study can do with each query set of the dataset."""
        repo = self.db.datasets
        encoders = list(repo.encoders(dataset_id))
        found = []
        for name in repo.query_sets(dataset_id):
            queries = repo.list_queries(dataset_id, name)
            own = repo.query_encoders([q.id for q in queries])
            query_images = [q.image_id for q in queries if q.image_id is not None]
            candidates = sorted({i for q in queries for i in q.candidates or []})
            embedded = repo.image_encoders(query_images + candidates)
            given = all(q.candidates for q in queries)
            found.append(
                QuerySetInfo(
                    name,
                    len(queries),
                    _kind(queries[0]),
                    given,
                    [
                        e
                        for e in encoders
                        if all((q.id, e) in own or (q.image_id, e) in embedded for q in queries)
                    ],
                    [e for e in encoders if given and all((i, e) in embedded for i in candidates)],
                )
            )
        return found

    def ingest(
        self, dataset_id: int, query_set: str, queries: list[QueryIn], corpus: list[CorpusItem]
    ) -> None:
        """Add a query set to a dataset, with its query images, its candidates and the corpus images.

        Queries with candidates keep them as their given pool. Images the dataset has already are reused.

        Raises:
            Conflict: The dataset has a query set with this name.
        """
        repo = self.db.datasets
        if repo.list_queries(dataset_id, query_set):
            raise Conflict(f"query set {query_set!r} already exists in dataset {dataset_id}")
        new_images = {item.image: (item.doc_id, True) for q in queries for item in q.candidates}
        new_images |= {item.image: (item.doc_id, True) for item in corpus}
        known = repo.image_ids_by_path(dataset_id)
        new_images |= {
            q.image: (f"query:{q.query_id}", False)
            for q in queries
            if q.image and q.image not in new_images and q.image not in known
        }
        id_of = repo.add_images(dataset_id, new_images)
        repo.add_queries(
            dataset_id,
            query_set,
            [
                (
                    q.query_id,
                    id_of[q.image] if q.image else None,
                    q.text,
                    [id_of[item.image] for item in q.candidates] or None,
                )
                for q in queries
            ],
        )
        logger.info(
            "dataset %d: query set %r with %d queries, %d new images",
            dataset_id,
            query_set,
            len(queries),
            len(id_of) - len(known),
        )

    def load_embeddings(
        self, dataset_id: int, encoder: str, paths: list[str], emb_nd: npt.NDArray[np.float32]
    ) -> int:
        """Store image embeddings made elsewhere, and make the encoder's search index.

        Args:
            paths: The images, by path in the dataset, one per row of `emb_nd`; paths the dataset doesn't have
                are skipped.
            emb_nd: The embeddings, unit length.

        Returns:
            How many embeddings were stored.
        """
        id_of = self.db.datasets.image_ids_by_path(dataset_id)
        known = [i for i, path in enumerate(paths) if path in id_of]
        self.db.datasets.upsert_embeddings(encoder, [id_of[paths[i]] for i in known], emb_nd[known])
        self.db.datasets.ensure_hnsw_index(encoder, emb_nd.shape[1])
        logger.info(
            "loaded %d %s embeddings; %d dataset images have none",
            len(known),
            encoder,
            len(id_of) - len(known),
        )
        return len(known)

    def load_query_embeddings(
        self,
        dataset_id: int,
        query_set: str,
        encoder: str,
        external_ids: list[str],
        emb_nd: npt.NDArray[np.float32],
    ) -> int:
        """Store queries' own embeddings (text or composed queries) made elsewhere.

        Args:
            external_ids: The queries, by id in the query file, one per row of `emb_nd`; ids the set doesn't
                have are skipped.
            emb_nd: The embeddings, unit length.

        Returns:
            How many embeddings were stored.
        """
        id_of = {q.external_id: q.id for q in self.db.datasets.list_queries(dataset_id, query_set)}
        known = [i for i, external_id in enumerate(external_ids) if external_id in id_of]
        self.db.datasets.upsert_query_embeddings(
            encoder, [id_of[external_ids[i]] for i in known], emb_nd[known]
        )
        return len(known)

    def query_vector(self, query: QueryRow, encoder: str) -> npt.NDArray[np.float32] | None:
        """Return the query's own embedding (text and composed queries), else its image's; None if neither."""
        own = self.db.datasets.query_embedding(query.dataset_query_id, encoder)
        if own is not None:
            return own
        if query.image_id is None or (query.image_id, encoder) not in self.db.datasets.image_encoders(
            [query.image_id]
        ):
            return None
        vec_d: npt.NDArray[np.float32] = self.db.datasets.embeddings(encoder, [query.image_id])[0]
        return vec_d
