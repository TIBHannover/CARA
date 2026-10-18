"""κ, α, disagreements, consensus and the qrels and training-pair exports, on hand-computed cases."""

import pytest

from cara.core.agreement import alpha, disagreements, pairwise_kappa
from cara.core.export import consensus, qrels_lines, training_pairs

A = {("q", "a"): "yes", ("q", "b"): "no", ("q", "c"): "no", ("q", "d"): "yes"}
B = {("q", "a"): "yes", ("q", "b"): "no", ("q", "c"): "yes", ("q", "d"): "yes"}


def test_kappa_and_alpha_match_hand_computed_values() -> None:
    assert pairwise_kappa({"ann": A, "bob": B})[("ann", "bob")] == pytest.approx(0.5)
    assert alpha({"ann": A, "bob": A}, ["yes", "no"]) == pytest.approx(1.0)
    assert alpha({"ann": A}, ["yes", "no"]) is None


def test_disagreements_list_each_users_label() -> None:
    assert disagreements({"ann": A, "bob": B}) == {("q", "c"): {"ann": "no", "bob": "yes"}}


def test_consensus_prefers_adjudication_then_majority() -> None:
    assert consensus(["yes", "no"], "no") == "no"
    assert consensus(["yes", "yes", "no"], None) == "yes"
    assert consensus(["yes", "no"], None) is None
    assert consensus([], None) is None


def test_exports_only_complete_pools_and_rank_hard_negatives() -> None:
    pools = {"q": ["a", "b", "c", "d"]}
    grade_of = {"yes": 1, "no": 0, "unsure": None}
    assert qrels_lines(pools, {"q": {"a": "no"}}, grade_of) == []
    labels = {"q": {"a": "no", "b": "yes", "c": "no", "d": "unsure"}}
    assert qrels_lines(pools, labels, grade_of) == ["q 0 a 0", "q 0 b 1", "q 0 c 0"]
    assert training_pairs(pools, labels, grade_of) == [
        {"query_id": "q", "positives": ["b"], "hard_negatives": ["a", "c"]}
    ]
