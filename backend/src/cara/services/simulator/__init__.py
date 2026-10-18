"""The settings simulator: which grouping saves the most time without losing relevant images.

It replays a study's queries under candidate grouping settings with simulated annotators, and reports effort,
time and recall per setting. It informs the choice; the admin makes it.

- service.py: `SimulatorService`, what the API and CLI call: scope, pilot report, sample qrels, runs;
- plan.py: what to compare (settings and annotator types);
- run.py: one run after its ground truth is read, step by step, with progress events;
- replay.py: the pools replayed, in parallel processes;
- results.py: the tallies and what is reported.

The engine itself is cara.simulation.
"""

from cara.services.simulator.plan import (
    MAX_ANNOTATORS,
    MAX_CANDIDATES,
    AgglomerativeOptions,
    AnnotatorProfile,
    HDBSCANOptions,
    KMeansOptions,
    SimulatorPlan,
    Source,
    default_plan,
    describe,
)
from cara.services.simulator.results import AnnotatorResult, SettingResult
from cara.services.simulator.run import SimulationRun, SimulatorEvent
from cara.services.simulator.service import (
    PilotAnnotator,
    PilotReport,
    Scope,
    SimulatorService,
    parse_qrels,
)

__all__ = [
    "MAX_ANNOTATORS",
    "MAX_CANDIDATES",
    "AgglomerativeOptions",
    "AnnotatorProfile",
    "AnnotatorResult",
    "HDBSCANOptions",
    "KMeansOptions",
    "PilotAnnotator",
    "PilotReport",
    "Scope",
    "SettingResult",
    "SimulationRun",
    "SimulatorEvent",
    "SimulatorPlan",
    "SimulatorService",
    "Source",
    "default_plan",
    "describe",
    "parse_qrels",
]
