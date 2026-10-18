"""Agglomerative clustering: similar images merged into a tree, cut at the largest group size."""

from typing import Literal

import numpy as np
import numpy.typing as npt

from cara.grouping.base import GroupingMethod, Linkage, register


@register
class Agglomerative(GroupingMethod):
    """Agglomerative clustering, cut so that no group is larger than `max_size`.

    Attributes:
        linkage: How the distance between two groups is measured: `average` (balanced groups), `complete`
            (tight groups) or `single` (long chains). It also splits groups in two.
    """

    method: Literal["agglomerative"]
    linkage: Linkage = "average"

    @property
    def split_linkage(self) -> Linkage:
        """Return the method's own linkage."""
        return self.linkage

    def label(self) -> str:
        """Return the method with its linkage and largest group."""
        return f"agglomerative ({self.linkage}), groups of up to {self.max_size}"

    def partition(self, emb_nd: npt.NDArray[np.float32]) -> list[list[int]]:
        """Return the whole pool as one group: capping it at `max_size` builds the tree top down."""
        return [list(range(len(emb_nd)))]
