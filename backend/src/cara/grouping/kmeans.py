"""k-means: a fixed number of clusters per pool."""

from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import Field
from sklearn.cluster import KMeans as SklearnKMeans

from cara.grouping.base import GroupingMethod, clusters, register


@register
class KMeans(GroupingMethod):
    """k-means with `n_groups` clusters per pool; clusters larger than `max_size` are split further.

    Attributes:
        n_groups: Clusters per pool; fewer when the pool has fewer images.
        seed: The random seed, so the same pool always gets the same groups.
    """

    method: Literal["kmeans"]
    n_groups: int = Field(default=12, ge=2)
    seed: int = 0

    def label(self) -> str:
        """Return the method with its number of clusters and largest group."""
        return f"k-means k={self.n_groups}, groups of up to {self.max_size}"

    def partition(self, emb_nd: npt.NDArray[np.float32]) -> list[list[int]]:
        """Return the k-means clusters."""
        k = min(self.n_groups, len(emb_nd))
        return clusters(
            SklearnKMeans(n_clusters=k, random_state=self.seed, n_init="auto").fit_predict(emb_nd)
        )
