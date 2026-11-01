"""The paper's simulation table: CARA's default and its recommended setting against one image at a time.

    python experiments/paper_table.py <analysis artifacts dir> --out <dir>

Reads `summary.csv` (analyze_simulation.py) and writes `table.md` and `table.tex`, one row per query set. All
values are for the typical (realistic) profile with a review round. The recommended setting follows the app's
rule: the fastest setting whose recall stays within `RECALL_TOLERANCE` of judging one image at a time.
"""

import argparse
import logging
import re
from pathlib import Path

import pandas as pd

from cara.services.simulator.results import RECALL_TOLERANCE

logger = logging.getLogger(__name__)

QUERY_SETS = [  # (dataset, qrels, row label)
    ("met_test", "instance", "Image (instance)"),
    ("met_text_test", "category", "Text"),
    ("met_composed_test", "category", "Image + text"),
]
BASELINE = "one_at_a_time"
DEFAULT = "agglo-average-G16-solo10-top0"
PROFILE = {"assessor": "realistic", "review": "review"}
BOUND = {"assessor": "group_only", "review": "review"}


def code(strategy: str) -> str:
    """Return a setting's short name: A16·10% (agglomerative, at most 16, 10% alone), K10, H5, single."""
    if strategy == BASELINE:
        return "single"
    if m := re.fullmatch(r"agglo-(\w+)-G(\d+)-solo(\d+)-top(\d+)", strategy):
        linkage, size, solo, top = m.groups()
        name = f"A{size}" if linkage == "average" else f"A{size}{linkage[0]}"
        return f"{name}·{solo}%" + (f"·top{top}" if top != "0" else "")
    if m := re.fullmatch(r"kmeans-k(\d+)(?:-G(\d+))?", strategy):
        return f"K{m[1]}" + (f"≤{m[2]}" if m[2] else "")
    if m := re.fullmatch(r"hdbscan-m(\d+)(?:-G(\d+))?", strategy):
        return f"H{m[1]}" + (f"≤{m[2]}" if m[2] else "")
    raise ValueError(f"no short name for setting {strategy!r}")


def row(cells: pd.DataFrame, bound: pd.DataFrame, label: str) -> dict[str, object]:
    """Return one query set's row from its summary cells for the profile, one per setting."""
    by_strategy = cells.set_index("strategy")
    single = by_strategy.loc[BASELINE]
    default = by_strategy.loc[DEFAULT]
    keeps = by_strategy[by_strategy.recall >= single.recall - RECALL_TOLERANCE - 1e-9]
    recommended = keeps.seconds_pc.idxmin()
    best = by_strategy.loc[recommended]
    return {
        "Query set": label,
        "Queries": int(single.queries),
        "Relevant per pool": single.relevant_share,
        "Recall, single": single.recall,
        "Default: saved": 1 - default.seconds_pc / single.seconds_pc,
        "Default: Δ recall": 100 * (default.recall - single.recall),
        "Recommended": code(str(recommended)),
        "Recommended: saved": 1 - best.seconds_pc / single.seconds_pc,
        "Recommended: Δ recall": 100 * (best.recall - single.recall),
        "Group-only recall": float(bound.set_index("strategy").loc[DEFAULT].recall),
    }


def table(summary: pd.DataFrame, depth: int) -> pd.DataFrame:
    """Return the table: one row per query set."""
    rows = []
    for dataset, qrels, label in QUERY_SETS:
        cell = summary[(summary.dataset == dataset) & (summary.qrels == qrels) & (summary.depth == depth)]
        profile = cell[(cell.assessor == PROFILE["assessor"]) & (cell.review == PROFILE["review"])]
        bound = cell[(cell.assessor == BOUND["assessor"]) & (cell.review == BOUND["review"])]
        rows.append(row(profile, bound, label))
    return pd.DataFrame(rows)


def formatted(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the table as the paper shows it: shares in percent, recall changes in points."""
    shown = frame.copy()
    for column in ["Relevant per pool", "Default: saved", "Recommended: saved"]:
        shown[column] = shown[column].map("{:.0%}".format)
    for column in ["Recall, single", "Group-only recall"]:
        shown[column] = shown[column].map("{:.2f}".format)
    for column in ["Default: Δ recall", "Recommended: Δ recall"]:
        shown[column] = shown[column].map("{:+.1f}".format)
    shown["Queries"] = shown["Queries"].map("{:,}".format)
    return shown


def markdown(frame: pd.DataFrame) -> str:
    lines = [list(frame.columns), ["---"] * len(frame.columns), *frame.astype(str).values.tolist()]
    return "".join("| " + " | ".join(line) + " |\n" for line in lines)


def latex_rows(frame: pd.DataFrame) -> str:
    """Return the table body for the paper; the group-only recall goes into the text, not the table."""
    body = frame.drop(columns=["Group-only recall"]).astype(str)
    body = body.replace({"%": r"\\%", "≤": r"$\\le$", "·": r"$\\cdot$", r"^-": r"$-$"}, regex=True)
    body["Queries"] = body["Queries"].str.replace(",", "{,}")
    return "".join(" & ".join(line) + r" \\" + "\n" for line in body.values.tolist())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("artifacts", type=Path, help="analysis artifacts dir holding summary.csv")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=100)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    shown = formatted(table(pd.read_csv(args.artifacts / "summary.csv"), args.depth))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "table.md").write_text(markdown(shown))
    (args.out / "table.tex").write_text(latex_rows(shown))
    logger.info("%s", markdown(shown))


if __name__ == "__main__":
    main()
