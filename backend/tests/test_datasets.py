"""Datasets shared by studies, pooling rules, the first admin, the New study page, and file errors."""

import json
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
from cara.settings import PoolSettings


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
