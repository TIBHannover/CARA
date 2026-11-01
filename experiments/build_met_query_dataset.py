import argparse
import json
import logging
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd
from embedding_cache import cache_name, cached_images, file_label, fuse, random_pools, top_k
from pydantic import BaseModel, TypeAdapter
from tracking import log_run, numeric_leaves

from cara.encoders import ENCODERS, build_encoder
from cara.inputs import read_embeddings

logger = logging.getLogger(__name__)

REPORT_DEPTHS = (10, 50, 100, 200, 500, 1000)
CARA_YAML = """\
name: {name}
encoder: {grouping}
labels:
  - {{name: Relevant, short: "✓", grade: 1, colour: "#2ecc71"}}
  - {{name: Not Relevant, short: "✗", grade: 0, colour: "#e74c3c"}}
  - {{name: Unsure, short: "?", grade: null, colour: "#f1c40f"}}
pool: {{source: file, k: null}}
order: pool_rank
"""


class DatabaseEntry(BaseModel):
    path: str
    id: int


class QueryEntry(BaseModel):
    path: str
    MET_id: int | None = None


@dataclass(frozen=True, slots=True)
class Corpus:
    key: str
    doc_ids: list[str]
    files: list[Path]
    exhibits: list[int]


@dataclass(frozen=True, slots=True)
class Photo:
    query_id: str
    image: str
    file: Path
    exhibit: int


@dataclass(frozen=True, slots=True)
class MetQuery:
    query_id: str
    text: str
    name: str
    culture: str | None
    photo: Photo | None


def met_corpus(met_root: Path, split: str) -> tuple[Corpus, list[Photo]]:
    truth = met_root / "ground_truth"
    database = TypeAdapter(list[DatabaseEntry]).validate_json((truth / "MET_database.json").read_bytes())
    entries = TypeAdapter(list[QueryEntry]).validate_json((truth / f"{split}set.json").read_bytes())
    corpus = Corpus(
        key="MET_database",
        doc_ids=[e.path for e in database],
        files=[met_root / "images" / e.path for e in database],
        exhibits=[e.id for e in database],
    )
    photos = [
        Photo(Path(e.path).stem, f"images/{e.path}", met_root / "images" / e.path, e.MET_id)
        for e in entries
        if e.MET_id is not None
    ]
    return corpus, photos


def dataset_corpus(folder: Path) -> tuple[Corpus, list[Photo]]:
    with (folder / "queries.jsonl").open() as f:
        queries = [json.loads(line) for line in f if line.strip()]
    exhibit_of = json.loads((folder / "query_exhibits.json").read_text())
    candidates = {c["doc_id"]: c["image"] for q in queries for c in q["candidates"]}
    corpus = Corpus(
        key=folder.name,
        doc_ids=list(candidates),
        files=[folder / image for image in candidates.values()],
        exhibits=[int(doc_id.split("/")[1]) for doc_id in candidates],
    )
    photos = [
        Photo(q["query_id"], q["image"], folder / q["image"], exhibit_of[q["query_id"]]) for q in queries
    ]
    return corpus, photos


def read_metadata(met_objects: Path) -> tuple[dict[int, str], dict[int, str]]:
    meta = pd.read_csv(met_objects, usecols=["Object ID", "Object Name", "Culture"], low_memory=False)
    meta = meta.set_index("Object ID")
    name = meta["Object Name"].dropna().str.strip().str.lower()
    culture = meta["Culture"].dropna().str.strip()
    return name[name != ""].to_dict(), culture[culture != ""].to_dict()


def make_queries(
    task: str,
    photos: list[Photo],
    corpus_keys: Counter[tuple[str, str | None]],
    name_of: dict[int, str],
    culture_of: dict[int, str],
    min_positives: int,
    rng: random.Random,
) -> list[MetQuery]:
    if task == "text":
        names = sorted({name_of[p.exhibit] for p in photos if p.exhibit in name_of})
        names = [n for n in names if corpus_keys[(n, None)] >= min_positives]
        return [MetQuery(f"t{i:04d}", f"a photo of a {n}", n, None, None) for i, n in enumerate(names)]
    if task == "text_culture":
        pairs = sorted(
            {
                (name_of[p.exhibit], culture_of[p.exhibit])
                for p in photos
                if p.exhibit in name_of and p.exhibit in culture_of
            }
        )
        pairs = [(n, c) for n, c in pairs if corpus_keys[(n, c)] >= min_positives]
        return [
            MetQuery(f"tc{i:04d}", f"a photo of a {n}, {c}", n, c, None) for i, (n, c) in enumerate(pairs)
        ]
    queries = []
    for photo in photos:
        name = name_of.get(photo.exhibit)
        if name is None:
            continue
        targets = sorted(
            c
            for (n, c), count in corpus_keys.items()
            if n == name and c is not None and c != culture_of.get(photo.exhibit) and count >= min_positives
        )
        if targets:
            target = rng.choice(targets)
            caption = f"the same kind of object, but {target}"
            queries.append(MetQuery(photo.query_id, caption, name, target, photo))
    return queries


def main() -> None:
    parser = argparse.ArgumentParser(description="Text or composed queries over The Met, judged by metadata.")
    parser.add_argument("met_objects", type=Path, help="MetObjects.csv (Met Open Access, CC0)")
    parser.add_argument("out", type=Path)
    parser.add_argument("--task", choices=["text", "text_culture", "composed"], required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--met-root", type=Path, help="Met dataset with ground_truth/ and images/")
    source.add_argument(
        "--corpus-dataset", type=Path, help="small test: use a dataset folder's pool images as corpus"
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--split", choices=["test", "val"], default="test")
    parser.add_argument(
        "--retrievers",
        nargs="+",
        default=["siglip2"],
        help="cross-modal encoders that build the pools (names or <family>:<model id>), fused by reciprocal "
        "rank fusion when several",
    )
    parser.add_argument(
        "--pool", choices=["ranked", "random"], default="ranked", help="random: a random sample per query"
    )
    parser.add_argument(
        "--grouping", default="dinov3", help=f"one of {sorted(ENCODERS)}, or <name>:<model id>"
    )
    parser.add_argument("--depth", type=int, default=200)
    parser.add_argument("--min-positives", type=int, default=5)
    parser.add_argument("--max-queries", type=int, default=0, help="0 = all")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--num-workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rng = random.Random(args.seed)

    corpus, photos = (
        met_corpus(args.met_root, args.split) if args.met_root else dataset_corpus(args.corpus_dataset)
    )
    name_of, culture_of = read_metadata(args.met_objects)
    keys = [(name_of.get(e), culture_of.get(e)) for e in corpus.exhibits]
    corpus_keys: Counter[tuple[str, str | None]] = Counter(keys) + Counter((n, None) for n, _ in keys)
    queries = make_queries(args.task, photos, corpus_keys, name_of, culture_of, args.min_positives, rng)
    if args.max_queries:
        queries = rng.sample(queries, min(args.max_queries, len(queries)))
    logger.info("%s: %d queries over %d corpus images", args.task, len(queries), len(corpus.doc_ids))

    def model_cache(encoder: str) -> Path:
        return args.cache_dir / cache_name(corpus.key, encoder)

    def ranking(retriever: str) -> npt.NDArray[np.int64]:
        retrieval_nd = cached_images(
            corpus.files, retriever, model_cache(retriever), args.batch_size, args.num_workers
        )
        text_qd = build_encoder(retriever).encode_texts([q.text for q in queries], args.batch_size)
        if args.task == "composed":
            photo_qd = cached_images(
                [q.photo.file for q in queries if q.photo],
                retriever,
                args.out / f"query_photos__{file_label(retriever)}.npy",
                args.batch_size,
                args.num_workers,
            )
            fused = photo_qd.astype(np.float32) + text_qd.astype(np.float32)
            query_qd = (fused / np.linalg.norm(fused, axis=1, keepdims=True)).astype(np.float16)
        else:
            query_qd = text_qd
        return top_k(query_qd, retrieval_nd, reach)

    reach = min(len(corpus.doc_ids), max(args.depth, *REPORT_DEPTHS))
    if args.pool == "random":
        ranked_qk = random_pools(len(corpus.doc_ids), len(queries), reach, args.seed)
    else:
        rankings = [ranking(retriever) for retriever in args.retrievers]
        ranked_qk = rankings[0] if len(rankings) == 1 else fuse(rankings, reach)
    pools_qk = ranked_qk[:, : args.depth]

    if args.corpus_dataset:
        ids, emb_nd = read_embeddings(args.corpus_dataset / "embeddings.npz")
        lookup = dict(zip(ids, emb_nd, strict=True))
        image_of = {
            d: f.relative_to(args.corpus_dataset).as_posix()
            for d, f in zip(corpus.doc_ids, corpus.files, strict=True)
        }
        grouping_nd = np.stack([lookup[image_of[d]] for d in corpus.doc_ids]).astype(np.float16)
    else:
        grouping_nd = cached_images(
            corpus.files, args.grouping, model_cache(args.grouping), args.batch_size, args.num_workers
        )
        image_of = {d: f"images/{d}" for d in corpus.doc_ids}

    is_relevant = {
        q.query_id: np.array([k[0] == q.name and (q.culture is None or k[1] == q.culture) for k in keys])
        for q in queries
    }
    args.out.mkdir(parents=True, exist_ok=True)
    lines, qrels, recall_at, shares = [], [], {d: [] for d in REPORT_DEPTHS}, []
    for query, ranked_k in zip(queries, ranked_qk, strict=True):
        relevant_n = is_relevant[query.query_id]
        pool_k = ranked_k[: args.depth]
        line: dict[str, object] = {
            "query_id": query.query_id,
            "text": query.text,
            "candidates": [
                {"doc_id": corpus.doc_ids[i], "image": image_of[corpus.doc_ids[i]]} for i in pool_k
            ],
        }
        if query.photo:
            line["image"] = query.photo.image
        lines.append(json.dumps(line))
        qrels += [f"{query.query_id} 0 {corpus.doc_ids[i]} 1" for i in pool_k if relevant_n[i]]
        shares.append(float(relevant_n[pool_k].mean()))
        for depth in REPORT_DEPTHS:
            recall_at[depth].append(float(relevant_n[ranked_k[:depth]].sum() / relevant_n.sum()))

    (args.out / "queries.jsonl").write_text("\n".join(lines) + "\n")
    (args.out / "category.qrels").write_text("\n".join(qrels) + "\n")
    name = {"text": "Met text", "text_culture": "Met text + culture", "composed": "Met composed"}[args.task]
    (args.out / "cara.yaml").write_text(CARA_YAML.format(name=name, grouping=args.grouping))
    pooled = sorted({int(i) for i in pools_qk.ravel()})
    np.savez(
        args.out / "embeddings.npz",
        ids=np.array([image_of[corpus.doc_ids[i]] for i in pooled]),
        emb_nd=grouping_nd[pooled],
    )
    stats = {
        "task": args.task,
        "corpus": corpus.key,
        "pool": args.pool,
        "retrievers": [build_encoder(r).model_id for r in args.retrievers] if args.pool == "ranked" else [],
        "grouping": build_encoder(args.grouping).model_id,
        "queries": len(queries),
        "depth": args.depth,
        "min_positives": args.min_positives,
        "positives_in_collection": {
            "mean": float(np.mean([is_relevant[q.query_id].sum() for q in queries])),
            "median": float(np.median([is_relevant[q.query_id].sum() for q in queries])),
        },
        "positive_share_in_pool": {"mean": float(np.mean(shares)), "median": float(np.median(shares))},
        "mean_recall_at": {d: float(np.mean(r)) for d, r in recall_at.items()},
    }
    (args.out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    log_run(
        experiment="datasets",
        name=args.out.name,
        params={key: str(value) for key, value in vars(args).items()},
        metrics=numeric_leaves(stats),
        artifacts=[args.out / "stats.json"],
    )
    logger.info("stats: %s", stats)


if __name__ == "__main__":
    main()
