"""Log an experiment's parameters, metrics and files with runlog, when `RUNLOG_DIR` is set."""

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from runlog import Run

logger = logging.getLogger(__name__)

PROJECT = "cara_demo"


def log_run(
    experiment: str,
    name: str,
    params: Mapping[str, object],
    metrics: Mapping[str, float],
    artifacts: list[Path],
    series: list[tuple[str, int, float]] | None = None,
) -> None:
    """Log one run under project `cara_demo`; without `RUNLOG_DIR`, only warn (outputs stay where they are).

    Args:
        series: (metric, step, value) triples, for metrics logged per step.
    """
    if not os.environ.get("RUNLOG_DIR"):
        logger.warning("RUNLOG_DIR is not set: %s/%s stays in the local output folder only", experiment, name)
        return
    with Run(project=PROJECT, name=name, experiment=experiment, params=params) as run:
        run.log(metrics)
        for key, step, value in series or []:
            run.log({key: value}, step=step)
        for path in artifacts:
            run.artifact(path, path.name)
    logger.info("logged %s/%s to %s", experiment, name, os.environ["RUNLOG_DIR"])


def numeric_leaves(data: Mapping[str, object], prefix: str = "") -> dict[str, float]:
    """Return the numbers of a nested mapping as flat metrics keyed by path (`a/b/c`), booleans skipped."""
    leaves: dict[str, float] = {}
    for key, value in data.items():
        if isinstance(value, Mapping):
            leaves |= numeric_leaves(value, f"{prefix}{key}/")
        elif isinstance(value, int | float) and not isinstance(value, bool):
            leaves[f"{prefix}{key}"] = float(value)
    return leaves
