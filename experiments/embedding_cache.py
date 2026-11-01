"""For the Met builders: cached image embeddings, nearest-neighbour pools, fused and random pools."""

import logging
from pathlib import Path

import numpy as np
import numpy.typing as npt
import torch

from cara.encoders import build_encoder, device

logger = logging.getLogger(__name__)


def cached_images(
    paths: list[Path], encoder: str, cache: Path, batch_size: int, num_workers: int
) -> npt.NDArray[np.float16]:
    """Return the images' embeddings from `cache`, encoding and saving them there first if it doesn't exist.

    Raises:
        ValueError: The cache holds a different number of images; the message says to delete it.
    """
    if cache.exists():
        logger.info("cache hit: %s", cache)
        emb_nd: npt.NDArray[np.float16] = np.load(cache)
        if len(emb_nd) != len(paths):
            raise ValueError(
                f"{cache} has {len(emb_nd)} rows for {len(paths)} images; delete it to re-encode"
            )
        return emb_nd
    logger.info("cache miss, encoding %d images: %s", len(paths), cache)
    emb_nd = build_encoder(encoder).encode_images(paths, batch_size, num_workers)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, emb_nd)
    return emb_nd


def cache_name(prefix: str, encoder: str) -> str:
    """Return the cache file name for `prefix` embedded by `encoder` (its model id, made file-safe)."""
    return f"{prefix}__{build_encoder(encoder).model_id.replace('/', '--')}.npy"


def top_k(query_qd: npt.NDArray[np.float16], db_nd: npt.NDArray[np.float16], k: int) -> npt.NDArray[np.int64]:
    """Return the indices of the `k` most similar database rows per query (dot product), on a GPU if any."""
    db = torch.from_numpy(db_nd).to(device(), torch.float32)
    queries = torch.from_numpy(query_qd).to(device(), torch.float32)
    indices_qk = torch.cat(
        [(chunk @ db.T).topk(min(k, len(db)), dim=1).indices for chunk in queries.split(256)]
    )
    result: npt.NDArray[np.int64] = indices_qk.cpu().numpy()
    return result


RRF_K = 60
"""Reciprocal rank fusion's constant, as in Cormack, Clarke and Buettcher (SIGIR 2009)."""


def reciprocal_rank_fusion(rankings: list[list[int]], depth: int) -> list[int]:
    """Return the `depth` items with the highest summed 1 / (RRF_K + rank) over the rankings."""
    score: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            score[item] = score.get(item, 0.0) + 1 / (RRF_K + rank)
    return sorted(score, key=lambda item: -score[item])[:depth]


def fuse(rankings: list[npt.NDArray[np.int64]], depth: int) -> npt.NDArray[np.int64]:
    """Fuse rankings of the same queries (queries × depth, corpus indices) by reciprocal rank fusion.

    Used by the fused-pool experiments of the paper; the app itself pools several encoders as a union.
    """
    return np.array(
        [
            reciprocal_rank_fusion([ranked_k.tolist() for ranked_k in per_retriever], depth)
            for per_retriever in zip(*rankings, strict=True)
        ],
        dtype=np.int64,
    )


def random_pools(corpus_size: int, queries: int, depth: int, seed: int) -> npt.NDArray[np.int64]:
    """Return `depth` distinct corpus indices per query, drawn uniformly: the random-pool baseline."""
    rng = np.random.default_rng(seed)
    return np.stack([rng.choice(corpus_size, min(depth, corpus_size), replace=False) for _ in range(queries)])


def file_label(encoder: str) -> str:
    """Return an encoder name usable in a file name (`hf-dual:openai/clip` → `hf-dual_openai_clip`)."""
    return encoder.replace(":", "_").replace("/", "_")
