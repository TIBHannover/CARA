import argparse
import json
import logging
import random
from pathlib import Path

import numpy as np
import numpy.typing as npt
from embedding_cache import cache_name, cached_images, fuse, random_pools, top_k
from PIL import Image
from pydantic import BaseModel, TypeAdapter
from tqdm import tqdm
from tracking import log_run, numeric_leaves

from cara.encoders import ENCODERS, build_encoder

logger = logging.getLogger(__name__)

REPORT_DEPTHS = (10, 25, 50, 100, 200, 500, 1000)

CARA_YAML = """\
name: The Met ({split})
encoder: {encoder}
labels:
  - {{name: Relevant, short: "✓", grade: 1, colour: "#2ecc71"}}
  - {{name: Not Relevant, short: "✗", grade: 0, colour: "#e74c3c"}}
  - {{name: Unsure, short: "?", grade: null, colour: "#f1c40f"}}
pool: {{source: file, k: null}}
grouping: {{method: agglomerative, max_size: 16}}
"""


class DatabaseEntry(BaseModel):
    path: str
    id: int


class QueryEntry(BaseModel):
    path: str
    MET_id: int | None = None
    url: str = "None"


def recall_at_depths(
    queries: list[QueryEntry],
    ranked_qk: npt.NDArray[np.int64],
    database: list[DatabaseEntry],
    n_positives_by_id: dict[int, int],
) -> dict[int, float]:
    is_hit_qk = np.array(
        [[database[i].id == q.MET_id for i in ranked] for q, ranked in zip(queries, ranked_qk, strict=True)]
    )
    n_positives_q = np.array([n_positives_by_id[q.MET_id] for q in queries if q.MET_id is not None])
    depths = [k for k in REPORT_DEPTHS if k <= ranked_qk.shape[1]]
    return {k: float((is_hit_qk[:, :k].sum(axis=1) / n_positives_q).mean()) for k in depths}


def save_resized(source: Path, target: Path, max_side: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        img.save(target, format="JPEG", quality=90)


def limit_database(
    database: list[DatabaseEntry], kept_objects: set[int | None], max_images: int, seed: int
) -> list[DatabaseEntry]:
    """Return every image of the kept objects, then a random sample up to `max_images` in all."""
    kept = [entry for entry in database if entry.id in kept_objects]
    others = [entry for entry in database if entry.id not in kept_objects]
    extra = max(0, max_images - len(kept))
    return kept + random.Random(seed).sample(others, min(extra, len(others)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a CARA dataset folder from The Met dataset.")
    parser.add_argument("met_root", type=Path, help="directory holding ground_truth/ and images/")
    parser.add_argument("out", type=Path, help="dataset folder to write")
    parser.add_argument("--cache-dir", type=Path, required=True, help="where database embeddings are cached")
    parser.add_argument("--split", choices=["test", "val"], default="test")
    parser.add_argument("--queries", type=int, default=50, help="Met queries to sample; 0 = all")
    parser.add_argument("--depth", type=int, default=200)
    parser.add_argument("--mini", action="store_true", help="use the mini Met database (3 GB)")
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="encode at most this many database images, always with the query objects' images; 0 = all",
    )
    parser.add_argument("--skip-images", action="store_true", help="write pools and ground truth only")
    parser.add_argument("--max-side", type=int, default=640)
    parser.add_argument(
        "--encoder",
        default="dinov3",
        help=f"groups the pools: one of {sorted(ENCODERS)}, or <name>:<model id>",
    )
    parser.add_argument(
        "--retrievers",
        nargs="+",
        help="encoders that build the pools, fused by reciprocal rank fusion when several "
        "(default: --encoder)",
    )
    parser.add_argument(
        "--pool", choices=["ranked", "random"], default="ranked", help="random: a random sample per query"
    )
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--num-workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--authors-photos-only",
        action="store_true",
        help="keep queries photographed by the dataset authors (no Flickr attribution needed)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ground_truth = args.met_root / "ground_truth"
    images = args.met_root / "images"
    database_file = "mini_MET_database.json" if args.mini else "MET_database.json"
    database = TypeAdapter(list[DatabaseEntry]).validate_json((ground_truth / database_file).read_bytes())
    queries = [
        entry
        for entry in TypeAdapter(list[QueryEntry]).validate_json(
            (ground_truth / f"{args.split}set.json").read_bytes()
        )
        if entry.MET_id is not None and not (args.authors_photos_only and entry.url != "None")
    ]
    if args.queries:
        queries = random.Random(args.seed).sample(queries, min(args.queries, len(queries)))
    if args.max_images:
        database = limit_database(database, {q.MET_id for q in queries}, args.max_images, args.seed)
    logger.info("%d database images, %d queries from %sset", len(database), len(queries), args.split)

    model_id = build_encoder(args.encoder).model_id
    database_name = Path(database_file).stem + (f"-{args.max_images}" if args.max_images else "")
    cache = args.cache_dir / cache_name(database_name, args.encoder)
    db_emb_nd = cached_images(
        [images / e.path for e in database], args.encoder, cache, args.batch_size, args.num_workers
    )
    query_emb_qd = build_encoder(args.encoder).encode_images(
        [images / q.path for q in queries], args.batch_size, args.num_workers
    )
    reach = min(len(database), max(args.depth, *REPORT_DEPTHS))
    retrievers = args.retrievers or [args.encoder]
    if args.pool == "random":
        ranked_qk = random_pools(len(database), len(queries), reach, args.seed)
    else:
        rankings = []
        for retriever in retrievers:
            if retriever == args.encoder:
                rankings.append(top_k(query_emb_qd, db_emb_nd, reach))
                continue
            retriever_nd = cached_images(
                [images / e.path for e in database],
                retriever,
                args.cache_dir / cache_name(database_name, retriever),
                args.batch_size,
                args.num_workers,
            )
            retriever_qd = build_encoder(retriever).encode_images(
                [images / q.path for q in queries], args.batch_size, args.num_workers
            )
            rankings.append(top_k(retriever_qd, retriever_nd, reach))
        ranked_qk = rankings[0] if len(rankings) == 1 else fuse(rankings, reach)
    pools_qk = ranked_qk[:, : args.depth]

    n_positives_by_id: dict[int, int] = {}
    for entry in database:
        n_positives_by_id[entry.id] = n_positives_by_id.get(entry.id, 0) + 1
    args.out.mkdir(parents=True, exist_ok=True)
    query_lines, qrels_lines, recalls = [], [], []
    for query, pool_k in zip(queries, pools_qk, strict=True):
        query_id = Path(query.path).stem
        candidates = [{"doc_id": database[i].path, "image": f"images/{database[i].path}"} for i in pool_k]
        query_lines.append(
            json.dumps({"query_id": query_id, "image": f"images/{query.path}", "candidates": candidates})
        )
        hits = [database[i].path for i in pool_k if database[i].id == query.MET_id]
        qrels_lines += [f"{query_id} 0 {doc_id} 1" for doc_id in hits]
        recalls.append(len(hits) / n_positives_by_id[query.MET_id])

    (args.out / "queries.jsonl").write_text("\n".join(query_lines) + "\n")
    (args.out / "ground_truth.qrels").write_text("\n".join(qrels_lines) + "\n")
    (args.out / "cara.yaml").write_text(CARA_YAML.format(split=args.split, encoder=args.encoder))
    exhibit_by_query = {Path(q.path).stem: q.MET_id for q in queries}
    (args.out / "query_exhibits.json").write_text(json.dumps(exhibit_by_query, indent=1) + "\n")
    pooled = sorted({int(i) for i in pools_qk.ravel()})
    ids = [f"images/{q.path}" for q in queries] + [f"images/{database[i].path}" for i in pooled]
    np.savez(
        args.out / "embeddings.npz",
        ids=np.array(ids),
        emb_nd=np.concatenate([query_emb_qd, db_emb_nd[pooled]]),
    )
    stats = {
        "split": args.split,
        "database": database_file,
        "model_id": model_id,
        "pool": args.pool,
        "retrievers": [build_encoder(r).model_id for r in retrievers] if args.pool == "ranked" else [],
        "queries": len(queries),
        "positives_in_collection": {
            "mean": float(np.mean([n_positives_by_id[q.MET_id] for q in queries])),
            "median": float(np.median([n_positives_by_id[q.MET_id] for q in queries])),
        },
        "depth": args.depth,
        "pooled_images": len(pooled),
        "queries_with_positive_in_pool": int(sum(r > 0 for r in recalls)),
        "mean_recall_at_depth": float(np.mean(recalls)),
        "mean_recall_at": recall_at_depths(queries, ranked_qk, database, n_positives_by_id),
    }
    (args.out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    log_run(
        experiment="datasets",
        name=args.out.name,
        params={key: str(value) for key, value in vars(args).items()},
        metrics=numeric_leaves(stats),
        artifacts=[args.out / "stats.json"],
    )
    logger.info("pool stats: %s", stats)

    if not args.skip_images:
        for path in tqdm(
            [q.path for q in queries] + [database[i].path for i in pooled], desc="copying", mininterval=60
        ):
            save_resized(images / path, args.out / "images" / path, args.max_side)


if __name__ == "__main__":
    main()
