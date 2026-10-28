"""The recommendation: the fastest setting that keeps every realistic type's recall within the tolerance."""

from cara.services.simulator.plan import AnnotatorProfile
from cara.services.simulator.results import AnnotatorResult, SettingResult, recommend
from cara.simulation.assessors import GroupOnly, Perfect, Realistic

PROFILES = [
    AnnotatorProfile(name="Perfect", model=Perfect(kind="perfect")),
    AnnotatorProfile(name="Group-only", model=GroupOnly(kind="group_only")),
    AnnotatorProfile(name="Typical", model=Realistic(kind="realistic")),
    AnnotatorProfile(name="alice", model=Realistic(kind="realistic")),
]


def _setting(strategy: str, seconds: float, recalls: list[float]) -> SettingResult:
    return SettingResult(
        strategy=strategy,
        grouping={},
        solo_percentile=0.0,
        top_k_individual=0,
        is_current=False,
        queries=1,
        groups_per_pool=1.0,
        individual_share=0.0,
        min_actions_pc=0.1,
        actions_pc=0.1,
        recall_uncorrected=None,
        annotators=[AnnotatorResult(str(i), seconds, recall, None) for i, recall in enumerate(recalls)],
    )


def _recommended(results: list[SettingResult]) -> list[str]:
    return [result.strategy for result in recommend(results, PROFILES) if result.recommended]


def test_fastest_setting_that_keeps_recall_for_every_realistic_type() -> None:
    results = [
        _setting("one at a time", 5.0, [1.0, 1.0, 0.66, 0.70]),
        _setting("max 32", 1.4, [1.0, 0.0, 0.62, 0.69]),  # Typical loses 4 points
        _setting("max 16", 1.7, [1.0, 0.0, 0.72, 0.67]),  # alice loses 3 points
        _setting("max 8", 2.0, [1.0, 0.0, 0.81, 0.71]),
        _setting("max 4", 2.5, [1.0, 0.0, 0.85, 0.72]),
    ]
    assert _recommended(results) == ["max 8"]
    marked = recommend(results, PROFILES)
    assert [a.keeps_recall for a in marked[1].annotators] == [None, None, False, True]


def test_bounds_never_decide_and_one_at_a_time_is_the_fallback() -> None:
    results = [
        _setting("one at a time", 5.0, [1.0, 1.0, 0.66, 0.70]),
        _setting("max 32", 1.4, [1.0, 1.0, 0.60, 0.70]),
    ]
    assert _recommended(results) == ["one at a time"]


def test_no_recommendation_without_labels() -> None:
    results = [_setting("one at a time", 5.0, [None, None, None, None]), _setting("max 8", 2.0, [None] * 4)]  # type: ignore[list-item]
    assert _recommended(results) == []
