"""How each pilot annotator worked: speed, corrections, label rates and accuracy against the others."""

from collections import Counter
from dataclasses import dataclass
from statistics import median

from cara.core.agreement import ItemKey, LabelsByUser, pairwise_kappa
from cara.core.export import consensus

IDLE_SECONDS = 600
"""A longer gap between two actions is a break, not work."""

HUMAN_SECONDS = 0.5
"""A faster median per image means a script recorded the labels: no speed is measured then."""


@dataclass(frozen=True, slots=True)
class Action:
    """One logged action of an annotator.

    Attributes:
        time: Seconds since the epoch.
        label: The label given; None for an action that labels nothing (a split, review done).
        items: The images it applies to.
    """

    username: str
    time: float
    label: str | None
    items: tuple[ItemKey, ...]


@dataclass(frozen=True, slots=True)
class AnnotatorStats:
    """How one pilot annotator worked, for the Pilot results page and the simulator's annotator types.

    Shares and accuracies are None when there is nothing to divide by.

    Attributes:
        queries_judged: Queries in which this annotator labelled every image.
        images: Images they labelled.
        seconds_per_image: The median gap before an action that labels one image; None if they labelled none
            one by one, or if it is under `HUMAN_SECONDS` (a script, not a person).
        active_minutes: The gaps between their actions, up to `IDLE_SECONDS` each, summed.
        corrections: Labelling actions that changed a label they had given before.
        relevant_share: The share of their labels with a grade of 1 or more.
        unsure_share: The share of their labels without a grade.
        kappa: The mean of their Cohen's κ with each other annotator.
        acc_relevant: Of the images the others' majority (leave-one-out) labels relevant, the share this
            annotator labels relevant too; only images where both sides gave a graded label count.
        acc_nonrelevant: The same for the images the others label not relevant.
        compared: Images the accuracies are computed on.
    """

    username: str
    queries_judged: int
    images: int
    seconds_per_image: float | None
    active_minutes: float
    corrections: int
    relevant_share: float | None
    unsure_share: float | None
    kappa: float | None
    acc_relevant: float | None
    acc_nonrelevant: float | None
    compared: int


def _share(hits: int, total: int) -> float | None:
    return hits / total if total else None


def annotator_stats(
    actions: list[Action],
    labels: LabelsByUser,
    pool_sizes: dict[str, int],
    grade_of: dict[str, int | None],
) -> list[AnnotatorStats]:
    """Return each annotator's statistics, in username order.

    Args:
        actions: Every logged action of the annotators, in any order.
        labels: Each annotator's final labels.
        pool_sizes: Images per query, by query id.
        grade_of: Each label's grade; None for a label without one (Unsure).
    """
    kappas = pairwise_kappa(labels)
    found = []
    for name in sorted(labels):
        mine = labels[name]
        gaps: list[float] = []
        single: list[float] = []
        corrections = 0
        given: dict[ItemKey, str] = {}
        previous: float | None = None
        for action in sorted((a for a in actions if a.username == name), key=lambda a: a.time):
            gap = None if previous is None else action.time - previous
            previous = action.time
            if gap is not None and 0 < gap <= IDLE_SECONDS:
                gaps.append(gap)
                if action.label is not None and len(action.items) == 1:
                    single.append(gap)
            if action.label is None:
                continue
            corrections += any(given.get(item, action.label) != action.label for item in action.items)
            given.update(dict.fromkeys(action.items, action.label))

        per_query = Counter(query for query, _ in mine)
        grades = [grade_of[label] for label in mine.values()]
        hits = Counter[bool]()
        totals = Counter[bool]()
        for item, label in mine.items():
            others = [labels[other][item] for other in labels if other != name and item in labels[other]]
            truth = consensus(others, None)
            if truth is None or grade_of[truth] is None or grade_of[label] is None:
                continue
            relevant = (grade_of[truth] or 0) > 0
            totals[relevant] += 1
            hits[relevant] += ((grade_of[label] or 0) > 0) == relevant
        with_me = [k for pair, k in kappas.items() if name in pair and k is not None]
        found.append(
            AnnotatorStats(
                username=name,
                queries_judged=sum(per_query[q] == n for q, n in pool_sizes.items()),
                images=len(mine),
                seconds_per_image=median(single) if single and median(single) >= HUMAN_SECONDS else None,
                active_minutes=sum(gaps) / 60,
                corrections=corrections,
                relevant_share=_share(sum((g or 0) > 0 for g in grades), len(grades)),
                unsure_share=_share(sum(g is None for g in grades), len(grades)),
                kappa=sum(with_me) / len(with_me) if with_me else None,
                acc_relevant=_share(hits[True], totals[True]),
                acc_nonrelevant=_share(hits[False], totals[False]),
                compared=totals.total(),
            )
        )
    return found
