"""Run with: python tests/test_slots.py (from frontend/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from styles import slots  # noqa: E402

assert slots([38, 60, 4], 7) == [2, 4, 1]
assert slots([11, 60, 5], 5) == [1, 3, 1]
assert slots([0, 200, 0], 5) == [1, 3, 1]
assert slots([10, 10, 10], 2) == [1, 1, 1]  # never fewer than one column each
assert sum(slots([3, 97, 0], 12)) == 12
print("slots: ok")
