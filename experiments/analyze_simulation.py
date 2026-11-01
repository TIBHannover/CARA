import argparse
import json
import logging
from itertools import product
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import bootstrap, kendalltau, wilcoxon
from statsmodels.stats.multitest import multipletests
from tracking import log_run

from cara.simulation import TimeModel

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

SETTING = ["dataset", "qrels", "depth", "assessor", "review"]
CELL = [*SETTING, "strategy"]
METRICS = ["actions_pc", "seconds_pc", "recall", "precision", "accuracy", "group_purity", "relevant_share"]
TESTED = ["actions_pc", "seconds_pc", "recall"]


def load(run_dirs: list[Path]) -> pd.DataFrame:
    frames = [pd.read_parquet(run_dir / "outcomes.parquet") for run_dir in run_dirs]
    outcomes = pd.concat(frames, ignore_index=True)
    outcomes["actions_pc"] = outcomes.actions / outcomes.n
    outcomes["seconds_pc"] = TimeModel().seconds(outcomes) / outcomes.n  # type: ignore[arg-type]
    has_relevant = outcomes.n_relevant > 0
    outcomes["recall"] = (outcomes.tp / (outcomes.tp + outcomes.fn)).where(has_relevant)
    outcomes["precision"] = (outcomes.tp / (outcomes.tp + outcomes.fp)).where(outcomes.tp + outcomes.fp > 0)
    outcomes["accuracy"] = (outcomes.tp + outcomes.tn) / outcomes.n
    outcomes["relevant_share"] = outcomes.n_relevant / outcomes.n
    return outcomes


def mean_ci(values: pd.Series) -> tuple[float, float, float]:
    sample = values.dropna().to_numpy()
    if len(sample) < 2 or np.ptp(sample) == 0:
        mean = float(sample.mean()) if len(sample) else float("nan")
        return mean, mean, mean
    result = bootstrap((sample,), np.mean, n_resamples=2000, method="percentile", random_state=0)
    return float(sample.mean()), float(result.confidence_interval.low), float(result.confidence_interval.high)


def summarise(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, cell in outcomes.groupby(CELL, sort=False):
        row = dict(zip(CELL, keys, strict=True)) | {"queries": cell.query_id.nunique()}
        for metric in METRICS:
            row[metric], row[f"{metric}_lo"], row[f"{metric}_hi"] = mean_ci(cell[metric])
        rows.append(row)
    return pd.DataFrame(rows)


def paired_test(diff: np.ndarray) -> float:
    diff = diff[~np.isnan(diff)]
    if len(diff) < 2 or not np.any(diff):
        return 1.0
    return float(wilcoxon(diff).pvalue)


def against_baseline(outcomes: pd.DataFrame, baseline: str) -> pd.DataFrame:
    rows = []
    for keys, setting in outcomes.groupby(SETTING, sort=False):
        wide = setting.pivot_table(index="query_id", columns="strategy", values=TESTED)
        for metric, strategy in product(TESTED, setting.strategy.unique()):
            if strategy == baseline:
                continue
            diff = (wide[metric][strategy] - wide[metric][baseline]).to_numpy()
            mean, low, high = mean_ci(pd.Series(diff))
            rows.append(
                dict(zip(SETTING, keys, strict=True))
                | {"strategy": strategy, "metric": metric, "mean_diff": mean, "diff_lo": low, "diff_hi": high}
                | {"queries": int((~np.isnan(diff)).sum()), "p": paired_test(diff)}
            )
    tests = pd.DataFrame(rows)
    tests["p_holm"] = tests.groupby([*SETTING, "metric"]).p.transform(
        lambda p: multipletests(p, method="holm")[1]
    )
    tests["significant"] = tests.p_holm < 0.05
    return tests


def saving_by_relevance(outcomes: pd.DataFrame, strategy: str, baseline: str) -> pd.DataFrame:
    keys = ["dataset", "depth", "assessor", "review", "query_id", "qrels"]
    actions = outcomes[outcomes.strategy.isin([strategy, baseline])].pivot_table(
        index=keys, columns="strategy", values="actions_pc"
    )
    saving = (1 - actions[strategy] / actions[baseline]).unstack("qrels").dropna()
    rows = []
    for setting, frame in saving.groupby(level=["dataset", "depth", "assessor", "review"]):
        diff = (frame["category"] - frame["instance"]).to_numpy()
        rows.append(
            dict(zip(["dataset", "depth", "assessor", "review"], setting, strict=True))
            | {"saving_instance": frame["instance"].mean(), "saving_category": frame["category"].mean()}
            | {"queries": len(frame), "p": paired_test(diff)}
        )
    return pd.DataFrame(rows)


def review_effect(outcomes: pd.DataFrame, base: str, other: str) -> pd.DataFrame:
    """Paired by query: recall and time of review variant `other` against `base` (e.g. none vs a review)."""
    keys = [*CELL, "query_id"]
    wide = outcomes[outcomes.review.isin([base, other])].pivot_table(
        index=[k for k in keys if k != "review"], columns="review", values=["recall", "seconds_pc"]
    )
    rows = []
    for setting, frame in wide.groupby(level=[k for k in CELL if k != "review"]):
        recall_diff = (frame["recall"][other] - frame["recall"][base]).to_numpy()
        rows.append(
            dict(zip([k for k in CELL if k != "review"], setting, strict=True))
            | {"base": base, "other": other}
            | {
                "recall_base": frame["recall"][base].mean(),
                "recall_other": frame["recall"][other].mean(),
                "extra_seconds_pc": (frame["seconds_pc"][other] - frame["seconds_pc"][base]).mean(),
                "p": paired_test(recall_diff),
            }
        )
    return pd.DataFrame(rows)


def system_rankings(outcomes: pd.DataFrame) -> pd.DataFrame:
    columns = [c.removeprefix("ap_true.") for c in outcomes.columns if c.startswith("ap_true.")]
    rows = []
    for keys, cell in outcomes.groupby(CELL, sort=False):
        systems = sorted(s for s in columns if cell[f"ap_true.{s}"].notna().all())
        if len(systems) < 3:
            continue
        true_map = np.array([cell[f"ap_true.{s}"].mean() for s in systems])
        sim_map = np.array([cell[f"ap_sim.{s}"].mean() for s in systems])
        rows.append(
            dict(zip(CELL, keys, strict=True))
            | {"systems": len(systems), "kendall_tau": float(kendalltau(true_map, sim_map).statistic)}
            | {"max_abs_delta_map": float(np.abs(sim_map - true_map).max())}
            | {f"map_true.{s}": t for s, t in zip(systems, true_map, strict=True)}
            | {f"map_sim.{s}": m for s, m in zip(systems, sim_map, strict=True)}
        )
    return pd.DataFrame(rows)


def time_sensitivity(outcomes: pd.DataFrame, strategies: list[str], baseline: str) -> pd.DataFrame:
    perfect = outcomes[(outcomes.assessor == "perfect") & outcomes.strategy.isin([*strategies, baseline])]
    rows = []
    for single, group_action, browse in product([3.0, 5.0, 8.0], [1.0, 3.0, 5.0], [1.0, 2.0, 3.0]):
        time = TimeModel(
            single_s=single,
            group_action_s=group_action,
            browse_relevant_s=1.4 * browse,
            browse_nonrelevant_s=0.2 * browse,
        )
        spc = perfect.assign(spc=time.seconds(perfect) / perfect.n)  # type: ignore[arg-type]
        means = spc.groupby(["dataset", "qrels", "depth", "strategy"]).spc.mean().unstack("strategy")
        for strategy in strategies:
            for index, ratio in (means[strategy] / means[baseline]).items():
                rows.append(
                    dict(zip(["dataset", "qrels", "depth"], index, strict=True))
                    | {"strategy": strategy, "single_s": single, "group_action_s": group_action}
                    | {"browse_multiplier": browse, "time_ratio": ratio}
                )
    return pd.DataFrame(rows)


def save_figure(fig: plt.Figure, stem: Path) -> None:
    fig.savefig(stem.with_suffix(".pdf"))
    fig.savefig(stem.with_suffix(".png"), dpi=150)


def curves(summary: pd.DataFrame, strategy: str, depth: int) -> list[tuple[str, int, float]]:
    by_size = summary[
        summary.strategy.str.match(r"agglo-average-G\d+-solo10-top0$")
        & (summary.depth == depth)
        & (summary.review == "none")
    ]
    by_depth = summary[summary.strategy == strategy]
    return [
        (
            f"effort_vs_group_size/{r.dataset}/{r.qrels}/{r.assessor}",
            int(r.strategy.split("-G")[1].split("-")[0]),
            r.actions_pc,
        )
        for r in by_size.itertuples()
    ] + [
        (
            f"{metric}_vs_depth/{r.dataset}/{r.qrels}/{r.assessor}/{r.review}",
            int(r.depth),
            float(getattr(r, metric)),
        )
        for r in by_depth.itertuples()
        for metric in ("actions_pc", "recall")
        if not np.isnan(getattr(r, metric))
    ]


def plot_effort_vs_group_size(summary: pd.DataFrame, depth: int, out: Path) -> None:
    agglo = summary[
        summary.strategy.str.match(r"agglo-average-G\d+-solo10-top0$")
        & (summary.depth == depth)
        & (summary.review == "none")
        & summary.assessor.isin(["perfect", "realistic"])
    ].copy()
    agglo["max_size"] = agglo.strategy.str.extract(r"G(\d+)").astype(int)
    fig, ax = plt.subplots(figsize=(4.5, 3))
    for (dataset, qrels, assessor), frame in agglo.groupby(["dataset", "qrels", "assessor"]):
        frame = frame.sort_values("max_size")
        ax.errorbar(
            frame.max_size,
            frame.actions_pc,
            yerr=[frame.actions_pc - frame.actions_pc_lo, frame.actions_pc_hi - frame.actions_pc],
            marker="o",
            capsize=2,
            label=f"{dataset} {qrels} {assessor}",
        )
    ax.axhline(1.0, color="grey", linestyle="--", linewidth=1, label="one at a time")
    ax.set(xlabel="largest group size G", ylabel="actions per candidate", ylim=(0, 1.05))
    ax.legend(fontsize=6)
    fig.tight_layout()
    save_figure(fig, out / f"effort_vs_group_size_d{depth}")
    plt.close(fig)


def plot_effort_recall(summary: pd.DataFrame, depth: int, out: Path) -> None:
    cells = summary[(summary.depth == depth) & summary.assessor.isin(["group_only", "realistic"])]
    for (dataset, qrels), frame in cells.groupby(["dataset", "qrels"]):
        fig, ax = plt.subplots(figsize=(4.5, 3))
        for (assessor, review), part in frame.groupby(["assessor", "review"]):
            ax.scatter(part.seconds_pc, part.recall, s=10, label=f"{assessor}, {review}")
        ax.set(xlabel="estimated seconds per candidate", ylabel="recall of relevant images", ylim=(0, 1.02))
        ax.legend(fontsize=6)
        fig.tight_layout()
        save_figure(fig, out / f"effort_recall_{dataset}_{qrels}_d{depth}")
        plt.close(fig)


def plot_false_negative_sources(outcomes: pd.DataFrame, strategy: str, depth: int, out: Path) -> None:
    sources = ["fn_group_minority", "fn_group_majority", "fn_individual"]
    cells = outcomes[(outcomes.strategy == strategy) & (outcomes.depth == depth)]
    totals = cells.groupby(["dataset", "qrels", "assessor", "review"])[[*sources, "n_relevant"]].sum()
    shares = totals[sources].div(totals.n_relevant, axis=0)
    ax = shares.plot.barh(stacked=True, figsize=(5, 0.25 * len(shares) + 1))
    ax.set(xlabel="missed relevant images / all relevant images", ylabel="")
    ax.figure.tight_layout()
    save_figure(ax.figure, out / f"false_negative_sources_d{depth}")
    plt.close(ax.figure)


def headlines(summary: pd.DataFrame, strategy: str, depth: int) -> dict[str, float]:
    cells = summary[(summary.strategy == strategy) & (summary.depth == depth)]
    return {
        f"{row.dataset}/{row.qrels}/{row.assessor}/{row.review}/{metric}": float(getattr(row, metric))
        for row in cells.itertuples()
        for metric in ("actions_pc", "seconds_pc", "recall")
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tables, significance tests and figures for simulation runs."
    )
    parser.add_argument("runs", type=Path, nargs="+", help="run directories holding outcomes.parquet")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", default="one_at_a_time")
    parser.add_argument("--default-strategy", default="agglo-average-G16-solo10-top0")
    parser.add_argument("--depth", type=int, default=100, help="depth used in figures and headlines")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)

    outcomes = load(args.runs)
    depth = args.depth if args.depth in set(outcomes.depth) else int(outcomes.depth.max())
    summary = summarise(outcomes)
    summary.to_csv(args.out / "summary.csv", index=False)
    against_baseline(outcomes, args.baseline).to_csv(args.out / "tests_vs_baseline.csv", index=False)
    if {"instance", "category"} <= set(outcomes.qrels):
        saving_by_relevance(outcomes, args.default_strategy, args.baseline).to_csv(
            args.out / "tests_category_vs_instance.csv", index=False
        )
    reviews = [r for r in sorted(set(outcomes.review)) if r != "none"]
    pd.concat([review_effect(outcomes, "none", r) for r in reviews]).to_csv(
        args.out / "tests_review.csv", index=False
    )
    if {"review-query", "review-relevant"} <= set(reviews):  # second study: which review order finds more
        review_effect(outcomes, "review-query", "review-relevant").to_csv(
            args.out / "tests_review_order.csv", index=False
        )
    rankings = system_rankings(outcomes)
    if not rankings.empty:
        rankings.to_csv(args.out / "system_rankings.csv", index=False)
    compared = [args.default_strategy, "agglo-average-G32-solo0-top0", "kmeans-k10"]
    time_sensitivity(outcomes, [s for s in compared if s in set(outcomes.strategy)], args.baseline).to_csv(
        args.out / "time_sensitivity.csv", index=False
    )
    plot_effort_vs_group_size(summary, depth, args.out)
    plot_effort_recall(summary, depth, args.out)
    plot_false_negative_sources(outcomes, args.default_strategy, depth, args.out)
    numbers = headlines(summary, args.default_strategy, depth)
    (args.out / "headlines.json").write_text(json.dumps(numbers, indent=2))
    log_run(
        experiment="analysis",
        name=args.out.name,
        params={
            "runs": [str(run) for run in args.runs],
            "default_strategy": args.default_strategy,
            "depth": depth,
        },
        metrics=numbers,
        artifacts=sorted(args.out.glob("*.csv"))
        + sorted(args.out.glob("*.pdf"))
        + sorted(args.out.glob("*.png"))
        + [args.out / "headlines.json"],
        series=curves(summary, args.default_strategy, depth),
    )
    logger.info("wrote tables and figures to %s", args.out)


if __name__ == "__main__":
    main()
