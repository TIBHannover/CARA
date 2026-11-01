"""Write category qrels for a Met dataset: relevant means sharing a metadata field with the query exhibit.

The field (default `Object Name`) comes from the Met Open Access metadata, `MetObjects.csv` (CC0).
"""

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def exhibit_of(doc_id: str) -> int:
    """Return the Met object id in a candidate's doc id (its second path part)."""
    return int(doc_id.split("/")[1])


def main() -> None:
    """Write `category_<field>.qrels` and its stats (positive share per pool) to the dataset folder."""
    parser = argparse.ArgumentParser(
        description="Category qrels for a Met dataset: relevant = same metadata field as the query exhibit."
    )
    parser.add_argument("folder", type=Path, help="dataset folder built by build_met_dataset.py")
    parser.add_argument(
        "met_objects", type=Path, help="MetObjects.csv from github.com/metmuseum/openaccess (CC0)"
    )
    parser.add_argument("--field", default="Object Name")
    parser.add_argument(
        "--met-root",
        type=Path,
        help="the Met dataset (ground_truth/MET_database.json): also count each query's positives in the "
        "whole collection, not only in its pool",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    meta = pd.read_csv(args.met_objects, usecols=["Object ID", args.field], low_memory=False)
    value_of = meta.dropna().set_index("Object ID")[args.field].str.strip().str.lower().to_dict()
    exhibit_by_query = json.loads((args.folder / "query_exhibits.json").read_text())
    with (args.folder / "queries.jsonl").open() as f:
        queries = [json.loads(line) for line in f if line.strip()]

    lines, shares, excluded, unmatched_candidates = [], [], [], 0
    for query in queries:
        query_value = value_of.get(exhibit_by_query[query["query_id"]])
        if query_value is None:
            excluded.append(query["query_id"])
            continue
        candidate_values = [value_of.get(exhibit_of(c["doc_id"])) for c in query["candidates"]]
        unmatched_candidates += sum(v is None for v in candidate_values)
        positives = [
            c["doc_id"]
            for c, v in zip(query["candidates"], candidate_values, strict=True)
            if v == query_value
        ]
        lines += [f"{query['query_id']} 0 {doc_id} 1" for doc_id in positives]
        shares.append(len(positives) / len(query["candidates"]))

    name = args.field.lower().replace(" ", "_")
    (args.folder / f"category_{name}.qrels").write_text("\n".join(lines) + "\n")
    stats = {
        "field": args.field,
        "match": "exact, case-insensitive, whitespace-trimmed",
        "qrels_convention": "positives only; every other pooled candidate is judged non-relevant",
        "queries": len(queries),
        "queries_scored": len(shares),
        "excluded_queries_without_field": excluded,
        "candidates_without_field": unmatched_candidates,
        "positive_share_per_pool": {
            "mean": float(np.mean(shares)),
            "p25": float(np.percentile(shares, 25)),
            "median": float(np.median(shares)),
            "p75": float(np.percentile(shares, 75)),
            "pools_with_zero_positives": int(sum(s == 0 for s in shares)),
            "pools_above_half": int(sum(s > 0.5 for s in shares)),
        },
    }
    if args.met_root:
        database = json.loads((args.met_root / "ground_truth" / "MET_database.json").read_text())
        images_per_value = Counter(value_of.get(entry["id"]) for entry in database)
        in_collection = [
            images_per_value[value_of[exhibit]]
            for exhibit in exhibit_by_query.values()
            if exhibit in value_of
        ]
        stats["positives_in_collection"] = {
            "mean": float(np.mean(in_collection)),
            "median": float(np.median(in_collection)),
        }
    (args.folder / f"category_{name}_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    logger.info("wrote %d positives for %d queries; %d excluded", len(lines), len(shares), len(excluded))


if __name__ == "__main__":
    main()
