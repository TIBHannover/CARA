"""Shared fixtures: a Postgres test database (`CARA_TEST_DATABASE_URL`), emptied after each test, and a toy
study behind a test client."""

import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from cara.db.models import Base, Role
from cara.grouping.agglomerative import Agglomerative
from cara.inputs import CorpusItem, QueryIn
from cara.repositories.database import Database
from cara.services.datasets import DatasetService
from cara.services.pipeline import PipelineService
from cara.services.studies import StudyService
from cara.services.users import UserService
from cara.settings import Label, PoolSettings, StudySettings

TEST_DATABASE_URL = os.environ.get(
    "CARA_TEST_DATABASE_URL", "postgresql+psycopg://cara:cara@localhost:5432/cara_test"
)


def blobs(seed: int = 0, n_blobs: int = 5, per_blob: int = 30) -> npt.NDArray[np.float32]:
    """Return unit-length embeddings in tight, well-separated clusters, `per_blob` rows each, in order."""
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(n_blobs, 32))
    emb = np.concatenate([centre + 0.05 * rng.normal(size=(per_blob, 32)) for centre in centres])
    return (emb / np.linalg.norm(emb, axis=1, keepdims=True)).astype(np.float32)


@pytest.fixture(scope="session")
def sessions() -> Iterator[sessionmaker[Session]]:
    """Create the schema in the test database once per run (with pgvector) and yield a session factory."""
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def clean(sessions: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield the session factory, then empty every table, so each test starts from an empty database."""
    yield sessions
    with sessions.begin() as session:
        tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
        session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


SETTINGS = StudySettings(
    name="toy",
    encoder="test",
    labels=[Label(name="yes", grade=1, colour="#0f0"), Label(name="no", grade=0, colour="#f00")],
    pool=PoolSettings(source="file", k=None),
    grouping=Agglomerative(method="agglomerative", max_size=4),
)
"""The toy study's settings: two labels, given pools, groups of at most four."""


@pytest.fixture
def client(clean: sessionmaker[Session], tmp_path: Path) -> Iterator[TestClient]:
    """Yield an API client on a toy study: one query, 12 images in two blobs, annotators ann and bob.

    Accounts: root (superuser), ann, bob and eve, all with password `pw`; eve is in no study.
    """
    emb = blobs(n_blobs=2, per_blob=6)
    paths = [f"img/{i}.png" for i in range(len(emb) + 1)]
    (tmp_path / "toy" / "img").mkdir(parents=True)
    for path in paths:
        Image.new("RGB", (40, 30), "white").save(tmp_path / "toy" / path)
    query = QueryIn(
        query_id="q1",
        image=paths[-1],
        candidates=[CorpusItem(doc_id=f"d{i}", image=p) for i, p in enumerate(paths[:-1])],
    )
    with clean.begin() as session:
        db = Database(session)
        users, datasets, pipeline = UserService(db), DatasetService(db), PipelineService(db)
        users.add("root", "pw", is_superuser=True)
        for name in ("ann", "bob", "eve"):
            users.add(name, "pw")
        dataset = datasets.add("toy", "toy")
        datasets.ingest(dataset.id, "default", [query], [])
        datasets.load_embeddings(dataset.id, SETTINGS.encoder, paths, np.concatenate([emb, emb[:1]]))
        study = StudyService(db).create(SETTINGS, dataset.id, "default")
        users.set_role(study.id, "ann", Role.ANNOTATOR)
        users.set_role(study.id, "bob", Role.ANNOTATOR)
        pipeline.add_queries(study.id, None, 0)
        pipeline.cluster(study.id)
    os.environ.update(
        CARA_DATABASE_URL=TEST_DATABASE_URL,
        CARA_IMAGE_ROOT=str(tmp_path),
        CARA_SECRET_KEY="test-secret-of-at-least-32-bytes!!",
    )
    from cara.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> dict[str, str]:
    """Log in as `username` and return the authorization header."""
    response = client.post("/auth/token", data={"username": username, "password": "pw"})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
