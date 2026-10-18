"""The simulation study (`experiments/simulate.py`, configs in `configs/`): its config schema, and one query.

One query is replayed under every setting, pool depth, ground truth, simulated annotator and review variant.
"""

import zlib
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import Field

from cara.grouping import Linkage, scores
from cara.grouping.agglomerative import Agglomerative
from cara.settings import Frozen
from cara.simulation import PoolCase, ReviewRound, Setting, Workflow, simulate_pool
from cara.simulation.assessors import Assessor


class AgglomerativeGrid(Frozen):
    """Agglomerative settings to compare: every combination of these values is one setting."""

    linkage: list[Linkage] = ["average"]
    max_size: list[int]
    solo_percentile: list[float]
    top_k_individual: list[int]

    def expand(self) -> list[Setting]:
        """Return one setting per combination, named like `agglo-average-G16-solo10-top0`."""
        return [
            Setting(
                name=f"agglo-{linkage}-G{size}-solo{solo:g}-top{top_k}",
                grouping=Agglomerative(method="agglomerative", linkage=linkage, max_size=size),
                solo_percentile=solo,
                top_k_individual=top_k,
            )
            for linkage, size, solo, top_k in product(
                self.linkage, self.max_size, self.solo_percentile, self.top_k_individual
            )
        ]


class NamedAssessor(Frozen):
    """A simulated annotator, with the name results give it."""

    name: str
    assessor: Assessor


class NamedReview(Frozen):
    """A review variant, with the name results give it (such as `none`)."""

    name: str
    round: ReviewRound


class QrelsSpec(Frozen):
    """A ground truth: a qrels file, and the queries to leave out of it.

    Attributes:
        path: The qrels file, relative to the dataset folder.
        exclude: Query ids not to simulate.
    """

    path: Path
    exclude: list[str] = Field(default_factory=list)


class DatasetSpec(Frozen):
    """The dataset a simulation study runs on.

    Attributes:
        folder: The dataset folder (see `experiments/build_met_dataset.py`).
        embeddings: The file in it with the pools' embeddings.
        order: How each pool's images are scored for the query, as in the study settings' `order`.
        qrels: The ground truths to compare, by name.
        systems: Retrieval systems' scores to rank the pools with, by name and file, for average precision
            under true and simulated labels.
        max_queries: Simulate only this many queries, for quick runs.
    """

    name: str
    folder: Path
    embeddings: str = "embeddings.npz"
    order: Literal["similarity", "pool_rank"] = "similarity"
    qrels: dict[str, QrelsSpec]
    systems: dict[str, str] = Field(default_factory=dict)
    max_queries: int | None = Field(default=None, ge=1)


class SimulationConfig(Frozen):
    """A whole simulation study, as its Hydra config gives it.

    Attributes:
        depths: Pool depths to cut each pool to (the first n images).
        strategies: Settings listed one by one; `grid` adds more (the key keeps its first name).
        seed: The base of every random seed, so a study runs the same every time.
        workers: Queries simulated in parallel.
    """

    dataset: DatasetSpec
    depths: list[int] = Field(min_length=1)
    strategies: list[Setting] = Field(default_factory=list)
    grid: AgglomerativeGrid | None = None
    assessors: list[NamedAssessor] = Field(min_length=1)
    reviews: list[NamedReview] = Field(min_length=1)
    seed: int = 0
    workers: int = Field(default=1, ge=1)

    def all_settings(self) -> list[Setting]:
        """Return the listed settings and the grid's.

        Raises:
            ValueError: Two settings share a name.
        """
        found = self.strategies + (self.grid.expand() if self.grid else [])
        names = [s.name for s in found]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate setting names: {names}")
        return found


@dataclass(frozen=True, slots=True)
class QueryInput:
    """One query's data for the study.

    Attributes:
        emb_nd: The pool's embeddings, deepest pool, in rank order.
        query_emb_d: The query's embedding; None without one.
        truth_by_qrels: Whether each image is relevant, by ground truth.
        system_scores: Each retrieval system's score per image, by system.
    """

    query_id: str
    emb_nd: npt.NDArray[np.float32]
    query_emb_d: npt.NDArray[np.float32] | None
    truth_by_qrels: dict[str, npt.NDArray[np.bool_]]
    system_scores: dict[str, npt.NDArray[np.float32]]


def average_precision(score_n: npt.NDArray[np.float32], relevant_n: npt.NDArray[np.bool_]) -> float:
    """Return the average precision of the pool ranked by `score_n`; 0 without relevant images."""
    n_relevant = int(relevant_n.sum())
    if n_relevant == 0:
        return 0.0
    hits_n = relevant_n[np.argsort(-score_n, kind="stable")]
    precision_n = np.cumsum(hits_n) / np.arange(1, len(hits_n) + 1)
    return float(precision_n[hits_n].sum() / n_relevant)


def simulate_query(query: QueryInput, config: SimulationConfig) -> list[dict[str, float | int | str]]:
    """Return one results row per depth, setting, ground truth, annotator and review variant.

    Each row has the setting's keys and the outcome's counts, averaged over the annotator's repetitions. Seeds
    come from the config's seed, the query id and the row's indices, so any row can be rerun by itself.
    Suggest mode compares with the query image when there is one: with `order: similarity`, `score_n` is its
    similarity.
    """
    rows: list[dict[str, float | int | str]] = []
    candidates = config.all_settings()
    depths = [depth for depth in config.depths if depth <= len(query.emb_nd)]
    query_seed = zlib.crc32(query.query_id.encode())
    for depth, (setting_index, setting) in product(depths, enumerate(candidates)):
        emb_nd = query.emb_nd[:depth]
        score_n = scores(config.dataset.order, emb_nd, query.query_emb_d)
        workflow = setting.workflow(emb_nd, score_n)
        keys: dict[str, float | int | str] = {
            "dataset": config.dataset.name,
            "query_id": query.query_id,
            "depth": depth,
            "strategy": setting.name,
            "method": setting.grouping.method,
            "max_size": setting.grouping.max_size,
            "solo_percentile": setting.solo_percentile,
            "top_k_individual": setting.top_k_individual,
        }
        for (qrels_index, (qrels_name, truth_full_n)), (assessor_index, named) in product(
            enumerate(query.truth_by_qrels.items()), enumerate(config.assessors)
        ):
            case = PoolCase(
                emb_nd,
                truth_full_n[:depth],
                score_n,
                setting.grouping.split_linkage,
                score_n if config.dataset.order == "similarity" else None,
            )
            seed = [config.seed, query_seed, depth, setting_index, qrels_index, assessor_index]
            reviews = config.reviews if named.assessor.varies_with_review else config.reviews[:1]
            for review in reviews:
                row = _assessor_row(query, case, workflow, named, review, seed)
                rows.append(keys | {"qrels": qrels_name, "assessor": named.name, "review": review.name} | row)
    return rows


def _assessor_row(
    query: QueryInput,
    case: PoolCase,
    workflow: Workflow,
    named: NamedAssessor,
    review: NamedReview,
    seed: list[int],
) -> dict[str, float | int | str]:
    depth = len(case)
    reps = named.assessor.runs()
    """Average one annotator's repetitions on one pool under one review variant, with each system's AP.

    Every review variant of one repetition draws from the same seed, so they see the same perceptions (common
    random numbers) and differ only by the review.
    """
    rows, ap_sim = [], dict.fromkeys(query.system_scores, 0.0)
    for rep in range(reps):
        rng = np.random.default_rng([*seed, rep])
        outcome, final_n = simulate_pool(case, workflow, named.assessor, review.round, rng)
        rows.append(outcome.as_row() | {"actions": outcome.actions})
        for name, system_n in query.system_scores.items():
            ap_sim[name] += average_precision(system_n[:depth], final_n) / reps
    row: dict[str, float | int | str] = {key: float(np.mean([r[key] for r in rows])) for key in rows[0]}
    for name, system_n in query.system_scores.items():
        row[f"ap_true.{name}"] = average_precision(system_n[:depth], case.truth_n)
        row[f"ap_sim.{name}"] = ap_sim[name]
    return row
