"""Suggest mode's rule on small hand-made cases."""

import numpy as np

from cara.core.suggest import merge_threshold, suggest


def unit(*rows: list[float]) -> np.ndarray:
    v = np.array(rows, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_near_identical_marks_with_one_label_become_one_starting_point() -> None:
    marked = unit([1, 0, 0], [0.99, 0.05, 0], [0, 1, 0])  # two near-identical Not Relevant, one more
    open_ = unit([0.95, 0.1, 0], [0.1, 0.95, 0])
    positive = np.array([False, False, False])
    found, rest = suggest(open_ @ marked.T, marked @ marked.T, positive, None, 0.05, threshold=0.9)
    assert sorted(len(s.seeds) for s in found) == [1, 2] and rest == []
    found, _ = suggest(open_ @ marked.T, marked @ marked.T, positive, None, 0.05, threshold=np.inf)
    assert all(len(s.seeds) == 1 for s in found)


def test_close_calls_and_query_like_images_get_no_suggestion() -> None:
    marked = unit([1, 0, 0], [0, 1, 0])  # Not Relevant, Relevant
    positive = np.array([False, True])
    open_ = unit(
        [1, 0.98, 0], [1, 0.05, 0.02], [0.9, 0.1, 0.4]
    )  # a toss-up; clearly Not Relevant; query-like
    query = unit([0.9, 0.1, 0.45])[0]
    found, rest = suggest(open_ @ marked.T, marked @ marked.T, positive, open_ @ query, 0.05, np.inf)
    assert [(s.relevant, s.members) for s in found] == [(False, [1])] and sorted(rest) == [0, 2]


def test_merge_threshold_is_a_percentile_of_nearest_neighbour_similarity() -> None:
    sim = np.array([[1, 0.9, 0.1], [0.9, 1, 0.2], [0.1, 0.2, 1]], dtype=np.float32)
    assert merge_threshold(sim, 50) == np.float32(0.9) and merge_threshold(sim, 100) == np.inf
