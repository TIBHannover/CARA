"""Grouping methods: every image placed once, the caps, the ordering, splits, small pools, the registry."""

import numpy as np
import pytest
from conftest import blobs
from sklearn.cluster import AgglomerativeClustering

from cara.grouping import GroupingMethod, GroupingSettings, find_solos, register
from cara.grouping.agglomerative import Agglomerative
from cara.grouping.hdbscan import HDBSCAN
from cara.grouping.kmeans import KMeans
from cara.grouping.none import NoGrouping

METHODS: list[GroupingSettings] = [
    Agglomerative(method="agglomerative"),
    KMeans(method="kmeans", n_groups=4),
    HDBSCAN(method="hdbscan"),
    NoGrouping(method="none"),
]


@pytest.mark.parametrize("grouping", METHODS, ids=lambda g: g.method)
def test_every_candidate_appears_once_and_groups_respect_the_cap(grouping: GroupingSettings) -> None:
    emb = blobs()
    pool = grouping.group(emb, emb @ emb[0], solo_percentile=10, top_k_individual=3)
    members = [c for group in pool.groups for c in group] + pool.individual
    assert sorted(members) == list(range(len(emb)))
    assert all(2 <= len(group) <= 16 for group in pool.groups)


def test_none_puts_everything_in_the_individual_bin() -> None:
    emb = blobs()
    pool = NoGrouping(method="none").group(emb, emb @ emb[0], 10, 0)
    assert pool.groups == [] and len(pool.individual) == len(emb)


def test_groups_and_members_are_ordered_by_score() -> None:
    emb = blobs()
    pool = Agglomerative(method="agglomerative", max_size=40).group(emb, emb @ emb[0], 0, 0)
    assert pool.groups[0][0] == 0


def test_top_k_goes_to_the_individual_bin() -> None:
    emb = blobs()
    score = emb @ emb[0]
    pool = Agglomerative(method="agglomerative").group(emb, score, 0, 5)
    assert set(np.argsort(-score)[:5].tolist()) <= set(pool.individual)


def test_split_of_a_capped_group_equals_its_children_in_the_full_tree() -> None:
    emb = blobs(n_blobs=2, per_blob=20)
    members = list(range(len(emb)))
    halves = Agglomerative(method="agglomerative").split(emb, emb @ emb[0], members)
    tree = AgglomerativeClustering(n_clusters=2, metric="cosine", linkage="average").fit(emb)
    children = {frozenset(np.flatnonzero(tree.labels_ == label).tolist()) for label in (0, 1)}
    assert {frozenset(half) for half in halves} == children


def test_tiny_pools() -> None:
    one = np.ones((1, 4), dtype=np.float32) / 2
    assert not find_solos(one, 50).any()
    pool = Agglomerative(method="agglomerative").group(one, np.ones(1, dtype=np.float32), 10, 0)
    assert pool.groups == [] and pool.individual == [0]


def test_scores_must_match_candidates() -> None:
    emb = blobs()
    with pytest.raises(ValueError, match="one score per candidate"):
        Agglomerative(method="agglomerative").group(emb, emb[0], 10, 0)


def test_hdbscan_with_fewer_images_than_its_smallest_cluster_judges_them_alone() -> None:
    emb_nd = blobs(0, n_blobs=3, per_blob=4)
    score_n = np.arange(12, 0, -1, dtype=np.float32)
    # Top 10 judged alone leaves 2 images for HDBSCAN, which needs at least 3 to form a cluster.
    pool = HDBSCAN(method="hdbscan", min_cluster_size=3).group(emb_nd, score_n, 0.0, 10)
    assert pool.groups == [] and sorted(pool.individual) == list(range(12))


def test_registering_needs_a_new_method_key() -> None:
    with pytest.raises(ValueError, match="'kmeans' is registered twice"):

        @register
        class OtherKMeans(KMeans):
            pass

    with pytest.raises(TypeError, match="needs a field `method"):

        @register
        class Keyless(GroupingMethod):
            pass
