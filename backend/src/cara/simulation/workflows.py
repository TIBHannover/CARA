"""How an annotator works through a pool: the app's groups, or Suggest mode; then, optionally, a review round.

A workflow labels the pool and returns the tally; the assessor decides every individual step (see
assessors.py).
"""

import zlib
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt
from pydantic import Field

from cara.core.suggest import merge_threshold, suggest
from cara.grouping import GroupingSettings, PoolGroups
from cara.settings import Frozen
from cara.simulation.assessors import AssessorModel
from cara.simulation.case import PoolCase, Tally


class Workflow(Protocol):
    """How an annotator works through a pool."""

    def label(self, case: PoolCase, assessor: AssessorModel, rng: np.random.Generator) -> Tally:
        """Label every image of the pool as the assessor would, and return what it did."""
        ...


def _handle_group(
    tally: Tally,
    case: PoolCase,
    members: npt.NDArray[np.intp],
    label: bool,
    assessor: AssessorModel,
    rng: np.random.Generator,
) -> npt.NDArray[np.bool_]:
    """Label a whole group with one action, then let the annotator correct members; return those corrected."""
    tally.group_clicks += 1
    corrected_n = assessor.corrections(case, members, label, tally.perceived_n, rng)
    tally.override_clicks += int(corrected_n.sum())
    tally.final_n[members] = np.where(corrected_n, tally.perceived_n[members], label)
    return corrected_n


@dataclass(frozen=True, slots=True)
class Grouped:
    """The app's grouping: images judged one by one, then each group labelled as a whole."""

    pool: PoolGroups

    def label(self, case: PoolCase, assessor: AssessorModel, rng: np.random.Generator) -> Tally:
        """Judge the images set aside one by one, then handle each group as its true majority label.

        An annotator that splits (see `split_cost`) is charged for its splits instead of corrections.
        """
        tally = Tally.start(case, assessor.perceive(case.truth_n, rng))
        tally.judge_alone(self.pool.individual)
        tally.n_groups = len(self.pool.groups)
        for group in self.pool.groups:
            majority = case.majority(group)
            members = np.array(group)
            tally.mark_group(case, members, majority)
            if (cost := assessor.split_cost(case, group)) is not None:
                tally.group_clicks += cost[0]
                tally.override_clicks += cost[1]
                tally.split_clicks += cost[2]
            else:
                _handle_group(tally, case, members, majority, assessor, rng)
        return tally


class SuggestWorkflow(Frozen):
    """The app's Suggest mode as a workflow.

    Judge images one by one (most similar to the query first) until `min_seeds` are labelled Not Relevant,
    then repeatedly take the first suggestion as the app lists it (Relevant ones first, then the largest),
    handle it like a group, and judge one image by hand whenever nothing is suggested. Corrections become new
    seeds, as in the app. The settings mean what they mean in the study settings' `suggest`.
    """

    min_seeds: int = Field(default=2, ge=1)
    min_margin: float = Field(default=0.05, ge=0.0, le=1.0)
    merge_percentile: float = Field(default=50.0, ge=0.0, le=100.0)

    def label(self, case: PoolCase, assessor: AssessorModel, rng: np.random.Generator) -> Tally:
        """Label the pool by the app's rule (`core.suggest`); without a query image, it ignores the query."""
        n = len(case)
        tally = Tally.start(case, assessor.perceive(case.truth_n, rng))
        sim_nn = case.emb_nd @ case.emb_nd.T
        threshold = merge_threshold(sim_nn, self.merge_percentile)
        by_query = np.argsort(-case.score_n, kind="stable")
        judged_n = np.zeros(n, dtype=bool)
        seed_n = np.zeros(n, dtype=bool)

        def judge_one() -> None:
            i = int(by_query[~judged_n[by_query]][0])
            tally.judge_alone(i)
            judged_n[i] = seed_n[i] = True

        while not judged_n.all():
            seeds = np.flatnonzero(seed_n)
            positive_s = tally.final_n[seeds]
            open_ = np.flatnonzero(~judged_n)
            if int((~positive_s).sum()) < self.min_seeds:
                judge_one()
                continue
            found, _ = suggest(
                sim_nn[np.ix_(open_, seeds)],
                sim_nn[np.ix_(seeds, seeds)],
                positive_s,
                case.query_sim_n[open_] if case.query_sim_n is not None else None,
                self.min_margin,
                threshold,
            )
            if not found:
                judge_one()
                continue
            members = open_[found[0].members]
            label = found[0].relevant
            tally.n_groups += 1
            tally.mark_group(case, members, label)
            corrected_n = _handle_group(tally, case, members, label, assessor, rng)
            judged_n[members] = True
            seed_n[members[corrected_n]] = True
        return tally


class ReviewRound(Frozen):
    """After judging, the annotator goes over the images labelled Relevant and the first Not Relevant ones.

    It flips what it sees differently; an annotator that never corrects (`corrects_in_review`) only looks.

    Attributes:
        negatives_shown: How many Not Relevant images the review shows.
        inspect_prob: The chance the annotator looks at each image shown.
        order: Which Not Relevant images come first: those most similar to the query (`query`, the 13 Oct
            runs), or those most similar to the images labelled Relevant (`relevant`, the app's review, where
            missed Relevant images are likely).
    """

    enabled: bool = False
    negatives_shown: int = Field(default=60, ge=0)
    inspect_prob: float = Field(default=1.0, ge=0.0, le=1.0)
    order: Literal["query", "relevant"] = "query"

    def apply(
        self, tally: Tally, case: PoolCase, assessor: AssessorModel, rng: np.random.Generator
    ) -> tuple[npt.NDArray[np.bool_], int]:
        """Show the review, let the annotator flip labels, and return the images shown and the flips."""
        if not self.enabled:
            return np.zeros(len(case), dtype=bool), 0
        negatives = np.flatnonzero(~tally.final_n)
        relevant = np.flatnonzero(tally.final_n)
        if self.order == "relevant" and len(relevant) and len(negatives):
            first_n = -(case.emb_nd[negatives] @ case.emb_nd[relevant].T).max(axis=1)
        else:
            first_n = -case.score_n[negatives]
        negatives = negatives[np.argsort(first_n, kind="stable")][: self.negatives_shown]
        shown = np.concatenate([relevant, negatives])
        shown_n = np.zeros(len(case), dtype=bool)
        shown_n[shown] = True
        if not assessor.corrects_in_review:
            return shown_n, 0
        inspected = shown[rng.random(len(shown)) < self.inspect_prob]
        flips = inspected[tally.perceived_n[inspected] != tally.final_n[inspected]]
        tally.final_n[flips] = ~tally.final_n[flips]
        return shown_n, len(flips)


class Setting(Frozen):
    """A setting to compare: a grouping with its rules for images judged alone, or Suggest mode.

    Attributes:
        name: How results name it (their `strategy` column, kept from the study's first runs).
        solo_percentile: As the study settings' `solo.percentile`.
        top_k_individual: As the study settings' `top_k_individual`.
        suggest: When set, Suggest mode replaces the grouping, which is then unused (use method `none`).
        shuffle_groups: The random-groups baseline of the simulation study: group as usual, then deal the
            grouped images into groups of the same sizes at random, so only whether a group's images look
            alike changes. Images judged alone stay alone.
    """

    name: str
    grouping: GroupingSettings
    solo_percentile: float = Field(default=0.0, ge=0.0, le=100.0)
    top_k_individual: int = Field(default=0, ge=0)
    suggest: SuggestWorkflow | None = None
    shuffle_groups: bool = False

    def groups(self, emb_nd: npt.NDArray[np.float32], score_n: npt.NDArray[np.float32]) -> PoolGroups:
        """Return the pool's groups and images judged alone under this setting.

        With `shuffle_groups`, the shuffle is seeded by the pool's scores, so a pool shuffles the same way
        every time.
        """
        grouped = self.grouping.group(emb_nd, score_n, self.solo_percentile, self.top_k_individual)
        if not self.shuffle_groups:
            return grouped
        rng = np.random.default_rng(zlib.crc32(np.ascontiguousarray(score_n).tobytes()))
        dealt = rng.permutation([member for group in grouped.groups for member in group]).tolist()
        bounds = np.cumsum([0] + [len(group) for group in grouped.groups])
        groups = [dealt[start:end] for start, end in zip(bounds[:-1], bounds[1:], strict=True)]
        return PoolGroups(groups=groups, individual=grouped.individual)

    def workflow(self, emb_nd: npt.NDArray[np.float32], score_n: npt.NDArray[np.float32]) -> Workflow:
        """Return the workflow for a pool: Suggest mode if set, else its groups."""
        return self.suggest if self.suggest is not None else Grouped(self.groups(emb_nd, score_n))
