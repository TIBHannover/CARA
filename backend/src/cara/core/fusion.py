"""Reciprocal rank fusion: one ranking from several (Cormack, Clarke and Buettcher, SIGIR 2009)."""

RRF_K = 60
"""The constant that damps the weight of top ranks; 60 as in the original paper."""


def reciprocal_rank_fusion(rankings: list[list[int]], depth: int) -> list[int]:
    """Return the `depth` items with the highest summed 1 / (RRF_K + rank) over the rankings.

    An item missing from a ranking adds nothing for it. Ties keep the order in which items were first seen,
    so the first ranking breaks them.
    """
    score: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            score[item] = score.get(item, 0.0) + 1 / (RRF_K + rank)
    return sorted(score, key=lambda item: -score[item])[:depth]
