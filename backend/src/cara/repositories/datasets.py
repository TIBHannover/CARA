"""Datasets with their images, embeddings and query sets; the nearest-neighbour search that builds pools."""

import logging
import re

import numpy as np
import numpy.typing as npt
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from cara.db.models import DatasetQueryRow, DatasetRow, EmbeddingRow, ImageRow, QueryEmbeddingRow
from cara.repositories.base import Repository

logger = logging.getLogger(__name__)

HNSW_MAX_DIM = 2000
"""pgvector's limit for an HNSW index on `vector` columns; wider embeddings are searched exactly."""
ENCODER_NAME = re.compile(r"^[A-Za-z0-9._:/-]+$")
"""The characters an encoder name may use; the same rule as `StudySettings.encoder`."""


class Datasets(Repository[DatasetRow]):
    """Datasets, and what belongs to one: images, their embeddings, query sets, query embeddings."""

    model = DatasetRow
    noun = "dataset"

    def create(self, name: str, path: str, description: str) -> DatasetRow:
        """Add a dataset and flush, so it has its id.

        Raises:
            sqlalchemy.exc.IntegrityError: A dataset with this name exists.
        """
        return self.add(DatasetRow(name=name, path=path, description=description))

    def named(self, name: str) -> DatasetRow | None:
        """Return the dataset with this name, or None."""
        return self.session.scalar(select(DatasetRow).where(DatasetRow.name == name))

    def add_queries(
        self,
        dataset_id: int,
        query_set: str,
        queries: list[tuple[str, int | None, str | None, list[int] | None]],
    ) -> None:
        """Add a query set's queries and flush.

        Args:
            queries: Per query: its id in the query file, its image id (None for text queries), its text (None
                for image queries), and the image ids of its given pool in rank order (None to build the pool
                from nearest neighbours).

        Raises:
            sqlalchemy.exc.IntegrityError: A query id appears twice in the set, or the set exists already.
        """
        self.session.add_all(
            DatasetQueryRow(
                dataset_id=dataset_id,
                query_set=query_set,
                external_id=external_id,
                image_id=image_id,
                text=query_text,
                candidates=candidates,
            )
            for external_id, image_id, query_text, candidates in queries
        )
        self.session.flush()

    def list_queries(self, dataset_id: int, query_set: str) -> list[DatasetQueryRow]:
        """Return a query set's queries, in the order they were added (the query file's order)."""
        return list(
            self.session.scalars(
                select(DatasetQueryRow)
                .where(DatasetQueryRow.dataset_id == dataset_id, DatasetQueryRow.query_set == query_set)
                .order_by(DatasetQueryRow.id)
            )
        )

    def query_sets(self, dataset_id: int) -> dict[str, int]:
        """Return the dataset's query sets and how many queries each holds, by name."""
        rows = self.session.execute(
            select(DatasetQueryRow.query_set, func.count())
            .where(DatasetQueryRow.dataset_id == dataset_id)
            .group_by(DatasetQueryRow.query_set)
            .order_by(DatasetQueryRow.query_set)
        )
        return {name: count for name, count in rows}

    def image_count(self, dataset_id: int) -> int:
        """Count the dataset's corpus images; query images that aren't in the corpus don't count."""
        return (
            self.session.scalar(
                select(func.count()).where(ImageRow.dataset_id == dataset_id, ImageRow.is_corpus)
            )
            or 0
        )

    def encoders(self, dataset_id: int) -> dict[str, int]:
        """Return the encoders with image embeddings in the dataset, and the corpus images each covers."""
        rows = self.session.execute(
            select(EmbeddingRow.encoder, func.count())
            .join(ImageRow, ImageRow.id == EmbeddingRow.image_id)
            .where(ImageRow.dataset_id == dataset_id, ImageRow.is_corpus)
            .group_by(EmbeddingRow.encoder)
        )
        return {encoder: count for encoder, count in rows}

    def query_encoders(self, dataset_query_ids: list[int]) -> set[tuple[int, str]]:
        """Return the (query, encoder) pairs for which a query has an embedding of its own."""
        rows = self.session.execute(
            select(QueryEmbeddingRow.dataset_query_id, QueryEmbeddingRow.encoder).where(
                QueryEmbeddingRow.dataset_query_id.in_(dataset_query_ids)
            )
        )
        return {(query_id, encoder) for query_id, encoder in rows}

    def image_encoders(self, image_ids: list[int]) -> set[tuple[int, str]]:
        """Return the (image, encoder) pairs that have an embedding."""
        rows = self.session.execute(
            select(EmbeddingRow.image_id, EmbeddingRow.encoder).where(EmbeddingRow.image_id.in_(image_ids))
        )
        return {(image_id, encoder) for image_id, encoder in rows}

    def upsert_query_embeddings(
        self, encoder: str, dataset_query_ids: list[int], emb_nd: npt.NDArray[np.float32]
    ) -> None:
        """Store the queries' own embeddings by this encoder, replacing any they had.

        Args:
            dataset_query_ids: The queries, one per row of `emb_nd`.
            emb_nd: Their embeddings, unit length.
        """
        rows = [
            {"dataset_query_id": i, "encoder": encoder, "vec": vec.tolist()}
            for i, vec in zip(dataset_query_ids, emb_nd, strict=True)
        ]
        if rows:
            statement = insert(QueryEmbeddingRow).values(rows)
            self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["dataset_query_id", "encoder"], set_={"vec": statement.excluded.vec}
                )
            )

    def query_embedding(self, dataset_query_id: int, encoder: str) -> npt.NDArray[np.float32] | None:
        """Return a query's own embedding by this encoder, or None if it has none (image queries never do)."""
        vec = self.session.scalar(
            select(QueryEmbeddingRow.vec).where(
                QueryEmbeddingRow.dataset_query_id == dataset_query_id, QueryEmbeddingRow.encoder == encoder
            )
        )
        return None if vec is None else np.asarray(vec, dtype=np.float32)

    def add_images(self, dataset_id: int, images: dict[str, tuple[str, bool]]) -> dict[str, int]:
        """Add images to a dataset, skipping any it has already.

        Args:
            images: Per image path (relative to the dataset's folder): its id in the dataset's files and
                whether it belongs to the corpus.

        Returns:
            The id of every image of the dataset, new or not, by path.
        """
        rows = [
            {"dataset_id": dataset_id, "path": path, "external_id": external_id, "is_corpus": is_corpus}
            for path, (external_id, is_corpus) in images.items()
        ]
        if rows:
            self.session.execute(insert(ImageRow).on_conflict_do_nothing(), rows)
        return self.image_ids_by_path(dataset_id)

    def image(self, image_id: int) -> ImageRow | None:
        """Return the image, or None if there is none with this id."""
        return self.session.get(ImageRow, image_id)

    def image_ids_by_path(self, dataset_id: int) -> dict[str, int]:
        """Return the id of every image of the dataset, by path."""
        rows = self.session.execute(
            select(ImageRow.path, ImageRow.id).where(ImageRow.dataset_id == dataset_id)
        )
        return {path: image_id for path, image_id in rows}

    def corpus_ids(self, dataset_id: int) -> list[int]:
        """Return the ids of the dataset's corpus images, in the order they were added."""
        return list(
            self.session.scalars(
                select(ImageRow.id)
                .where(ImageRow.dataset_id == dataset_id, ImageRow.is_corpus)
                .order_by(ImageRow.id)
            )
        )

    def missing_embeddings(self, dataset_id: int, encoder: str) -> dict[str, int]:
        """Return the dataset's images, corpus and query images, without an embedding by `encoder`."""
        embedded = select(EmbeddingRow.image_id).where(EmbeddingRow.encoder == encoder)
        rows = self.session.execute(
            select(ImageRow.path, ImageRow.id).where(
                ImageRow.dataset_id == dataset_id, ImageRow.id.not_in(embedded)
            )
        )
        return {path: image_id for path, image_id in rows}

    def upsert_embeddings(self, encoder: str, image_ids: list[int], emb_nd: npt.NDArray[np.float32]) -> None:
        """Store images' embeddings by this encoder, replacing any they had.

        Args:
            image_ids: The images, one per row of `emb_nd`.
            emb_nd: Their embeddings, unit length.
        """
        statement = insert(EmbeddingRow)
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["image_id", "encoder"], set_={"vec": statement.excluded.vec}
            ),
            [
                {"image_id": i, "encoder": encoder, "vec": vec}
                for i, vec in zip(image_ids, emb_nd, strict=True)
            ],
        )

    def ensure_hnsw_index(self, encoder: str, dim: int) -> None:
        """Create the HNSW index for one encoder's embeddings, unless it exists.

        Embeddings of every encoder share one column, so each encoder gets a partial index of its own, cast to
        its dimension. Above `HNSW_MAX_DIM` dimensions no index is made and nearest-neighbour pools use an
        exact scan, which is slower on large corpora; a `halfvec` index would cover up to 4,000 dimensions.

        Raises:
            ValueError: The encoder name has a character outside `ENCODER_NAME`; it is written into the
                index's SQL, which can't take parameters.
        """
        if not ENCODER_NAME.match(encoder):
            raise ValueError(f"encoder name {encoder!r} may only use letters, digits and . _ : / -")
        if dim > HNSW_MAX_DIM:
            logger.warning(
                "%s has %d dimensions, above pgvector's HNSW limit of %d: kNN pools use an exact scan",
                encoder,
                dim,
                HNSW_MAX_DIM,
            )
            return
        name = "ix_embeddings_hnsw_" + "".join(c if c.isalnum() else "_" for c in encoder.lower()) + f"_{dim}"
        self.session.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {name} ON embeddings "
                f"USING hnsw ((vec::vector({dim})) vector_cosine_ops) WHERE encoder = '{encoder}'"
            )
        )

    def embeddings(self, encoder: str, image_ids: list[int]) -> npt.NDArray[np.float32]:
        """Return the images' embeddings by this encoder, one row per image in the order given.

        Raises:
            KeyError: Some images have no embedding by this encoder; the message names a few and the command
                that makes them.
        """
        rows = self.session.execute(
            select(EmbeddingRow.image_id, EmbeddingRow.vec).where(
                EmbeddingRow.encoder == encoder, EmbeddingRow.image_id.in_(image_ids)
            )
        )
        vec_by_id = {image_id: vec for image_id, vec in rows}
        missing = [i for i in image_ids if i not in vec_by_id]
        if missing:
            raise KeyError(
                f"{len(missing)} images have no {encoder} embedding, e.g. image ids {missing[:3]}: "
                f"run cara encode <dataset> --encoder {encoder}"
            )
        return np.stack([vec_by_id[i] for i in image_ids]).astype(np.float32)

    def nearest(
        self, dataset_id: int, encoder: str, query_vec: npt.NDArray[np.float32], k: int
    ) -> list[tuple[int, float]]:
        """Return the dataset's corpus images most similar to `query_vec`, most similar first.

        Each comes with its cosine similarity to the query.

        Uses the encoder's HNSW index when it has one, with iterative scans (pgvector 0.8 or later), so the
        search still finds `k` images when the dataset filter removes most of the index's neighbours.
        """
        dim = len(query_vec)
        self.session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rows = self.session.execute(
            text(
                f"SELECT e.image_id, 1 - (e.vec::vector({dim}) <=> CAST(:q AS vector({dim}))) AS sim "
                "FROM embeddings e JOIN images i ON i.id = e.image_id "
                "WHERE e.encoder = :encoder AND i.dataset_id = :dataset_id AND i.is_corpus "
                f"ORDER BY e.vec::vector({dim}) <=> CAST(:q AS vector({dim})) LIMIT :k"
            ),
            {"q": str(query_vec.tolist()), "encoder": encoder, "dataset_id": dataset_id, "k": k},
        )
        return [(image_id, float(sim)) for image_id, sim in rows]
