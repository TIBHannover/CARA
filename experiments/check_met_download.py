"""Check that every image The Met's ground truth lists was downloaded and unpacked."""

import argparse
import json
from pathlib import Path


def missing_images(root: Path, ground_truth_file: str) -> list[str]:
    """Return the paths in one ground-truth file that have no image under `root`.

    Queries without a `MET_id` are distractors, which are not downloaded.
    """
    entries = json.loads((root / "ground_truth" / ground_truth_file).read_text())
    wanted = [e["path"] for e in entries if "id" in e or "MET_id" in e]
    return [path for path in wanted if not (root / "images" / path).exists()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("met_root", type=Path)
    parser.add_argument("database_file")
    args = parser.parse_args()
    for ground_truth_file in (args.database_file, "testset.json"):
        missing = missing_images(args.met_root, ground_truth_file)
        if missing:
            raise SystemExit(f"{ground_truth_file}: {len(missing)} images are missing, such as {missing[:3]}")


if __name__ == "__main__":
    main()
