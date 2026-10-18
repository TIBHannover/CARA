"""What judging one pool cost and how well it went, and the time each kind of action takes."""

from dataclasses import asdict, dataclass

from cara.grouping import PoolGroups
from cara.settings import Frozen


@dataclass(frozen=True, slots=True)
class PoolOutcome:
    """What judging one pool cost and how well it went; one row of the simulation's results.

    Attributes:
        n: Images in the pool.
        n_relevant: Of them, truly relevant.
        n_groups: Groups handled (or suggestions taken).
        n_individual: Images judged one by one.
        group_purity: The share of grouped images that truly have their group's label; 1 without groups.
        group_clicks: Actions that label a whole group.
        override_clicks: Corrections of single images inside a group.
        individual_clicks: Actions that label one image on its own.
        split_clicks: Splits of a group in two.
        review_flips: Labels the review round changed.
        browsed_relevant: Truly relevant images seen inside a group.
        browsed_nonrelevant: Truly not relevant images seen inside a group.
        review_shown_relevant: Truly relevant images the review showed.
        review_shown_nonrelevant: Truly not relevant images the review showed.
        tp: Relevant images labelled relevant.
        fp: Not relevant images labelled relevant.
        fn: Relevant images labelled not relevant (missed).
        tn: Not relevant images labelled not relevant.
        fn_group_minority: Missed images that were in a group handled as not relevant.
        fn_group_majority: Missed images that were in a group handled as relevant (and then wrongly
            corrected).
        fn_individual: Missed images that were judged one by one.
    """

    n: int
    n_relevant: int
    n_groups: int
    n_individual: int
    group_purity: float
    group_clicks: int
    override_clicks: int
    individual_clicks: int
    split_clicks: int
    review_flips: int
    browsed_relevant: int
    browsed_nonrelevant: int
    review_shown_relevant: int
    review_shown_nonrelevant: int
    tp: int
    fp: int
    fn: int
    tn: int
    fn_group_minority: int
    fn_group_majority: int
    fn_individual: int

    @property
    def actions(self) -> int:
        """Return every action the annotator took: group labels, corrections, single labels, splits, flips."""
        return (
            self.group_clicks
            + self.override_clicks
            + self.individual_clicks
            + self.split_clicks
            + self.review_flips
        )

    def as_row(self) -> dict[str, float | int]:
        """Return the counts as a results row, by field name."""
        return asdict(self)


class TimeModel(Frozen):
    """The seconds each kind of action takes, to turn counts into time.

    The defaults come from user studies: 5 s to judge one image on its own (4.97 s in Halvey and Villa's
    image study, 2014); 1.4 s per relevant and 0.2 s per not relevant image glanced at while browsing a set
    (Yan et al., CVPR 2008). The 3 s per group action is assumed; the simulation study varies the browsing
    times from 1× to 3×.

    Attributes:
        single_s: Judging one image on its own.
        group_action_s: Labelling a whole group.
        override_s: Correcting one image in a group, or flipping one in the review.
        split_s: Splitting a group in two.
        browse_relevant_s: Looking at a relevant image in a group or in the review.
        browse_nonrelevant_s: Looking at a not relevant image in a group or in the review.
    """

    single_s: float = 5.0
    group_action_s: float = 3.0
    override_s: float = 1.0
    split_s: float = 1.0
    browse_relevant_s: float = 1.4
    browse_nonrelevant_s: float = 0.2

    def seconds(self, outcome: PoolOutcome) -> float:
        """Return the seconds judging a pool took; works on a data frame of outcomes too, column by column."""
        return (
            self.single_s * outcome.individual_clicks
            + self.group_action_s * outcome.group_clicks
            + self.override_s * (outcome.override_clicks + outcome.review_flips)
            + self.split_s * outcome.split_clicks
            + self.browse_relevant_s * (outcome.browsed_relevant + outcome.review_shown_relevant)
            + self.browse_nonrelevant_s * (outcome.browsed_nonrelevant + outcome.review_shown_nonrelevant)
        )

    def lower_bound(self, grouped: PoolGroups, n: int) -> float:
        """Return the seconds a pool would take if every group were pure.

        One action per group and a glance at each grouped image, a full look at each image judged on its own;
        no corrections, no review.

        Args:
            n: Images in the pool.
        """
        individual = len(grouped.individual)
        return (
            len(grouped.groups) * self.group_action_s
            + (n - individual) * self.browse_nonrelevant_s
            + individual * self.single_s
        )
