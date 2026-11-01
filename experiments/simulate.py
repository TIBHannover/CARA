import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat
from pathlib import Path

import hydra
import numpy as np
import numpy.typing as npt
import pandas as pd
from hydra.core.hydra_config import HydraConfig
from omegaconf import DictConfig, OmegaConf
from tracking import log_run

from cara.inputs import read_embeddings
from cara.simulation.experiment import DatasetSpec, QueryInput, SimulationConfig, simulate_query

logger = logging.getLogger(__name__)


def read_positives(path: Path) -> dict[str, set[str]]:
    positives: dict[str, set[str]] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            query_id, _, doc_id, grade = line.split()
            if int(grade) > 0:
                positives.setdefault(query_id, set()).add(doc_id)
    return positives


def embedding_lookup(path: Path) -> dict[str, npt.NDArray[np.float32]]:
    ids, emb_nd = read_embeddings(path)
    return dict(zip(ids, emb_nd, strict=True))


def query_key(lookup: dict[str, npt.NDArray[np.float32]], query: dict[str, object]) -> str | None:
    composed = f"query:{query['query_id']}"
    if composed in lookup:
        return composed
    image = query.get("image")
    return image if isinstance(image, str) and image in lookup else None


def load_queries(dataset: DatasetSpec) -> list[QueryInput]:
    with (dataset.folder / "queries.jsonl").open() as f:
        queries = [json.loads(line) for line in f if line.strip()][: dataset.max_queries]
    grouping = embedding_lookup(dataset.folder / dataset.embeddings)
    systems = {}
    for name, path in dataset.systems.items():
        if (dataset.folder / path).exists():
            systems[name] = embedding_lookup(dataset.folder / path)
        else:
            logger.warning("system %s: %s is missing, so it is left out of the ranking analysis", name, path)
    qrels = {name: (read_positives(spec.path), set(spec.exclude)) for name, spec in dataset.qrels.items()}
    inputs = []
    for query in queries:
        candidates = query["candidates"]
        images = [c["image"] for c in candidates]
        key = query_key(grouping, query)
        system_scores = {}
        for name, lookup in systems.items():
            system_key = query_key(lookup, query)
            if system_key is None:
                raise KeyError(f"system {name} has no embedding for query {query['query_id']}")
            system_scores[name] = np.stack([lookup[i] for i in images]) @ lookup[system_key]
        inputs.append(
            QueryInput(
                query_id=query["query_id"],
                emb_nd=np.stack([grouping[i] for i in images]),
                query_emb_d=grouping[key] if key is not None else None,
                truth_by_qrels={
                    name: np.array(
                        [c["doc_id"] in positives.get(query["query_id"], set()) for c in candidates]
                    )
                    for name, (positives, excluded) in qrels.items()
                    if query["query_id"] not in excluded
                },
                system_scores=system_scores,
            )
        )
    return inputs


@hydra.main(version_base=None, config_path="../configs", config_name="simulate")
def main(raw_cfg: DictConfig) -> None:
    config = SimulationConfig.model_validate(OmegaConf.to_object(raw_cfg))
    run_dir = Path(HydraConfig.get().runtime.output_dir)
    started = time.perf_counter()
    queries = load_queries(config.dataset)
    logger.info(
        "%d queries, %d strategies, %d depths, %d assessors",
        len(queries),
        len(config.all_settings()),
        len(config.depths),
        len(config.assessors),
    )
    with ProcessPoolExecutor(config.workers) as executor:
        chunks = executor.map(simulate_query, queries, repeat(config), chunksize=2)
        rows = [row for chunk in chunks for row in chunk]
    outcomes = pd.DataFrame(rows)
    outcomes.to_parquet(run_dir / "outcomes.parquet", index=False)
    (run_dir / "config.json").write_text(config.model_dump_json(indent=2))
    logger.info("wrote %d rows to %s", len(outcomes), run_dir / "outcomes.parquet")
    # The first study logs as "simulation"; later ones under their config name (e.g. study2).
    config_name = HydraConfig.get().job.config_name
    log_run(
        experiment="simulation" if config_name == "simulate" else config_name,
        name=config.dataset.name,
        params={
            "dataset": config.dataset.name,
            "grouping_embeddings": config.dataset.embeddings,
            "order": config.dataset.order,
            "depths": config.depths,
            "strategies": len(config.all_settings()),
            "assessors": [a.name for a in config.assessors],
            "reviews": [r.name for r in config.reviews],
            "seed": config.seed,
        },
        metrics={
            "queries": len(queries),
            "rows": len(outcomes),
            "minutes": (time.perf_counter() - started) / 60,
        },
        artifacts=[run_dir / "outcomes.parquet", run_dir / "config.json"],
    )


if __name__ == "__main__":
    main()
