"""HDBSCAN: dense clusters only; the rest are judged one by one."""

from typing import Literal

import numpy as np
import numpy.typing as npt
from pydantic import Field
from sklearn.cluster import HDBSCAN as SklearnHDBSCAN

from cara.grouping.base import GroupingMethod, clusters, register


@register
class HDBSCAN(GroupingMethod):
    """HDBSCAN: dense clusters of at least `min_cluster_size` images; the outliers are judged one by one.

    Attributes:
        min_cluster_size: The smallest group HDBSCAN may form.
    """

    method: Literal["hdbscan"]
    min_cluster_size: int = Field(default=3, ge=2)

    def label(self) -> str:
        """Return the method with its smallest and largest group."""
        return f"HDBSCAN min. {self.min_cluster_size}, groups of up to {self.max_size}"

    def partition(self, emb_nd: npt.NDArray[np.float32]) -> list[list[int]]:
        """Return the dense clusters, and every outlier on its own.

        A pool with fewer images than `min_cluster_size` has no cluster: every image is judged alone.
        """
        if len(emb_nd) < self.min_cluster_size:
            return [[i] for i in range(len(emb_nd))]
        return clusters(SklearnHDBSCAN(min_cluster_size=self.min_cluster_size, copy=True).fit_predict(emb_nd))
