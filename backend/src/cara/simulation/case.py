"""One query's pool as the simulation sees it, and the running tally of what an annotator did to it."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from cara.grouping import Linkage
from cara.simulation.outcome import PoolOutcome

WHERE_INDIVIDUAL, WHERE_MINORITY, WHERE_MAJORITY = 0, 1, 2
"""Where an image was judged: on its own, or in a group whose label it does or doesn't share."""


@dataclass(frozen=True, slots=True)
class PoolCase:
    """One pool as the simulation sees it.

    Attributes:
        emb_nd: The images' embeddings, unit length.
        truth_n: The ground truth: whether each image is relevant.
        score_n: Each image's score for the query; it orders the review and Suggest mode's one-by-one images.
        linkage: The linkage that splits a group in two (the grouping method's `split_linkage`).
        query_sim_n: Each image's similarity to the query image, which Suggest mode compares with; None
            without a query image (text queries).
    """

    emb_nd: npt.NDArray[np.float32]
    truth_n: npt.NDArray[np.bool_]
    score_n: npt.NDArray[np.float32]
    linkage: Linkage = "average"
    query_sim_n: npt.NDArray[np.float32] | None = None

    def __len__(self) -> int:
        """Return the number of images in the pool."""
        return len(self.truth_n)

    def majority(self, members: list[int]) -> bool:
        """Return the true majority label of these images: relevant only if more than half are relevant."""
        return bool(2 * self.truth_n[members].sum() > len(members))


@dataclass(slots=True)
class Tally:
    """The labels an annotator gives a pool, and the actions it took to give them.

    Attributes:
        final_n: The label each image ends up with (True: relevant).
        perceived_n: What the annotator sees in each image when it looks, drawn once per image.
        where_n: Where each image was judged, one of the `WHERE_*` values.
        n_groups: Groups handled (or suggestions taken, in Suggest mode).
        n_individual: Images judged one by one.
        group_clicks: Actions that label a whole group.
        override_clicks: Corrections of single images inside a group.
        individual_clicks: Actions that label one image on its own.
        split_clicks: Splits of a group in two.
    """

    final_n: npt.NDArray[np.bool_]
    perceived_n: npt.NDArray[np.bool_]
    where_n: npt.NDArray[np.int8]
    n_groups: int = 0
    n_individual: int = 0
    group_clicks: int = 0
    override_clicks: int = 0
    individual_clicks: int = 0
    split_clicks: int = 0

    @classmethod
    def start(cls, case: PoolCase, perceived_n: npt.NDArray[np.bool_]) -> "Tally":
        """Start a tally with no actions; every image counts as judged alone until a group claims it."""
        return cls(
            final_n=case.truth_n.copy(),
            perceived_n=perceived_n,
            where_n=np.full(len(case), WHERE_INDIVIDUAL, dtype=np.int8),
        )

    def judge_alone(self, images: list[int] | int) -> None:
        """Label images one by one: each gets what the annotator perceives, at one action each."""
        self.final_n[images] = self.perceived_n[images]
        count = len(images) if isinstance(images, list) else 1
        self.individual_clicks += count
        self.n_individual += count

    def mark_group(self, case: PoolCase, members: npt.NDArray[np.intp], label: bool) -> None:
        """Record which members truly have the label the group is handled as, for the error analysis."""
        self.where_n[members] = np.where(case.truth_n[members] == label, WHERE_MAJORITY, WHERE_MINORITY)

    def outcome(self, case: PoolCase, shown_n: npt.NDArray[np.bool_], flips: int) -> PoolOutcome:
        """Return the counts of the finished pool.

        Args:
            shown_n: The images the review round showed.
            flips: The labels the review round changed.
        """
        truth_n, final_n, where_n = case.truth_n, self.final_n, self.where_n
        grouped_n = where_n != WHERE_INDIVIDUAL
        missed_n = truth_n & ~final_n
        n_grouped = int(grouped_n.sum())
        return PoolOutcome(
            n=len(truth_n),
            n_relevant=int(truth_n.sum()),
            n_groups=self.n_groups,
            n_individual=self.n_individual,
            group_purity=float((where_n[grouped_n] == WHERE_MAJORITY).mean()) if n_grouped else 1.0,
            group_clicks=self.group_clicks,
            override_clicks=self.override_clicks,
            individual_clicks=self.individual_clicks,
            split_clicks=self.split_clicks,
            review_flips=flips,
            browsed_relevant=int((grouped_n & truth_n).sum()),
            browsed_nonrelevant=int((grouped_n & ~truth_n).sum()),
            review_shown_relevant=int((shown_n & truth_n).sum()),
            review_shown_nonrelevant=int((shown_n & ~truth_n).sum()),
            tp=int((truth_n & final_n).sum()),
            fp=int((~truth_n & final_n).sum()),
            fn=int(missed_n.sum()),
            tn=int((~truth_n & ~final_n).sum()),
            fn_group_minority=int((missed_n & (where_n == WHERE_MINORITY)).sum()),
            fn_group_majority=int((missed_n & (where_n == WHERE_MAJORITY)).sum()),
            fn_individual=int((missed_n & (where_n == WHERE_INDIVIDUAL)).sum()),
        )
