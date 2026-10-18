"""No grouping: every image judged on its own, the reference the others are compared with."""

from typing import ClassVar, Literal

import numpy as np
import numpy.typing as npt

from cara.grouping.base import GroupingMethod, register


@register
class NoGrouping(GroupingMethod):
    """No groups: every image is judged on its own."""

    method: Literal["none"]
    groups: ClassVar[bool] = False

    def label(self) -> str:
        """Return "one at a time"."""
        return "one at a time"

    def partition(self, emb_nd: npt.NDArray[np.float32]) -> list[list[int]]:
        """Return every image on its own."""
        return [[i] for i in range(len(emb_nd))]
