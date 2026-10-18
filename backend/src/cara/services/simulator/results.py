"""What the simulator reports: per setting, effort and recall for each annotator type."""

from dataclasses import dataclass, field, replace

import numpy as np

from cara.services.simulator.plan import AnnotatorProfile
from cara.settings import StudySettings
from cara.simulation import Setting

RECALL_TOLERANCE = 0.02
"""How much recall a setting may lose against judging every image alone and still be the best trade-off."""


@dataclass(frozen=True, slots=True)
class AnnotatorResult:
    """Time and recall of one simulated annotator profile under one setting.

    Attributes:
        min_seconds_pc: Seconds per image if every group were all relevant or all not relevant; it needs no
            labels, so every run has it, and it is a lower bound on `seconds_pc`.
        best_tradeoff: Whether this is the fastest setting whose recall is within `RECALL_TOLERANCE` of
            judging every image on its own.
    """

    name: str
    seconds_pc: float | None
    recall: float | None
    min_seconds_pc: float | None
    best_tradeoff: bool = False


@dataclass(frozen=True, slots=True)
class SettingResult:
    """One setting's results, averaged over the replayed pools.

    Attributes:
        groups_per_pool: Groups an annotator sees per query, on average.
        individual_share: Share of the images judged one by one.
        min_actions_pc: Actions per image if every group were pure; a lower bound.
        actions_pc: Actions per image of a perfect annotator; None without labels.
        recall_uncorrected: Recall of an annotator who never corrects an image; None without labels.
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


def mark_tradeoffs(results: list[SettingResult]) -> list[SettingResult]:
    """Mark, for each annotator type, the fastest setting within `RECALL_TOLERANCE` of one at a time's recall.

    The CLI shows the mark; the app shows the trade-off front instead and leaves the choice to the admin.
    """
    baseline = next(result for result in results if result.strategy == "one at a time")
    best: dict[int, int] = {}
    for index, reference in enumerate(baseline.annotators):
        if reference.recall is None:
            continue
        floor = reference.recall - RECALL_TOLERANCE
        eligible = [
            (result.annotators[index].seconds_pc, position)
            for position, result in enumerate(results)
            if (recall := result.annotators[index].recall) is not None
            and recall >= floor
            and result.annotators[index].seconds_pc is not None
        ]
        if eligible:
            best[index] = min(eligible)[1]
    return [
        replace(
            result,
            annotators=[
                replace(a, best_tradeoff=best.get(i) == position) for i, a in enumerate(result.annotators)
            ],
        )
        for position, result in enumerate(results)
    ]
