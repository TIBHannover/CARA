"""The simulation engine: each simulated annotator, splits, the review, Suggest mode, the study's rows."""

from pathlib import Path

import numpy as np
import numpy.typing as npt
from conftest import blobs

from cara.grouping import PoolGroups
from cara.grouping.agglomerative import Agglomerative
from cara.grouping.none import NoGrouping
from cara.simulation import (
    Grouped,
    Perfect,
    PoolCase,
    PoolOutcome,
    Realistic,
    ReviewRound,
    RubberStamp,
    Setting,
    SuggestWorkflow,
    TimeModel,
    simulate_pool,
)
from cara.simulation.experiment import (
    AgglomerativeGrid,
    DatasetSpec,
    NamedAssessor,
    NamedReview,
    QrelsSpec,
    QueryInput,
    SimulationConfig,
    average_precision,
    simulate_query,
)

TRUTH = np.array([True, False, False, False])
EMB = blobs(n_blobs=2, per_blob=2)
SCORE = np.array([4.0, 3.0, 2.0, 1.0], dtype=np.float32)
ONE_GROUP = PoolGroups(groups=[[0, 1, 2, 3]], individual=[])
OFF = ReviewRound()
RNG = np.random.default_rng(0)


def run(
    emb: npt.NDArray[np.float32],
    truth: npt.NDArray[np.bool_],
    score: npt.NDArray[np.float32],
    pool: PoolGroups,
    assessor: Perfect | RubberStamp | Realistic,
    review: ReviewRound,
    rng: np.random.Generator,
    suggest: SuggestWorkflow | None = None,
) -> tuple[PoolOutcome, npt.NDArray[np.bool_]]:
    workflow = suggest if suggest is not None else Grouped(pool)
    return simulate_pool(PoolCase(emb, truth, score), workflow, assessor, review, rng)


def test_perfect_assessor_clicks_the_group_then_fixes_the_minority() -> None:
    out, _ = run(EMB, TRUTH, SCORE, ONE_GROUP, Perfect(kind="perfect"), OFF, RNG)
    assert (out.group_clicks, out.override_clicks, out.fn, out.fp, out.actions) == (1, 1, 0, 0, 2)


def test_rubber_stamp_turns_the_minority_positive_into_a_false_negative() -> None:
    out, _ = run(EMB, TRUTH, SCORE, ONE_GROUP, RubberStamp(kind="rubber_stamp"), OFF, RNG)
    assert (out.fn, out.fn_group_minority, out.tn, out.actions) == (1, 1, 3, 1)


def test_realistic_assessor_brackets_perfect_and_rubber_stamp() -> None:
    sharp = Realistic(kind="realistic", acc_relevant=1, acc_nonrelevant=1)
    out, _ = run(EMB, TRUTH, SCORE, ONE_GROUP, sharp, OFF, RNG)
    assert (out.override_clicks, out.fn) == (1, 0)
    skimming = sharp.model_copy(update={"full_inspection_size": 2, "inspect_prob_large": 0.0})
    out, _ = run(EMB, TRUTH, SCORE, ONE_GROUP, skimming, OFF, RNG)
    assert (out.override_clicks, out.fn) == (0, 1)


def test_perfect_splits_a_group_only_when_it_saves_clicks() -> None:
    perfect = Perfect(kind="perfect", split=True)
    emb, truth = blobs(n_blobs=2, per_blob=3), np.array([True] * 3 + [False] * 3)
    pool, score = PoolGroups(groups=[list(range(6))], individual=[]), np.zeros(6, dtype=np.float32)
    out, _ = run(emb, truth, score, pool, perfect, OFF, RNG)
    assert (out.split_clicks, out.group_clicks, out.override_clicks, out.fn) == (1, 2, 0, 0)
    tie, _ = run(EMB, np.array([True, True, False, False]), SCORE, ONE_GROUP, perfect, OFF, RNG)
    assert tie.split_clicks == 0


def test_review_round_recovers_a_missed_positive() -> None:
    sharp = Realistic(
        kind="realistic", acc_relevant=1, acc_nonrelevant=1, full_inspection_size=1, inspect_prob_large=0
    )
    out, _ = run(EMB, TRUTH, SCORE, ONE_GROUP, sharp, ReviewRound(enabled=True, negatives_shown=2), RNG)
    assert (out.review_flips, out.fn, out.review_shown_nonrelevant) == (1, 0, 1)


def test_one_at_a_time_baseline_and_time_model() -> None:
    emb = blobs()
    pool = NoGrouping(method="none").group(emb, emb @ emb[0], 0, 0)
    truth = np.arange(len(emb)) < 5
    out, _ = run(emb, truth, emb @ emb[0], pool, Perfect(kind="perfect"), OFF, RNG)
    assert out.actions == out.individual_clicks == len(emb)
    assert TimeModel(single_s=5).seconds(out) == 5 * len(emb)


def test_average_precision() -> None:
    assert average_precision(np.array([3.0, 2.0, 1.0]), np.array([True, False, True])) == (1 + 2 / 3) / 2
    assert average_precision(np.array([3.0, 2.0]), np.array([False, False])) == 0.0


def test_simulate_query_rows_cover_the_grid() -> None:
    emb = blobs()
    config = SimulationConfig(
        dataset=DatasetSpec(name="t", folder=Path("."), qrels={"inst": QrelsSpec(path=Path("x"))}),
        depths=[50, 150],
        strategies=[Setting(name="one", grouping=NoGrouping(method="none"))],
        grid=AgglomerativeGrid(max_size=[8, 16], solo_percentile=[0], top_k_individual=[0, 5]),
        assessors=[
            NamedAssessor(name="perfect", assessor=Perfect(kind="perfect")),
            NamedAssessor(name="realistic", assessor=Realistic(kind="realistic", repetitions=2)),
        ],
        reviews=[
            NamedReview(name="off", round=ReviewRound()),
            NamedReview(name="on", round=ReviewRound(enabled=True)),
        ],
    )
    query = QueryInput("q", emb, emb[0], {"inst": np.arange(len(emb)) < 30}, {"sys": emb @ emb[0]})
    rows = simulate_query(query, config)
    assert len(rows) == 2 * 5 * (1 + 2)
    baseline = next(
        r for r in rows if r["strategy"] == "one" and r["assessor"] == "perfect" and r["depth"] == 150
    )
    assert baseline["actions"] == 150 and baseline["fn"] == 0
    assert baseline["ap_sim.sys"] == baseline["ap_true.sys"]


def test_review_never_overturns_images_already_judged_one_by_one() -> None:
    emb = blobs()
    pool = NoGrouping(method="none").group(emb, emb @ emb[0], 0, 0)
    truth = np.arange(len(emb)) < 30
    realistic = Realistic(kind="realistic")
    rounds = [ReviewRound(), ReviewRound(enabled=True, negatives_shown=len(emb))]
    plain, with_review = (
        run(emb, truth, emb @ emb[0], pool, realistic, r, np.random.default_rng(1))[0] for r in rounds
    )
    assert with_review.review_flips == 0 and with_review.fn == plain.fn


def test_review_can_show_the_not_relevant_images_most_like_the_relevant_ones_first() -> None:
    # Blob A = images 0-2 (all Relevant), blob B = 3-5. A rubber stamp on group [2..5] misses image 2; the
    # query score ranks blob B first, so a 1-image review by query misses it, by Relevant images finds it.
    emb, truth = blobs(n_blobs=2, per_blob=3), np.array([True] * 3 + [False] * 3)
    score = np.array([6.0, 5.0, 1.0, 4.0, 3.0, 2.0], dtype=np.float32)
    pool = PoolGroups(groups=[[0, 1], [2, 3, 4, 5]], individual=[])
    sharp = Realistic(
        kind="realistic", acc_relevant=1, acc_nonrelevant=1, full_inspection_size=1, inspect_prob_large=0
    )
    for order, missed in [("query", 1), ("relevant", 0)]:
        round_ = ReviewRound(enabled=True, negatives_shown=1, order=order)
        out, _ = run(emb, truth, score, pool, sharp, round_, np.random.default_rng(0))
        assert out.fn == missed, order


def test_suggest_workflow_judges_seeds_one_by_one_then_accepts_groups() -> None:
    emb, truth = blobs(n_blobs=3, per_blob=4), np.array([True] * 4 + [False] * 8)
    score = np.linspace(12, 1, 12).astype(np.float32)
    workflow = SuggestWorkflow(min_seeds=1, min_margin=0.0)
    empty = PoolGroups(groups=[], individual=[])
    rng = np.random.default_rng(0)
    out, final = run(emb, truth, score, empty, Perfect(kind="perfect"), OFF, rng, workflow)
    assert out.fn == 0 and out.fp == 0 and bool((final == truth).all())
    assert out.individual_clicks >= 1 and out.n_groups >= 1 and out.actions < len(truth)
    # Rubber stamp accepts every suggestion: a group of suggestions never mixes labels here, so no errors.
    out, _ = run(emb, truth, score, empty, RubberStamp(kind="rubber_stamp"), OFF, rng, workflow)
    assert out.fn + out.fp == 0


def test_shuffled_groups_keep_their_sizes_and_the_images_judged_alone() -> None:
    emb_nd = blobs(n_blobs=4, per_blob=8)
    score_n = emb_nd @ emb_nd[0]
    grouping = Agglomerative(method="agglomerative", max_size=8)
    plain = Setting(name="g", grouping=grouping, solo_percentile=10).groups(emb_nd, score_n)
    shuffled = Setting(name="r", grouping=grouping, solo_percentile=10, shuffle_groups=True)
    dealt = shuffled.groups(emb_nd, score_n)
    assert [len(g) for g in dealt.groups] == [len(g) for g in plain.groups]
    assert dealt.individual == plain.individual
    assert sorted(m for g in dealt.groups for m in g) == sorted(m for g in plain.groups for m in g)
    assert dealt.groups != plain.groups
    assert shuffled.groups(emb_nd, score_n) == dealt
