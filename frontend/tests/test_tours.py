"""Run with: python tests/test_tours.py (from frontend/). Checks every tour file in tours/ loads."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.tours import FOLDER, load  # noqa: E402

tours = load()
assert {"new-study", "pilot-page", "simulator", "study-page", "pilot", "judge", "suggest", "review"} <= set(
    tours
)
assert all(steps and all(step.title and step.text for step in steps) for steps in tours.values())

with tempfile.TemporaryDirectory() as folder:
    (Path(folder) / "_shared.json").write_text((FOLDER / "_shared.json").read_text())
    (Path(folder) / "bad.json").write_text(
        json.dumps({"name": "x", "page": "p", "when": "w", "steps": [{"use": "nope"}]})
    )
    try:
        load(Path(folder))
    except ValueError as error:
        assert "no shared steps 'nope'" in str(error)
    else:
        raise AssertionError("an unknown shared key must fail")
print(f"tours: ok ({len(tours)} tours, {sum(len(s) for s in tours.values())} steps)")
