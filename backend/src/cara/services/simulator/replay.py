"""Replaying the sampled pools: each one grouped under every setting and judged by every annotator type.

Pools are independent, so they run in parallel processes when there are enough of them.
"""

import multiprocessing
import os
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from threadpoolctl import threadpool_limits

from cara.services.simulator.plan import AnnotatorProfile
from cara.services.simulator.results import SettingTally
from cara.simulation import (
    AssessorModel,
    Grouped,
    Perfect,
    PoolCase,
    PoolOutcome,
    ReviewRound,
    RubberStamp,
    Setting,
    simulate_pool,
)


@dataclass(frozen=True, slots=True)
class PoolInput:
    """One sampled pool, as sent to a worker: its embeddings, scores and ground truth (None: no labels)."""

    index: int
    query: str
    emb_nd: npt.NDArray[np.float32]
    score_n: npt.NDArray[np.float32]
    truth_n: npt.NDArray[np.bool_] | None


@dataclass(frozen=True, slots=True)
class Setup:
    """What every pool is replayed under."""

    candidates: list[Setting]
    review: ReviewRound
    annotators: list[AnnotatorProfile]
    seed: int


def replay_all(
    inputs: list[PoolInput], setup: Setup
) -> Iterator[tuple[PoolInput, list[SettingTally], float]]:
    """Yield each pool with one tally per setting and the seconds it took, as pools finish.

    A small run stays in this process: starting workers would cost more than it saves (a 200-image pool takes
    about 2 s).
    """
    workers = min(len(inputs), os.cpu_count() or 1, 8)
    if workers < 3:
        for pool_input in inputs:
            yield pool_input, *replay_pool(pool_input, setup)
        return
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context, initializer=_one_thread) as executor:
        futures = {executor.submit(replay_pool, p, setup): p for p in inputs}
        for future in as_completed(futures):
            yield futures[future], *future.result()


def _one_thread() -> None:
    """Limit a worker process to one BLAS thread.

    With one thread per core in every worker, the processes fought over the cores and a pool took four times
    longer than in a single process.
    """
    threadpool_limits(limits=1)


def replay_pool(pool_input: PoolInput, setup: Setup) -> tuple[list[SettingTally], float]:
    """Replay one pool under every setting and return one tally per setting, and the seconds it took.

    Each setting's grouping is judged by a perfect annotator (the fewest actions), a careless one (recall
    without corrections) and each chosen type; each draws from its own random stream.
    """
    started = time.perf_counter()
    n = len(pool_input.score_n)
    tallies = []
    for setting_index, setting in enumerate(setup.candidates):
        grouped = setting.groups(pool_input.emb_nd, pool_input.score_n)
        tally = SettingTally.empty(len(setup.annotators))
        tally.pools = 1
        tally.groups = len(grouped.groups)
        tally.individual_share = len(grouped.individual) / n
        tally.min_actions_pc = (len(grouped.groups) + len(grouped.individual)) / n
        for profile, profile_tally in zip(setup.annotators, tally.profiles, strict=True):
            profile_tally.min_seconds_pc.append(profile.time.lower_bound(grouped, n) / n)
        if pool_input.truth_n is not None:
            case = PoolCase(
                pool_input.emb_nd, pool_input.truth_n, pool_input.score_n, setting.grouping.split_linkage
            )
            judge = _Judge(case, Grouped(grouped), [setup.seed, pool_input.index, setting_index])
            tally.actions_pc.append(judge(Perfect(kind="perfect"), ReviewRound(), [0]).actions / n)
            careless = judge(RubberStamp(kind="rubber_stamp"), setup.review, [1])
            if careless.n_relevant:
                tally.recall_uncorrected.append(careless.tp / careless.n_relevant)
            for profile_index, (profile, profile_tally) in enumerate(
                zip(setup.annotators, tally.profiles, strict=True)
            ):
                for rep in range(profile.repetitions):
                    outcome = judge(profile.model, setup.review, [2, profile_index, rep])
                    profile_tally.seconds_pc.append(profile.time.seconds(outcome) / n)
                    if outcome.n_relevant:
                        profile_tally.recall.append(outcome.tp / outcome.n_relevant)
        tallies.append(tally)
    return tallies, time.perf_counter() - started


@dataclass(frozen=True, slots=True)
class _Judge:
    """One pool grouped under one setting, ready to be judged by simulated annotators."""

    case: PoolCase
    workflow: Grouped
    seed: list[int]

    def __call__(self, assessor: AssessorModel, review: ReviewRound, stream: list[int]) -> PoolOutcome:
        """Let one annotator judge the pool, drawing from its own random stream (`stream`).

        Each annotator type has its own stream, so they don't share their mistakes.
        """
        rng = np.random.default_rng([*self.seed, *stream])
        return simulate_pool(self.case, self.workflow, assessor, review, rng)[0]
