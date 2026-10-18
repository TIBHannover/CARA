"""Suggest mode's rule, shared by the app (`services/similarity.py`) and the simulator (`simulation/`).

Images the annotator marked one by one are the starting points. Marked images with the same label that are
about as similar as typical nearest neighbours in the pool are merged into one starting point, so two
near-identical marks do not split one group of suggestions in two.

For each unjudged image:
- R = its highest similarity to an image marked Relevant, or to the query image;
- N = its highest similarity to an image marked Not Relevant;
- it follows its most similar starting point and gets that point's label only if it is at least `min_margin`
  more similar to that side (R - N or N - R), and the query is not more similar to it than that point.
Everything else gets no suggestion.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True, slots=True)
class Suggestion:
    """The unjudged images that follow one starting point, with its label suggested.

    Attributes:
        seeds: The starting point, as indices into the marked images: one image or several merged ones.
        relevant: Whether the suggested label is relevant (else not relevant).
        members: Indices into the unjudged images, most similar to the starting point first.
    """

    seeds: list[int]
    relevant: bool
    members: list[int]


def merge_threshold(sim_nn: npt.NDArray[np.float32], percentile: float) -> float:
    """Return the similarity above which marked images with the same label are merged into one starting point.

    It is the `percentile` of the pool's nearest-neighbour similarities (50: a typical nearest-neighbour
    pair); 100, or a pool of one image, merges nothing.
    """
    if percentile >= 100:
        return np.inf
    off = sim_nn.copy()
    np.fill_diagonal(off, -np.inf)
    return float(np.percentile(off.max(axis=1), percentile)) if len(off) > 1 else np.inf


def _merge(
    sim_ss: npt.NDArray[np.float32], positive_s: npt.NDArray[np.bool_], threshold: float
) -> list[list[int]]:
    parent = list(range(len(positive_s)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(*np.nonzero(np.triu(sim_ss >= threshold, k=1)), strict=True):
        if positive_s[i] == positive_s[j]:
            parent[root(int(i))] = root(int(j))
    groups: dict[int, list[int]] = {}
    for i in range(len(positive_s)):
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def suggest(
    sim_os: npt.NDArray[np.float32],
    sim_ss: npt.NDArray[np.float32],
    positive_s: npt.NDArray[np.bool_],
    query_o: npt.NDArray[np.float32] | None,
    min_margin: float,
    threshold: float,
) -> tuple[list[Suggestion], list[int]]:
    """Apply the rule in this module's docstring to the unjudged images.

    Args:
        sim_os: Similarities, unjudged images by marked images.
        sim_ss: Similarities among the marked images.
        positive_s: Whether each marked image is marked relevant.
        query_o: Each unjudged image's similarity to the query image; None without one.
        min_margin: How much more similar an image must be to its side than to the other.
        threshold: The merge similarity, from `merge_threshold`.

    Returns:
        The suggestions, relevant ones first, then the largest; and the unjudged images that get none, most
        similar to the relevant side first.
    """
    n_open = sim_os.shape[0]
    query = query_o if query_o is not None else np.full(n_open, -np.inf)
    relevant_o = np.maximum(sim_os[:, positive_s].max(axis=1, initial=-np.inf), query)
    nonrelevant_o = sim_os[:, ~positive_s].max(axis=1, initial=-np.inf)
    anchors = _merge(sim_ss, positive_s, threshold)
    sim_oa = np.stack([sim_os[:, seeds].max(axis=1) for seeds in anchors], axis=1)
    nearest_o = sim_oa.argmax(axis=1)
    positive_a = np.array([bool(positive_s[seeds[0]]) for seeds in anchors])
    margin_o = np.where(positive_a[nearest_o], relevant_o - nonrelevant_o, nonrelevant_o - relevant_o)
    suggested_o = (margin_o >= min_margin) & (sim_oa.max(axis=1) >= relevant_o)
    suggestions = []
    for a, seeds in enumerate(anchors):
        rows = np.flatnonzero(suggested_o & (nearest_o == a))
        if len(rows):
            rows = rows[np.argsort(-sim_oa[rows, a], kind="stable")]
            suggestions.append(Suggestion(seeds, bool(positive_a[a]), [int(o) for o in rows]))
    suggestions.sort(key=lambda s: (not s.relevant, -len(s.members)))
    rest = np.flatnonzero(~suggested_o)
    rest = rest[np.argsort(-relevant_o[rest], kind="stable")]
    return suggestions, [int(o) for o in rest]
