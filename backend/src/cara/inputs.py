"""Reading a dataset's files: the corpus, the query sets and embeddings made elsewhere.

The folder layout is on the Datasets page of the docs.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Self

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class CorpusItem(BaseModel):
    """One image of the corpus, or one candidate of a query: its id and its path relative to the dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    image: str


class QueryIn(BaseModel):
    """One query as a query file holds it: an image, a text, or both (composed).

    Attributes:
        candidates: The query's pool in rank order; empty when CARA builds the pool from nearest neighbours.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_id: str
    image: str | None = None
    text: str | None = None
    candidates: list[CorpusItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _has_image_or_text(self) -> Self:
        if self.image is None and not self.text:
            raise ValueError(f"query {self.query_id!r} needs an image, a text, or both")
        return self


def _read_jsonl[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    items = []
    with path.open() as f:
        for number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                items.append(model.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as error:
                raise ValueError(f"{path}, line {number}: {error}") from error
    return items


def read_queries(path: Path) -> list[QueryIn]:
    """Read a query file, one JSON query per line; blank lines are skipped.

    Raises:
        ValueError: A line isn't valid JSON or not a valid query (the message names the file and the line), or
            two queries share a `query_id` (the message names them).
    """
    queries = _read_jsonl(path, QueryIn)
    if duplicates := [query_id for query_id, n in Counter(q.query_id for q in queries).items() if n > 1]:
        raise ValueError(f"{path}: query_id must be unique, repeated: {duplicates[:10]}")
    return queries


def read_corpus(path: Path) -> list[CorpusItem]:
    """Read `corpus.jsonl`, one `{"doc_id": ..., "image": ...}` per line; blank lines are skipped.

    Raises:
        ValueError: A line isn't valid JSON or not a valid item; the message names the file and the line.
    """
    return _read_jsonl(path, CorpusItem)


def read_embeddings(path: Path) -> tuple[list[str], npt.NDArray[np.float32]]:
    """Read embeddings made elsewhere from an `.npz` with `ids` and `emb_nd`, one row per id.

    Returns:
        The ids, and their embeddings scaled to unit length, so a dot product is the cosine similarity.

    Raises:
        ValueError: The file lacks `ids` or `emb_nd`, their lengths differ, or a row is all zeros (it has no
            direction to compare).
    """
    with np.load(path) as npz:
        if missing := {"ids", "emb_nd"} - set(npz.files):
            raise ValueError(f"{path}: needs arrays 'ids' and 'emb_nd', missing {sorted(missing)}")
        ids: list[str] = npz["ids"].tolist()
        emb_nd = npz["emb_nd"].astype(np.float32)
    if len(ids) != len(emb_nd):
        raise ValueError(f"{path}: {len(ids)} ids but {len(emb_nd)} embeddings")
    norms_n = np.linalg.norm(emb_nd, axis=1, keepdims=True)
    if zero := [ids[i] for i in np.flatnonzero(norms_n[:, 0] == 0)]:
        raise ValueError(f"{path}: all-zero embeddings for {zero[:10]}")
    return ids, emb_nd / norms_n
