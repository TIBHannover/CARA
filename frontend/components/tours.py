"""The guided tours' content, read from `tours/*.json`; `tour.py` draws them.

One file per tour, numbered in the order of the workflow (admin steps first, then the annotator's):

    {"name": "judge",                          # also the browser key that records it was seen
     "page": "Judge page, Judge mode (annotators)",
     "when": "Judging a query group by group.",
     "steps": [{"element": ".st-key-query-panel", "title": "The query", "text": "Judge every image ..."},
               {"use": "end"}]}

`element` is a CSS selector, or null for a step without an element; steps whose element is not on the page
are left out. `{"use": "<key>"}` inserts the steps stored under that key in `tours/_shared.json`. The files
are read on every run, so an edit shows on the next page load.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

import tour

FOLDER = Path(__file__).parent.parent / "tours"
SHARED = "_shared.json"


class Step(BaseModel):
    """One step of a tour."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    element: str | None
    title: str
    text: str


class Use(BaseModel):
    """A placeholder for the shared steps stored under `use` in `_shared.json`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    use: str


class TourFile(BaseModel):
    """One tour file: where and when the tour shows, and its steps."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    page: str
    when: str
    steps: list[Step | Use]


def load(folder: Path = FOLDER) -> dict[str, list[Step]]:
    """Return every tour's steps by name, with the shared steps filled in.

    Raises:
        ValueError: A file doesn't match the format (pydantic says where), two files share a name, or a step
            uses a key that `_shared.json` doesn't have.
    """
    shared = {
        key: [Step.model_validate(step) for step in steps]
        for key, steps in json.loads((folder / SHARED).read_text()).items()
    }
    tours: dict[str, list[Step]] = {}
    for path in sorted(folder.glob("*.json")):
        if path.name == SHARED:
            continue
        found = TourFile.model_validate_json(path.read_text())
        if found.name in tours:
            raise ValueError(f"{path.name}: tour {found.name!r} is defined twice")
        steps: list[Step] = []
        for step in found.steps:
            if isinstance(step, Use) and step.use not in shared:
                raise ValueError(f"{path.name}: no shared steps {step.use!r} in {SHARED} ({sorted(shared)})")
            steps += shared[step.use] if isinstance(step, Use) else [step]
        tours[found.name] = steps
    return tours


def show(name: str) -> None:
    """Draw the Tour button and offer tour `name` (on a first visit, or after the button is pressed)."""
    tour.button(name)
    tour.tour(name, [(step.element, step.title, step.text) for step in load()[name]])
