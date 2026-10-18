"""Embedding a dataset's images and text queries with an encoder (`cara encode`; needs the `encode` extra)."""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cara.encoders import build_encoder
from cara.repositories.database import Database
from cara.services.datasets import DatasetService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Encoded:
    """What one run encoded: images, text queries, and the composed queries it had to skip."""

    images: int
    text_queries: int
    skipped_composed: int


class EncodingService:
    """Embeddings made by CARA itself, with an encoder from `cara.encoders`."""

    def __init__(self, db: Database, image_root: Path) -> None:
        self.db = db
        self.image_root = image_root
        self.datasets = DatasetService(db)

    def encode(self, dataset_id: int, encoder_name: str, batch_size: int, num_workers: int) -> Encoded:
        """Embed every dataset image without an `encoder_name` embedding, and the text-only queries.

        Text queries need an encoder that also reads text (`hf-dual:`); an image-only encoder skips them
        with a warning. Composed queries (image and text) need an embedding from a composed retrieval method,
        loaded with the dataset; they are skipped here, with a warning that says so.

        Raises:
            NotFound: The dataset doesn't exist.
            ValueError: The encoder name isn't known (see `cara.encoders`).
        """
        dataset = self.datasets.get(dataset_id)
        encoder = build_encoder(encoder_name)
        missing = self.db.datasets.missing_embeddings(dataset_id, encoder_name)
        paths = sorted(missing)
        if paths:
            folder = self.image_root / dataset.path
            emb_nd = encoder.encode_images([folder / path for path in paths], batch_size, num_workers).astype(
                np.float32
            )
            emb_nd /= np.linalg.norm(emb_nd, axis=1, keepdims=True)
            self.datasets.load_embeddings(dataset_id, encoder_name, paths, emb_nd)
        texts, composed = 0, 0
        for query_set in self.db.datasets.query_sets(dataset_id):
            queries = self.db.datasets.list_queries(dataset_id, query_set)
            composed += sum(q.image_id is not None and bool(q.text) for q in queries)
            text_only = [q for q in queries if q.image_id is None and q.text]
            if not text_only:
                continue
            try:
                emb_nd = encoder.encode_texts([q.text or "" for q in text_only], batch_size).astype(
                    np.float32
                )
            except ValueError as error:
                logger.warning("query set %r: %s", query_set, error)
                continue
            emb_nd /= np.linalg.norm(emb_nd, axis=1, keepdims=True)
            texts += self.datasets.load_query_embeddings(
                dataset_id, query_set, encoder_name, [q.external_id for q in text_only], emb_nd
            )
        if composed:
            logger.warning(
                "%d composed queries (image and text) were not encoded: give them candidates, or a query "
                "embedding from your composed retrieval method (index/<encoder>/queries-<set>.npz)",
                composed,
            )
        return Encoded(len(paths), texts, composed)
