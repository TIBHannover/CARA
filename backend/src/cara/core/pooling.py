"""Depth pooling: the union of several rankings' top items, as in TREC pooling."""


def union_pool(rankings: list[list[int]]) -> list[int]:
    """Return every item of the rankings once, ordered by its best rank.

    Each ranking is already cut to its depth. Items ranked first anywhere come first, then those ranked
    second, and so on; at the same rank, the earlier ranking goes first.
    """
    best: dict[int, tuple[int, int]] = {}
    for order, ranking in enumerate(rankings):
        for rank, item in enumerate(ranking):
            best[item] = min(best.get(item, (rank, order)), (rank, order))
    return sorted(best, key=best.__getitem__)
