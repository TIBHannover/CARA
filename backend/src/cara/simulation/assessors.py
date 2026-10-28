"""Simulated annotators, called assessors.

Each model decides how it perceives images, which group members it looks at, which label it gives a group,
which members it corrects, and whether it corrects anything in a review; the workflows only ask (the Strategy
pattern). A new model is one subclass of `AssessorModel`, added to the `Assessor` union, so configs and the
API describe it as data.
"""

from typing import Annotated, Literal

import numpy as np
import numpy.typing as npt
from pydantic import Field

from cara.grouping import Linkage, bisect
from cara.settings import Frozen
from cara.simulation.case import PoolCase


class AssessorModel(Frozen):
    """What every simulated annotator answers, and all a workflow asks; each default is error-free."""

    def perceive(self, truth_n: npt.NDArray[np.bool_], rng: np.random.Generator) -> npt.NDArray[np.bool_]:
        """Return what the annotator would label each image if it looked at it.

        Drawn once per image, so a second look in the review gives the same verdict.
        """
        return truth_n

    def looks_at(
        self, case: PoolCase, members: npt.NDArray[np.intp], rng: np.random.Generator
    ) -> npt.NDArray[np.bool_]:
        """Return which members of a group the annotator looks at before labelling it: all of them."""
        return np.ones(len(members), dtype=bool)

    def group_label(
        self,
        case: PoolCase,
        members: npt.NDArray[np.intp],
        looked_n: npt.NDArray[np.bool_],
        perceived_n: npt.NDArray[np.bool_],
    ) -> bool:
        """Return the label the annotator gives the whole group: by default its true majority."""
        return case.majority(members.tolist())

    def corrections(
        self,
        case: PoolCase,
        members: npt.NDArray[np.intp],
        label: bool,
        looked_n: npt.NDArray[np.bool_],
        perceived_n: npt.NDArray[np.bool_],
    ) -> npt.NDArray[np.bool_]:
        """Return which members of a group labelled `label` the annotator relabels one by one."""
        raise NotImplementedError

    def split_cost(self, case: PoolCase, members: list[int]) -> tuple[int, int, int] | None:
        """Return (group actions, corrections, splits) if the annotator splits mixed groups, else None."""
        return None

    @property
    def corrects_in_review(self) -> bool:
        """Return whether the annotator changes labels in the review round."""
        return True

    @property
    def varies_with_review(self) -> bool:
        """Return False if the review can't change this annotator's result (experiments then run it once)."""
        return True

    def runs(self) -> int:
        """Return the repetitions needed: only an annotator that decides at random needs more than one."""
        return 1


class Perfect(AssessorModel):
    """Never errs: relabels exactly the minority of a group, or splits when that is cheaper.

    Attributes:
        split: Whether it splits mixed groups when that takes fewer actions than correcting them.
        max_split_depth: How many times in a row it may split.
    """

    kind: Literal["perfect"]
    split: bool = False
    max_split_depth: int = Field(default=3, ge=1)

    def corrections(
        self,
        case: PoolCase,
        members: npt.NDArray[np.intp],
        label: bool,
        looked_n: npt.NDArray[np.bool_],
        perceived_n: npt.NDArray[np.bool_],
    ) -> npt.NDArray[np.bool_]:
        """Return exactly the members whose true label differs from the group's."""
        corrected_n: npt.NDArray[np.bool_] = case.truth_n[members] != label
        return corrected_n

    def split_cost(self, case: PoolCase, members: list[int]) -> tuple[int, int, int] | None:
        """Return the cheapest way to handle the group, splitting where it helps; None if `split` is off."""
        return _cheapest(case, members, case.linkage, self.max_split_depth) if self.split else None

    @property
    def varies_with_review(self) -> bool:
        """Return False: its labels are already right, so the review changes nothing."""
        return False


class GroupOnly(AssessorModel):
    """Labels each group by one glance at one member and never corrects an image, in a group or in the review.

    The glance falls on the member most similar to the query, and its accuracy is that of a group decision.
    Images set aside from the groups get the same accuracy.

    Attributes:
        acc_relevant: The chance it sees a relevant image as relevant.
        acc_nonrelevant: The chance it sees a not relevant image as not relevant.
        repetitions: Runs per pool, averaged, since it decides at random.
    """

    kind: Literal["group_only"]
    acc_relevant: float = Field(default=0.68, ge=0.0, le=1.0)
    acc_nonrelevant: float = Field(default=0.82, ge=0.0, le=1.0)
    repetitions: int = Field(default=5, ge=1)

    def perceive(self, truth_n: npt.NDArray[np.bool_], rng: np.random.Generator) -> npt.NDArray[np.bool_]:
        """Return each image's truth, flipped with the chance of an error for its true label."""
        return _perceive(truth_n, self.acc_relevant, self.acc_nonrelevant, rng)

    def looks_at(
        self, case: PoolCase, members: npt.NDArray[np.intp], rng: np.random.Generator
    ) -> npt.NDArray[np.bool_]:
        """Return only the member most similar to the query."""
        return _most_similar(case, members)

    def group_label(
        self,
        case: PoolCase,
        members: npt.NDArray[np.intp],
        looked_n: npt.NDArray[np.bool_],
        perceived_n: npt.NDArray[np.bool_],
    ) -> bool:
        """Return what it perceives in the one member it looked at."""
        return bool(perceived_n[members[looked_n]][0])

    def corrections(
        self,
        case: PoolCase,
        members: npt.NDArray[np.intp],
        label: bool,
        looked_n: npt.NDArray[np.bool_],
        perceived_n: npt.NDArray[np.bool_],
    ) -> npt.NDArray[np.bool_]:
        """Return no corrections."""
        return np.zeros(len(members), dtype=bool)

    @property
    def corrects_in_review(self) -> bool:
        """Return False: it changes nothing in the review."""
        return False

    def runs(self) -> int:
        """Return `repetitions`."""
        return self.repetitions


class Realistic(AssessorModel):
    """Errs at a given rate per image, and doesn't look at every image of a large group.

    It looks at every member of a group up to `full_inspection_size`, at each member of a larger one with
    probability `inspect_prob_large` (grid viewing skips rows: Xie et al., WWW 2019), labels the group with
    the majority of what it perceives in the members it looked at, and corrects those it sees differently.
    The default accuracies are from a relevance study: 0.68 on relevant and 0.81–0.83 on not relevant items
    (Villa and Halvey, SIGIR 2013).

    Attributes:
        full_inspection_size: The largest group it looks at image by image.
        inspect_prob_large: The chance it looks at each image of a larger group.
        acc_relevant: The chance it sees a relevant image as relevant.
        acc_nonrelevant: The chance it sees a not relevant image as not relevant.
        repetitions: Runs per pool, averaged, since it decides at random.
    """

    kind: Literal["realistic"]
    full_inspection_size: int = Field(default=8, ge=1)
    inspect_prob_large: float = Field(default=0.7, ge=0.0, le=1.0)
    acc_relevant: float = Field(default=0.68, ge=0.0, le=1.0)
    acc_nonrelevant: float = Field(default=0.82, ge=0.0, le=1.0)
    repetitions: int = Field(default=5, ge=1)

    def perceive(self, truth_n: npt.NDArray[np.bool_], rng: np.random.Generator) -> npt.NDArray[np.bool_]:
        """Return each image's truth, flipped with the chance of an error for its true label."""
        return _perceive(truth_n, self.acc_relevant, self.acc_nonrelevant, rng)

    def looks_at(
        self, case: PoolCase, members: npt.NDArray[np.intp], rng: np.random.Generator
    ) -> npt.NDArray[np.bool_]:
        """Return all members of a small group, each member of a larger one with `inspect_prob_large`.

        It always looks at one member at least, the one most similar to the query, to have a label to give.
        """
        if len(members) <= self.full_inspection_size:
            return np.ones(len(members), dtype=bool)
        looked_n = rng.random(len(members)) < self.inspect_prob_large
        return looked_n if looked_n.any() else _most_similar(case, members)

    def group_label(
        self,
        case: PoolCase,
        members: npt.NDArray[np.intp],
        looked_n: npt.NDArray[np.bool_],
        perceived_n: npt.NDArray[np.bool_],
    ) -> bool:
        """Return the majority of what it perceives in the members it looked at (relevant: more than half)."""
        seen_n = perceived_n[members[looked_n]]
        return bool(2 * seen_n.sum() > len(seen_n))

    def corrections(
        self,
        case: PoolCase,
        members: npt.NDArray[np.intp],
        label: bool,
        looked_n: npt.NDArray[np.bool_],
        perceived_n: npt.NDArray[np.bool_],
    ) -> npt.NDArray[np.bool_]:
        """Return the members it looked at and perceives differently from the group's label."""
        corrected_n: npt.NDArray[np.bool_] = looked_n & (perceived_n[members] != label)
        return corrected_n

    def runs(self) -> int:
        """Return `repetitions`."""
        return self.repetitions


Assessor = Annotated[Perfect | GroupOnly | Realistic, Field(discriminator="kind")]
"""Every simulated annotator, told apart by its `kind` key."""


def _perceive(
    truth_n: npt.NDArray[np.bool_], acc_relevant: float, acc_nonrelevant: float, rng: np.random.Generator
) -> npt.NDArray[np.bool_]:
    """Return each image's truth, flipped with the chance of an error for its true label."""
    accuracy_n = np.where(truth_n, acc_relevant, acc_nonrelevant)
    correct_n = rng.random(len(truth_n)) < accuracy_n
    perceived_n: npt.NDArray[np.bool_] = np.where(correct_n, truth_n, ~truth_n)
    return perceived_n


def _most_similar(case: PoolCase, members: npt.NDArray[np.intp]) -> npt.NDArray[np.bool_]:
    """Return a mask with only the member most similar to the query."""
    looked_n = np.zeros(len(members), dtype=bool)
    looked_n[int(np.argmax(case.score_n[members]))] = True
    return looked_n


def _cheapest(case: PoolCase, members: list[int], linkage: Linkage, depth_left: int) -> tuple[int, int, int]:
    """Return (group actions, corrections, splits) for the cheaper of keeping the group or splitting it.

    Keeping costs one action and a correction per minority image; splitting handles each half the same way,
    down to `depth_left` splits.
    """
    n_relevant = int(case.truth_n[members].sum())
    minority = min(n_relevant, len(members) - n_relevant)
    keep = (1, minority, 0)
    if minority == 0 or depth_left == 0 or len(members) < 2:
        return keep
    halves = [
        _cheapest(case, half, linkage, depth_left - 1) for half in bisect(case.emb_nd, members, linkage)
    ]
    split = (halves[0][0] + halves[1][0], halves[0][1] + halves[1][1], 1 + halves[0][2] + halves[1][2])
    return split if sum(split) < sum(keep) else keep
