"""Datasets shared by studies, pooling rules, the first admin, the New study page, and file errors."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from conftest import SETTINGS, blobs, login
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cara.errors import Invalid, NotFound
from cara.inputs import read_embeddings, read_queries
from cara.repositories.database import Database
from cara.services.datasets import DatasetService
from cara.services.pipeline import PipelineService
from cara.services.simulator import SimulatorService
from cara.services.users import UserService
from cara.settings import PoolSettings, StudySettings


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _dataset_folder(root: Path) -> Path:
    """30 corpus images in 3 blobs; image queries (one per blob) and text queries with their own embedding."""
    folder = root / "shapes"
    emb = blobs(n_blobs=3, per_blob=10)
    corpus = [{"doc_id": f"d{i}", "image": f"img/{i}.png"} for i in range(len(emb))]
    _write_jsonl(folder / "corpus.jsonl", corpus)
    _write_jsonl(
        folder / "queries" / "image.jsonl",
        [{"query_id": f"i{b}", "image": f"queries/{b}.png"} for b in range(3)],
    )
    _write_jsonl(
        folder / "queries" / "text.jsonl", [{"query_id": f"t{b}", "text": f"blob {b}"} for b in range(3)]
    )
    (folder / "dataset.yaml").write_text("name: Shapes\ndescription: three blobs\n")
    index = folder / "index" / SETTINGS.encoder
    index.mkdir(parents=True)
    query_emb = emb[[0, 10, 20]]
    paths = [row["image"] for row in corpus] + [f"queries/{b}.png" for b in range(3)]
    np.savez(index / "corpus.npz", ids=np.array(paths), emb_nd=np.concatenate([emb, query_emb]))
    np.savez(index / "queries-text.npz", ids=np.array(["t0", "t1", "t2"]), emb_nd=query_emb)
    (folder / "qrels").mkdir()
    (folder / "qrels" / "text.qrels").write_text("t0 0 d0 1\n")
    return folder


def test_two_studies_share_a_dataset(clean: sessionmaker[Session], tmp_path: Path) -> None:
    knn = SETTINGS.model_copy(update={"pool": PoolSettings(source="knn", k=10)})
    with clean.begin() as session:
        db = Database(session)
        dataset_id = DatasetService(db).add_folder(_dataset_folder(tmp_path), None, None, None).id
        PipelineService(db).setup_study(
            knn.model_copy(update={"name": "by image"}), dataset_id, "image", 2, 0, []
        )
        PipelineService(db).setup_study(
            knn.model_copy(update={"name": "by text"}), dataset_id, "text", None, 0, []
        )
        by_image, by_text = db.studies.list_pools(1), db.studies.list_pools(2)
        assert len(by_image) == 2 and len(by_text) == 3
        # A text query is pooled by its own embedding: blob b's text finds the 10 images of blob b.
        for pool in by_text:
            blob = int(pool.query.external_id[1])
            doc_ids = {m.image.external_id for m in pool.members}
            assert doc_ids == {f"d{i}" for i in range(10 * blob, 10 * blob + 10)}
        # Each study serves only its own query and pool images, though both share the dataset.
        text_only = {m.image_id for p in by_text for m in p.members} - {
            m.image_id for p in by_image for m in p.members
        }
        assert text_only and not any(db.studies.has_image(1, i) for i in text_only)
        assert all(db.studies.has_image(2, i) for i in text_only)
        assert db.studies.has_image(1, by_image[0].query.image_id or 0)
        assert SimulatorService(db).sample_qrels(tmp_path, 2) == "t0 0 d0 1\n"
        with pytest.raises(NotFound):
            SimulatorService(db).sample_qrels(tmp_path, 1)


def test_queries_without_an_embedding_cannot_be_pooled(clean: sessionmaker[Session], tmp_path: Path) -> None:
    folder = _dataset_folder(tmp_path)
    (folder / "index" / SETTINGS.encoder / "queries-text.npz").unlink()
    knn = SETTINGS.model_copy(update={"pool": PoolSettings(source="knn", k=10)})
    with clean.begin() as session:
        db = Database(session)
        dataset_id = DatasetService(db).add_folder(folder, None, None, None).id
        with pytest.raises(Invalid, match="cara encode"):
            PipelineService(db).setup_study(knn, dataset_id, "text", None, 0, [])
        with pytest.raises(Invalid, match="has no candidates"):
            PipelineService(db).setup_study(
                SETTINGS.model_copy(update={"name": "f"}), dataset_id, "image", None, 0, []
            )


def test_the_first_admin_is_created_only_on_an_empty_database(clean: sessionmaker[Session]) -> None:
    with clean.begin() as session:
        users = UserService(Database(session))
        assert users.add_first_admin("admin", "pw")
        assert not users.add_first_admin("other", "pw")
        assert users.get("admin").is_superuser


def test_datasets_are_listed_for_superusers_only(client: TestClient) -> None:
    assert client.get("/datasets", headers=login(client, "ann")).status_code == 403
    [toy] = client.get("/datasets", headers=login(client, "root")).json()
    assert toy["name"] == "toy" and toy["studies"] == 1 and toy["query_sets"] == {"default": 1}
    assert toy["images"] == 12 and toy["encoders"] == {SETTINGS.encoder: 12}


def test_a_study_is_created_from_the_dashboard(client: TestClient) -> None:
    root = login(client, "root")
    [toy] = client.get("/datasets", headers=root).json()
    [info] = toy["sets"]
    assert info["kind"] == "image" and info["given_pools"] and info["queries"] == 1
    assert info["given_encoders"] == info["knn_encoders"] == [SETTINGS.encoder]
    body = {
        "name": "second look",
        "dataset_id": toy["id"],
        "query_set": "default",
        "encoder": SETTINGS.encoder,
        "k": 6,
        "unsure": False,
        "annotators": ["bob"],
    }
    assert client.post("/studies", json=body, headers=login(client, "ann")).status_code == 403
    assert client.post("/studies", json=body | {"encoder": "other"}, headers=root).status_code == 422
    created = client.post("/studies", json=body, headers=root)
    assert created.status_code == 201
    study = created.json()
    assert study["dataset"] == "toy" and study["overview"]["annotation_queries"] == 1
    assert [label["offered"] for label in study["settings"]["labels"]] == [True, True, False]
    bob = login(client, "bob")
    view = client.get(f"/studies/{study['id']}/queries/2", headers=bob).json()
    assert view["pool_size"] == 6
    assert client.get("/users", headers=root).json() == ["ann", "bob", "eve", "root"]
    assert client.get("/users", headers=bob).status_code == 403


def test_dataset_files_report_where_they_are_wrong(tmp_path: Path) -> None:
    queries = tmp_path / "queries.jsonl"
    queries.write_text('{"query_id": "q1", "text": "a vase"}\n\n{"query_id": "q2"}\n')
    with pytest.raises(ValueError, match=r"(?s)queries.jsonl, line 3: .*needs an image, a text, or both"):
        read_queries(queries)
    queries.write_text('{"query_id": "q1", "text": "a"}\n{"query_id": "q1", "text": "b"}\n')
    with pytest.raises(ValueError, match=r"repeated: \['q1'\]"):
        read_queries(queries)
    embeddings = tmp_path / "embeddings.npz"
    np.savez(embeddings, ids=np.array(["a", "b"]), emb_nd=np.array([[1.0, 0.0], [0.0, 0.0]]))
    with pytest.raises(ValueError, match=r"all-zero embeddings for \['b'\]"):
        read_embeddings(embeddings)
    np.savez(embeddings, emb_nd=np.ones((2, 2)))
    with pytest.raises(ValueError, match="missing \\['ids'\\]"):
        read_embeddings(embeddings)


def test_pools_fused_from_two_encoders_take_neighbours_of_both(
    clean: sessionmaker[Session], tmp_path: Path
) -> None:
    folder = _dataset_folder(tmp_path)
    # "alt" sees every query as the next blob: blob b's query lands among blob b + 1's images.
    corpus = np.load(folder / "index" / SETTINGS.encoder / "corpus.npz")
    emb_nd, ids = corpus["emb_nd"], corpus["ids"]
    alt_nd = emb_nd.copy()
    alt_nd[30:] = emb_nd[[10, 20, 0]]
    (folder / "index" / "alt").mkdir()
    np.savez(folder / "index" / "alt" / "corpus.npz", ids=ids, emb_nd=alt_nd)
    fused = PoolSettings(source="knn", k=10, encoders=[SETTINGS.encoder, "alt"])
    with clean.begin() as session:
        db = Database(session)
        dataset_id = DatasetService(db).add_folder(folder, None, None, None).id
        PipelineService(db).setup_study(
            SETTINGS.model_copy(update={"pool": fused}), dataset_id, "image", None, 0, []
        )
        for pool in db.studies.list_pools(1):
            blob = int(pool.query.external_id[1])
            blobs_seen = {int(m.image.external_id[1:]) // 10 for m in pool.members}
            assert len(pool.members) == 10 and blobs_seen == {blob, (blob + 1) % 3}


def test_random_pools_are_reproducible_and_never_given_candidates(
    clean: sessionmaker[Session], tmp_path: Path
) -> None:
    drawn = PoolSettings(source="random", k=7, seed=3)
    with clean.begin() as session:
        db = Database(session)
        dataset_id = DatasetService(db).add_folder(_dataset_folder(tmp_path), None, None, None).id
        pipeline = PipelineService(db)
        pipeline.setup_study(SETTINGS.model_copy(update={"pool": drawn}), dataset_id, "image", None, 0, [])
        first = [[m.image_id for m in p.members] for p in db.studies.list_pools(1)]
        pipeline.build_pools(1)
        assert [[m.image_id for m in p.members] for p in db.studies.list_pools(1)] == first
        corpus = set(db.datasets.corpus_ids(dataset_id))
        assert all(len(members) == 7 and set(members) <= corpus for members in first)
        assert len({tuple(members) for members in first}) == 3
        pipeline.setup_study(
            SETTINGS.model_copy(update={"name": "other seed", "pool": drawn.model_copy(update={"seed": 4})}),
            dataset_id,
            "image",
            None,
            0,
            [],
        )
        assert [[m.image_id for m in p.members] for p in db.studies.list_pools(2)] != first
    with pytest.raises(ValueError, match="pool.k is needed"):
        PoolSettings(source="random", k=None)
    with pytest.raises(ValueError, match="knn' only"):
        PoolSettings(source="file", k=None, encoders=["a", "b"])


def test_the_dashboard_creates_random_pools_and_checks_pooling_encoders(client: TestClient) -> None:
    root = login(client, "root")
    [toy] = client.get("/datasets", headers=root).json()
    body = {"name": "drawn", "dataset_id": toy["id"], "query_set": "default", "encoder": SETTINGS.encoder}
    created = client.post("/studies", json=body | {"pool": "random", "k": 5}, headers=root)
    assert created.status_code == 201
    assert created.json()["name"] == "drawn"
    assert created.json()["settings"]["pool"] | {"seed": 0} == {
        "source": "random",
        "k": 5,
        "max_size": 1000,
        "encoders": [],
        "seed": 0,
    }
    fused = body | {"name": "fused", "k": 6, "pool_encoders": ["missing"]}
    assert client.post("/studies", json=fused, headers=root).status_code == 422


def test_a_study_without_an_encoder_judges_one_image_at_a_time(
    client: TestClient, clean: sessionmaker[Session], tmp_path: Path
) -> None:
    root, bob = login(client, "root"), login(client, "bob")
    [toy] = client.get("/datasets", headers=root).json()
    body = {"name": "plain", "dataset_id": toy["id"], "query_set": "default", "annotators": ["bob"]}
    assert client.post("/studies", json=body | {"pool": "knn", "k": 5}, headers=root).status_code == 422
    created = client.post("/studies", json=body | {"pool": "file"}, headers=root).json()
    assert created["settings"]["encoder"] is None
    assert created["settings"]["grouping"]["method"] == "none"
    base = f"/studies/{created['id']}/queries/2"
    view = client.get(base, headers=bob).json()
    assert view["groups"] == [] and len(view["individual"]) == 12
    assert [m["score"] for m in view["individual"]] == sorted(
        (m["score"] for m in view["individual"]), reverse=True
    )
    one = [view["individual"][0]["member_id"]]
    two = [m["member_id"] for m in view["individual"][:2]]
    assert client.post(f"{base}/split", json={"member_ids": two}, headers=bob).status_code == 409
    assert client.get(f"{base}/similar", params={"to": one, "k": 3}, headers=bob).status_code == 409
    # Suggest mode can't be switched on without an encoder, so it is refused as off.
    assert client.get(f"{base}/suggestions", headers=bob).status_code == 403
    # A dataset without any embeddings still gets random pools.
    folder = _dataset_folder(tmp_path)
    shutil.rmtree(folder / "index")
    with clean.begin() as session:
        db = Database(session)
        dataset_id = DatasetService(db).add_folder(folder, None, None, None).id
        assert db.datasets.encoders(dataset_id) == {}
        study = PipelineService(db).new_study(
            "drawn", dataset_id, "image", None, 4, None, 0, True, [], [], pool="random"
        )
        pools = db.studies.list_pools(study.id)
        assert len(pools) == 3 and all(len(p.members) == 4 for p in pools)
        assert all(m.group_id is None for p in pools for m in p.members)


def test_settings_without_an_encoder_name_what_needs_one() -> None:
    plain = SETTINGS.model_dump() | {"encoder": None, "pool": {"source": "knn", "k": 5}}
    with pytest.raises(ValueError, match="grouping .*nearest-neighbour pools.*ordering by similarity"):
        StudySettings.model_validate(plain)
    StudySettings.model_validate(
        plain | {"pool": {"source": "random", "k": 5}, "grouping": {"method": "none"}, "order": "pool_rank"}
    )
