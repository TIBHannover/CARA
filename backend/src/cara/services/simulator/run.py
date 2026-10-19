"""One simulator run after its ground truth is read: embeddings, replay, comparison.

Each step reports progress as it goes; the last event carries the results.
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from cara.db.models import PoolRow
from cara.grouping import scores
from cara.repositories.database import Database
from cara.services.datasets import DatasetService
from cara.services.simulator.plan import SimulatorPlan, Source
from cara.services.simulator.replay import PoolInput, Setup, replay_all
from cara.services.simulator.results import SettingResult, SettingTally, mark_tradeoffs
from cara.services.studies import encoder_of
from cara.settings import StudySettings
from cara.simulation import ReviewRound, Setting


@dataclass(frozen=True, slots=True)
class SimulatorEvent:
    """One step of a run as it happens; the last event of a successful run carries the results.

    Attributes:
        images_in_study: With the results: how many images all pools of the study hold, for estimating how
            long judging the whole study takes.
    """

    step: Literal["labels", "embeddings", "replay", "compare", "error"]
    title: str
    done: int
    total: int
    message: str
    results: list[SettingResult] | None = None
    images_in_study: int | None = None


class SimulationRun:
    """One run of the simulator, after the ground truth is read: embeddings, replay, comparison.

    Args:
        db: Where the embeddings come from.
        sampled: The pools to replay, each with its ground truth (None when there are no labels).
        source: Where the ground truth came from, for the progress messages.
        started: When the run started (`time.perf_counter()`), for the final message.
    """

    def __init__(
        self,
        db: Database,
        study_id: int,
        settings: StudySettings,
        plan: SimulatorPlan,
        candidates: list[Setting],
        sampled: list[tuple[PoolRow, npt.NDArray[np.bool_] | None]],
        source: Source,
        seed: int,
        started: float,
    ) -> None:
        self.db, self.study_id, self.settings, self.plan = db, study_id, settings, plan
        self.candidates, self.sampled, self.source, self.seed = candidates, sampled, source, seed
        self.started = started
        self.datasets = DatasetService(db)

    def steps(self) -> Iterator[SimulatorEvent]:
        """Run the remaining steps, yielding progress events; the last one carries the results."""
        inputs: list[PoolInput] = []
        yield from self._embeddings(inputs)
        tallies = [SettingTally.empty(len(self.plan.annotators)) for _ in self.candidates]
        yield from self._replay(inputs, tallies)
        yield self._compare(tallies)

    def _embeddings(self, inputs: list[PoolInput]) -> Iterator[SimulatorEvent]:
        encoder, order = encoder_of(self.settings, "The settings simulator"), self.settings.order
        for index, (pool, truth_n) in enumerate(self.sampled):
            members = sorted(pool.members, key=lambda m: m.rank)
            emb_nd = self.db.datasets.embeddings(encoder, [m.image_id for m in members])
            query_emb_d = self.datasets.query_vector(pool.query, encoder) if order == "similarity" else None
            inputs.append(
                PoolInput(index, pool.query.external_id, emb_nd, scores(order, emb_nd, query_emb_d), truth_n)
            )
            yield SimulatorEvent(
                "embeddings",
                "Loading embeddings",
                index + 1,
                len(self.sampled),
                f"query {pool.query.external_id}: {len(members)} images, {emb_nd.shape[1]} dimensions",
            )

    def _replay(self, inputs: list[PoolInput], tallies: list[SettingTally]) -> Iterator[SimulatorEvent]:
        """Replay every pool, reporting each as it finishes; merge the tallies in query order at the end.

        Workers finish in any order, and floating-point sums depend on order, so merging in query order keeps
        the results exactly the same from run to run.
        """
        review = ReviewRound(
            enabled=self.settings.review.enabled,
            negatives_shown=self.settings.review.negatives_shown,
            order="relevant",
        )
        setup = Setup(self.candidates, review, self.plan.annotators, self.seed)
        profiles = len(self.plan.annotators)
        work = (
            f"grouped and judged by {profiles + 2} simulated annotators"
            if self.source != "none"
            else "grouped"
        )
        title = f"Replaying each query under {len(self.candidates)} settings"
        partials: dict[int, list[SettingTally]] = {}
        for done, (pool_input, partial, seconds_taken) in enumerate(replay_all(inputs, setup), 1):
            partials[pool_input.index] = partial
            yield SimulatorEvent(
                "replay",
                title,
                done,
                len(inputs),
                f"query {pool_input.query}: {work} under {len(self.candidates)} settings in "
                f"{seconds_taken:.1f} s",
            )
        for index in sorted(partials):
            for tally, part in zip(tallies, partials[index], strict=True):
                tally.merge(part)

    def _compare(self, tallies: list[SettingTally]) -> SimulatorEvent:
        results = mark_tradeoffs(
            [
                tally.result(setting, self.settings, self.plan.annotators)
                for setting, tally in zip(self.candidates, tallies, strict=True)
            ]
        )
        return SimulatorEvent(
            "compare",
            "Comparing settings",
            1,
            1,
            f"{len(results)} settings compared in {time.perf_counter() - self.started:.0f} s",
            results=results,
            images_in_study=sum(size for _, size in self.db.studies.pool_sizes(self.study_id)),
        )
