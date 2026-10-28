"""What the simulator reports: per setting, effort and recall for each annotator type."""

from dataclasses import dataclass, field, replace

import numpy as np

from cara.services.simulator.plan import AnnotatorProfile
from cara.settings import StudySettings
from cara.simulation import Setting

RECALL_TOLERANCE = 0.02
"""How much recall a setting may lose against judging every image alone and still be recommended."""


@dataclass(frozen=True, slots=True)
class AnnotatorResult:
    """Time and recall of one simulated annotator profile under one setting.

    Attributes:
        min_seconds_pc: Seconds per image if every group were all relevant or all not relevant; it needs no
            labels, so every run has it, and it is a lower bound on `seconds_pc`.
        keeps_recall: Whether this type's recall stays within `RECALL_TOLERANCE` of its recall when judging
            every image on its own. None for the bounds (perfect and group-only types), which don't count
            toward the recommendation, and when there are no labels.
    """

    name: str
    seconds_pc: float | None
    recall: float | None
    min_seconds_pc: float | None
    keeps_recall: bool | None = None


@dataclass(frozen=True, slots=True)
class SettingResult:
    """One setting's results, averaged over the replayed pools.

    Attributes:
        groups_per_pool: Groups an annotator sees per query, on average.
        individual_share: Share of the images judged one by one.
        min_actions_pc: Actions per image if every group were pure; a lower bound.
        actions_pc: Actions per image of a perfect annotator; None without labels.
        recall_uncorrected: Recall of an annotator who never corrects an image; None without labels.
        recommended: Whether this is the run's recommended setting (`recommend`).
    """

    strategy: str
    grouping: dict[str, object]
    solo_percentile: float
    top_k_individual: int
    is_current: bool
    queries: int
    groups_per_pool: float
    individual_share: float
    min_actions_pc: float
    actions_pc: float | None
    recall_uncorrected: float | None
    annotators: list[AnnotatorResult]
    recommended: bool = False


@dataclass(slots=True)
class ProfileTally:
    """One annotator type's numbers under one setting, one value per replayed pool and repetition."""

    seconds_pc: list[float] = field(default_factory=list)
    recall: list[float] = field(default_factory=list)
    min_seconds_pc: list[float] = field(default_factory=list)

    def merge(self, other: "ProfileTally") -> None:
        """Add another worker's values for the same annotator type."""
        self.seconds_pc += other.seconds_pc
        self.recall += other.recall
        self.min_seconds_pc += other.min_seconds_pc

    def result(self, name: str) -> AnnotatorResult:
        """Average the values into the type's result."""
        return AnnotatorResult(name, _mean(self.seconds_pc), _mean(self.recall), _mean(self.min_seconds_pc))


@dataclass(slots=True)
class SettingTally:
    """One setting's numbers, summed over the replayed pools; tallies from parallel workers merge."""

    profiles: list[ProfileTally]
    pools: int = 0
    groups: float = 0.0
    individual_share: float = 0.0
    min_actions_pc: float = 0.0
    actions_pc: list[float] = field(default_factory=list)
    recall_uncorrected: list[float] = field(default_factory=list)

    @classmethod
    def empty(cls, profiles: int) -> "SettingTally":
        """Return an empty tally with room for this many annotator types."""
        return cls([ProfileTally() for _ in range(profiles)])

    def merge(self, other: "SettingTally") -> None:
        """Add another pool's tally for the same setting."""
        self.pools += other.pools
        self.groups += other.groups
        self.individual_share += other.individual_share
        self.min_actions_pc += other.min_actions_pc
        self.actions_pc += other.actions_pc
        self.recall_uncorrected += other.recall_uncorrected
        for mine, theirs in zip(self.profiles, other.profiles, strict=True):
            mine.merge(theirs)

    def result(
        self, setting: Setting, settings: StudySettings, annotators: list[AnnotatorProfile]
    ) -> SettingResult:
        """Average the tally into the setting's result, marking whether it is the study's current setting."""
        is_current = (setting.grouping, setting.solo_percentile, setting.top_k_individual) == (
            settings.grouping,
            settings.solo.percentile,
            settings.top_k_individual,
        )
        return SettingResult(
            strategy=setting.name,
            grouping=setting.grouping.model_dump(mode="json"),
            solo_percentile=setting.solo_percentile,
            top_k_individual=setting.top_k_individual,
            is_current=is_current,
            queries=self.pools,
            groups_per_pool=self.groups / self.pools,
            individual_share=self.individual_share / self.pools,
            min_actions_pc=self.min_actions_pc / self.pools,
            actions_pc=_mean(self.actions_pc),
            recall_uncorrected=_mean(self.recall_uncorrected),
            annotators=[
                tally.result(profile.name) for profile, tally in zip(annotators, self.profiles, strict=True)
            ],
        )


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def recommend(results: list[SettingResult], annotators: list[AnnotatorProfile]) -> list[SettingResult]:
    """Mark the fastest setting that keeps every realistic type within `RECALL_TOLERANCE` of its own recall.

    An ε-constraint over the types: minimise the mean time per image over the realistic types, subject to each
    type's recall staying within the tolerance of its recall when judging one image at a time. Perfect and
    group-only types are bounds and don't count. One at a time always qualifies, so a run with labels always
    has a recommendation.
    """
    voters = [i for i, profile in enumerate(annotators) if profile.model.kind == "realistic"]
    baseline = next(result for result in results if result.strategy == "one at a time")
    reference = {i: baseline.annotators[i].recall for i in voters}
    if not voters or any(recall is None for recall in reference.values()):
        return results

    def keeps(result: SettingResult, i: int) -> bool | None:
        if i not in reference:
            return None
        recall, floor = result.annotators[i].recall, reference[i]
        if recall is None or floor is None:
            return None
        return recall >= floor - RECALL_TOLERANCE - 1e-9

    def speed(result: SettingResult) -> float:
        seconds = [result.annotators[i].seconds_pc for i in voters]
        known = [s for s in seconds if s is not None]
        return float(np.mean(known)) if len(known) == len(seconds) else float("inf")

    eligible = [
        (speed(result), position)
        for position, result in enumerate(results)
        if all(keeps(result, i) for i in voters)
    ]
    best = min(eligible)[1] if eligible else None
    return [
        replace(
            result,
            recommended=position == best,
            annotators=[replace(a, keeps_recall=keeps(result, i)) for i, a in enumerate(result.annotators)],
        )
        for position, result in enumerate(results)
    ]
