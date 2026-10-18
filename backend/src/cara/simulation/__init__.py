"""The judging simulation: simulated annotators work through a pool, and the outcome counts their work.

A workflow (the app's groups, or Suggest mode) asks an assessor (a simulated annotator) what it does at every
step; an optional review round follows; the outcome counts the actions, the time they take and the errors.
`simulate_pool` is the one entry point: the app's simulator (`services/simulator/`) and the simulation study
(`simulation/experiment.py`) both call it.
"""

import numpy as np
import numpy.typing as npt

from cara.simulation.assessors import Assessor, AssessorModel, Perfect, Realistic, RubberStamp
from cara.simulation.case import PoolCase, Tally
from cara.simulation.outcome import PoolOutcome, TimeModel
from cara.simulation.workflows import Grouped, ReviewRound, Setting, SuggestWorkflow, Workflow

__all__ = [
    "Assessor",
    "AssessorModel",
    "Grouped",
    "Perfect",
    "PoolCase",
    "PoolOutcome",
    "Realistic",
    "ReviewRound",
    "RubberStamp",
    "Setting",
    "SuggestWorkflow",
    "Tally",
    "TimeModel",
    "Workflow",
    "simulate_pool",
]


def simulate_pool(
    case: PoolCase, workflow: Workflow, assessor: AssessorModel, review: ReviewRound, rng: np.random.Generator
) -> tuple[PoolOutcome, npt.NDArray[np.bool_]]:
    """Let one simulated annotator judge one pool: the workflow labels it, then the review round corrects it.

    Returns:
        What it cost and how well it went, and the final labels (True: relevant), one per image.
    """
    tally = workflow.label(case, assessor, rng)
    shown_n, flips = review.apply(tally, case, assessor, rng)
    return tally.outcome(case, shown_n, flips), tally.final_n
