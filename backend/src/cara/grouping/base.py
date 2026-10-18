"""What every grouping method is and does: its settings, its partition of a pool, and the steps all share."""

from dataclasses import dataclass
from typing import ClassVar, Literal, get_args

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field
from sklearn.cluster import AgglomerativeClustering

Linkage = Literal["average", "complete", "single"]


@dataclass(frozen=True, slots=True)
class PoolGroups:
    """A pool's groups and its images judged alone, as row indices, most similar to the query first."""

    groups: list[list[int]]
    individual: list[int]


class GroupingMethod(BaseModel):
    """A grouping method: its settings as a study's YAML gives them, and how it groups a pool.

    Subclasses add their own settings, a `method` key, and `partition`; `group` does the rest: it sets aside
    the images judged alone, caps every group at `max_size` by splitting it, and orders groups by similarity
    to the query. Decorate a subclass with `register` so studies can use it.

    Attributes:
        method: The key a study's YAML names the method by; each subclass narrows it to its own `Literal`.
        max_size: The largest group; larger ones are split in two until they fit.
        groups: Whether the method makes groups at all (False for judging one image at a time).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: str
    max_size: int = Field(default=16, ge=2)
    groups: ClassVar[bool] = True

    @property
    def split_linkage(self) -> Linkage:
        """Return the linkage that splits a group in two, for capping and for annotators' splits."""
        return "average"

    def label(self) -> str:
        """Return a short, readable name, such as "k-means k=10, groups of up to 16"."""
        raise NotImplementedError

    def partition(self, emb_nd: npt.NDArray[np.float32]) -> list[list[int]]:
        """Partition the images (rows of `emb_nd`, unit length) into groups of row indices.

        Groups may be larger than `max_size`; a group of one is an image judged alone.
        """
        raise NotImplementedError

    def group(
        self,
        emb_nd: npt.NDArray[np.float32],
        score_n: npt.NDArray[np.float32],
        solo_percentile: float,
        top_k_individual: int,
    ) -> PoolGroups:
        """Group a pool: set aside images judged alone, partition the rest, cap the groups, order by score.

        Images judged alone are those without a close neighbour (`solo_percentile`), the `top_k_individual`
        most similar to the query, and groups of one. Groups and their members are ordered by score, highest
        first.

        Raises:
            ValueError: `score_n` doesn't have one score per image.
        """
        if score_n.shape != (len(emb_nd),):
            raise ValueError(f"need one score per candidate: {score_n.shape} vs {len(emb_nd)} candidates")
        is_individual_n = find_solos(emb_nd, solo_percentile)
        is_individual_n[np.argsort(-score_n, kind="stable")[:top_k_individual]] = True
        rest = np.flatnonzero(~is_individual_n)
        groups = [rest[group].tolist() for group in self.partition(emb_nd[rest])] if len(rest) else []
        groups = cap(emb_nd, groups, self.max_size, self.split_linkage)
        individual = np.flatnonzero(is_individual_n).tolist() + [g[0] for g in groups if len(g) == 1]
        ordered = _by_mean_score([_by_score(g, score_n) for g in groups if len(g) > 1], score_n)
        return PoolGroups(groups=ordered, individual=_by_score(individual, score_n))

    def split(
        self, emb_nd: npt.NDArray[np.float32], score_n: npt.NDArray[np.float32], members: list[int]
    ) -> list[list[int]]:
        """Split a group in two for an annotator, each half and the halves ordered by score, highest first."""
        halves = [_by_score(half, score_n) for half in bisect(emb_nd, members, self.split_linkage)]
        return _by_mean_score(halves, score_n)


METHODS: dict[str, type[GroupingMethod]] = {}
"""Every registered grouping method, by its `method` key."""


def register[G: GroupingMethod](cls: type[G]) -> type[G]:
    """Register a grouping method under its `method` key, so a study's grouping settings can name it.

    Raises:
        TypeError: The class has no `method: Literal["<key>"]` field.
        ValueError: Another class is registered under the same key.
    """
    field = cls.model_fields.get("method")
    keys = get_args(field.annotation) if field is not None else ()
    if len(keys) != 1 or not isinstance(keys[0], str):
        raise TypeError(f'{cls.__name__} needs a field `method: Literal["<key>"]` to be registered')
    if keys[0] in METHODS:
        raise ValueError(
            f"grouping method {keys[0]!r} is registered twice: {METHODS[keys[0]].__name__}, {cls.__name__}"
        )
    METHODS[keys[0]] = cls
    return cls


def scores(
    order: Literal["similarity", "pool_rank"],
    candidate_emb_nd: npt.NDArray[np.float32],
    query_emb_d: npt.NDArray[np.float32] | None,
) -> npt.NDArray[np.float32]:
    """Return each image's score for the query: its cosine similarity, or minus its rank in the pool.

    Raises:
        ValueError: `order` is `similarity` but the query has no embedding.
    """
    if order == "pool_rank":
        return -np.arange(len(candidate_emb_nd), dtype=np.float32)
    if query_emb_d is None:
        raise ValueError(
            "order 'similarity' needs a query embedding (cara encode); else use order 'pool_rank'"
        )
    score_n: npt.NDArray[np.float32] = candidate_emb_nd @ query_emb_d
    return score_n


def find_solos(emb_nd: npt.NDArray[np.float32], percentile: float) -> npt.NDArray[np.bool_]:
    """Mark the images without a close neighbour, to be judged alone.

    An image is marked when its nearest neighbour is less similar than this percentile of the pool's
    nearest-neighbour similarities; placed in a group, it would make the group mixed.
    """
    if len(emb_nd) < 2:
        return np.zeros(len(emb_nd), dtype=bool)
    sim_nn = emb_nd @ emb_nd.T
    np.fill_diagonal(sim_nn, -np.inf)
    nearest_n = sim_nn.max(axis=1)
    is_solo_n: npt.NDArray[np.bool_] = nearest_n < np.percentile(nearest_n, percentile)
    return is_solo_n


def clusters(labels_n: npt.NDArray[np.intp]) -> list[list[int]]:
    """Turn cluster labels into groups, one per label, and every noise point (label -1) on its own."""
    noise = [[i] for i in np.flatnonzero(labels_n == -1).tolist()]
    return [
        np.flatnonzero(labels_n == label).tolist() for label in np.unique(labels_n[labels_n >= 0])
    ] + noise


def bisect(
    emb_nd: npt.NDArray[np.float32], members: list[int], linkage: Linkage
) -> tuple[list[int], list[int]]:
    """Split a group in two by agglomerative clustering of its members.

    Raises:
        ValueError: The group has fewer than two members.
    """
    if len(members) < 2:
        raise ValueError("a group needs at least two members to be split")
    labels_n = AgglomerativeClustering(n_clusters=2, metric="cosine", linkage=linkage).fit_predict(
        emb_nd[members]
    )
    return (
        [m for m, label in zip(members, labels_n, strict=True) if label == 0],
        [m for m, label in zip(members, labels_n, strict=True) if label == 1],
    )


def cap(
    emb_nd: npt.NDArray[np.float32], groups: list[list[int]], max_size: int, linkage: Linkage
) -> list[list[int]]:
    """Split every group larger than `max_size` in two, again and again, until all fit."""
    stack, capped = list(groups), []
    while stack:
        group = stack.pop()
        if len(group) <= max_size:
            capped.append(group)
        else:
            stack.extend(bisect(emb_nd, group, linkage))
    return capped


def _by_score(members: list[int], score_n: npt.NDArray[np.float32]) -> list[int]:
    return sorted(members, key=lambda c: (-score_n[c], c))


def _by_mean_score(groups: list[list[int]], score_n: npt.NDArray[np.float32]) -> list[list[int]]:
    return sorted(groups, key=lambda g: (-float(score_n[g].mean()), g[0]))
