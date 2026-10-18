"""What a study exports: TREC qrels, training pairs with hard negatives, and an image's consensus label."""

from collections import Counter

Pools = dict[str, list[str]]
"""Each query's pool as doc ids in rank order, keyed by query id."""

LabelsByQuery = dict[str, dict[str, str]]
"""One label per image (doc id) of each query, keyed by query id."""


def is_complete(pool: list[str], labels: dict[str, str]) -> bool:
    """Return whether every image of the pool has a label."""
    return all(doc_id in labels for doc_id in pool)


def qrels_lines(pools: Pools, labels_by_query: LabelsByQuery, grade_of: dict[str, int | None]) -> list[str]:
    """Return TREC qrels lines (`query 0 doc grade`) for the queries whose pool is fully labelled.

    Partly labelled queries are left out, so the qrels never treat an unjudged image as not relevant. Labels
    without a grade (Unsure) are left out too.

    Args:
        grade_of: Each label's grade; None for a label left out of the qrels.
    """
    lines = []
    for query_id, pool in pools.items():
        labels = labels_by_query.get(query_id, {})
        if not is_complete(pool, labels):
            continue
        for doc_id in pool:
            grade = grade_of[labels[doc_id]]
            if grade is not None:
                lines.append(f"{query_id} 0 {doc_id} {grade}")
    return lines


def training_pairs(
    pools: Pools, labels_by_query: LabelsByQuery, grade_of: dict[str, int | None]
) -> list[dict[str, str | list[str]]]:
    """Return, per query with both, its relevant images and its hard negatives, for training a retriever.

    Hard negatives are the images labelled grade 0, in pool order: the pool is in rank order, so the first
    ones are the look-alikes that fooled the retriever. Unjudged and ungraded images are neither.
    """
    pairs: list[dict[str, str | list[str]]] = []
    for query_id, pool in pools.items():
        labels = labels_by_query.get(query_id, {})
        grades = [grade_of[labels[doc_id]] if doc_id in labels else None for doc_id in pool]
        positives = [doc_id for doc_id, grade in zip(pool, grades, strict=True) if grade]
        hard_negatives = [doc_id for doc_id, grade in zip(pool, grades, strict=True) if grade == 0]
        if positives and hard_negatives:
            pairs.append({"query_id": query_id, "positives": positives, "hard_negatives": hard_negatives})
    return pairs


def consensus(labels_by_annotator: list[str], adjudicated: str | None) -> str | None:
    """Return an image's agreed label: the adjudicated one if there is one, else the majority label.

    Returns:
        The label, or None when there are no labels or the two most common are tied.
    """
    if adjudicated is not None:
        return adjudicated
    counts = Counter(labels_by_annotator).most_common(2)
    if not counts or (len(counts) == 2 and counts[0][1] == counts[1][1]):
        return None
    return counts[0][0]
