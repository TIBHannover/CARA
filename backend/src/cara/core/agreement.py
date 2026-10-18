"""Agreement between annotators: Cohen's κ for each pair, Krippendorff's α overall, and the disagreements."""

from itertools import combinations

import krippendorff
import numpy as np
from sklearn.metrics import cohen_kappa_score

ItemKey = tuple[str, str]
"""An image within a query: (query id, doc id), both as in the dataset's files."""

LabelsByUser = dict[str, dict[ItemKey, str]]
"""Each annotator's labels by image, keyed by username."""


def pairwise_kappa(labels_by_user: LabelsByUser) -> dict[tuple[str, str], float | None]:
    """Return Cohen's κ for every pair of annotators, on the images both labelled.

    Returns:
        κ by pair of usernames, in alphabetical order; None for a pair whose shared labels hold fewer than two
        distinct labels, where κ is undefined.
    """
    kappas: dict[tuple[str, str], float | None] = {}
    for a, b in combinations(sorted(labels_by_user), 2):
        shared = sorted(labels_by_user[a].keys() & labels_by_user[b].keys())
        labels_a = [labels_by_user[a][item] for item in shared]
        labels_b = [labels_by_user[b][item] for item in shared]
        if len(set(labels_a) | set(labels_b)) < 2:
            kappas[a, b] = None
        else:
            kappas[a, b] = float(cohen_kappa_score(labels_a, labels_b))
    return kappas


def alpha(labels_by_user: LabelsByUser, label_names: list[str]) -> float | None:
    """Return Krippendorff's α (nominal) over all annotators, missing labels allowed.

    Args:
        label_names: Every label a judgment can have; each one in `labels_by_user` must be here.

    Returns:
        α, or None with fewer than two annotators or fewer than two distinct labels on images labelled
        at least twice, where α is undefined.
    """
    items = sorted({item for labels in labels_by_user.values() for item in labels})
    code = {name: float(i) for i, name in enumerate(label_names)}
    data_ui = np.array(
        [
            [code[labels[item]] if item in labels else np.nan for item in items]
            for labels in labels_by_user.values()
        ]
    )
    pairable = (~np.isnan(data_ui)).sum(axis=0) >= 2
    if len(labels_by_user) < 2 or len(np.unique(data_ui[:, pairable][~np.isnan(data_ui[:, pairable])])) < 2:
        return None
    return float(krippendorff.alpha(reliability_data=data_ui, level_of_measurement="nominal"))


def disagreements(labels_by_user: LabelsByUser) -> dict[ItemKey, dict[str, str]]:
    """Return the images annotators labelled differently, each with every annotator's label, by image."""
    by_item: dict[ItemKey, dict[str, str]] = {}
    for user, labels in labels_by_user.items():
        for item, label in labels.items():
            by_item.setdefault(item, {})[user] = label
    return {item: users for item, users in sorted(by_item.items()) if len(set(users.values())) > 1}
