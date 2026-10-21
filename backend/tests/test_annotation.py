"""What an annotator sees and does: groups, label precedence, locking, splits, review, Suggest mode."""

import pytest
from conftest import login
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cara.db.models import AssignmentRow
from cara.errors import Conflict
from cara.repositories.database import Database
from cara.services.pipeline import PipelineService


def _post(client: TestClient, headers: dict[str, str], ids: list[int], label: str | None, source: str) -> int:
    body = {"member_ids": ids, "label": label, "source": source}
    return client.post("/studies/1/queries/1/judgments", headers=headers, json=body).status_code


def _view(client: TestClient, user: str) -> dict:
    return client.get("/studies/1/queries/1", headers=login(client, user)).json()


def test_view_has_capped_groups_ordered_by_score(client: TestClient) -> None:
    view = _view(client, "ann")
    members = [m for g in view["groups"] for m in g["members"]] + view["individual"]
    assert len(members) == view["pool_size"] == 12
    assert all(len(g["members"]) <= 4 for g in view["groups"])
    means = [sum(m["score"] for m in g["members"]) / len(g["members"]) for g in view["groups"]]
    assert means == sorted(means, reverse=True)
    assert max(members, key=lambda m: m["score"])["doc_id"] == "d0"


def test_group_label_keeps_individual_and_review_labels(client: TestClient) -> None:
    headers = login(client, "ann")
    first = [m["member_id"] for m in _view(client, "ann")["groups"][0]["members"]]
    assert _post(client, headers, first, "no", "group") == 204
    _post(client, headers, first[:1], "yes", "item")
    _post(client, headers, first[1:2], "yes", "review")
    _post(client, headers, first, "no", "group")
    labels = {m["member_id"]: m["label"] for m in _view(client, "ann")["groups"][0]["members"]}
    assert [labels[m] for m in first[:3]] == ["yes", "yes", "no"]
    assert _view(client, "bob")["judged"] == 0
    assert _post(client, headers, [999], "no", "item") == 404
    assert _post(client, headers, first, "maybe", "item") == 404


def test_taking_a_group_label_back_keeps_individual_labels(client: TestClient) -> None:
    headers = login(client, "ann")
    first = [m["member_id"] for m in _view(client, "ann")["groups"][0]["members"]]
    _post(client, headers, first, "no", "group")
    _post(client, headers, first[:1], "yes", "item")
    assert _post(client, headers, first, None, "group") == 204
    labels = {m["member_id"]: m["label"] for m in _view(client, "ann")["groups"][0]["members"]}
    assert [labels[m] for m in first] == ["yes"] + [None] * (len(first) - 1)
    _post(client, headers, first[:1], None, "item")
    assert _view(client, "ann")["judged"] == 0


def test_first_judgment_locks_pools_and_grouping(client: TestClient, clean: sessionmaker[Session]) -> None:
    headers = login(client, "root")
    _post(client, login(client, "ann"), [1], "no", "item")
    study = client.get("/studies/1", headers=headers).json()
    assert study["locked"]
    changed = {**study["settings"], "grouping": {"method": "kmeans"}}
    assert client.put("/studies/1/settings", json=changed, headers=headers).status_code == 409
    example = {"member_id": 1, "image_id": 1, "label": "no", "note": "Only the frame matches."}
    guided = {**study["settings"], "guidelines": {"text": "Judge the object.", "examples": [example]}}
    assert client.put("/studies/1/settings", json=guided, headers=headers).status_code == 200
    with clean.begin() as session, pytest.raises(Conflict):
        PipelineService(Database(session)).cluster(1)


def test_split_and_review(client: TestClient) -> None:
    headers = login(client, "ann")
    view = _view(client, "ann")
    group = [m["member_id"] for m in view["groups"][0]["members"]]
    halves = client.post("/studies/1/queries/1/split", headers=headers, json={"member_ids": group}).json()
    assert len(halves) == 2 and sorted(halves[0] + halves[1]) == sorted(group)
    assert client.post("/studies/1/queries/1/review", headers=headers).status_code == 409
    every = [m["member_id"] for g in view["groups"] for m in g["members"]] + [
        m["member_id"] for m in view["individual"]
    ]
    _post(client, headers, every, "no", "group")
    assert client.post("/studies/1/queries/1/review", headers=headers).status_code == 204
    queue = client.get("/studies/1/queue", headers=headers).json()
    assert queue == [
        {
            "query_id": 1,
            "external_id": "q1",
            "pool_size": 12,
            "judged": 12,
            "reviewed": True,
            "is_pilot": False,
            "image_id": queue[0]["image_id"],
            "text": None,
        }
    ]


def test_assignments_restrict_the_queue(client: TestClient, clean: sessionmaker[Session]) -> None:
    with clean.begin() as session:
        session.add(AssignmentRow(user_id=2, query_id=1))
    assert len(client.get("/studies/1/queue", headers=login(client, "ann")).json()) == 1
    assert client.get("/studies/1/queue", headers=login(client, "bob")).json() == []
    assert client.get("/studies/1/queries/1", headers=login(client, "bob")).status_code == 403


def test_images_are_served_to_members_only(client: TestClient) -> None:
    response = client.get("/studies/1/images/1?size=64", headers=login(client, "ann"))
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert client.get("/studies/1/images/1?size=64", headers=login(client, "eve")).status_code == 403
    assert client.get("/studies/1/images/999?size=64", headers=login(client, "ann")).status_code == 404


def test_splits_survive_a_new_session(client: TestClient) -> None:
    headers = login(client, "ann")
    first = _view(client, "ann")["groups"][0]
    group = [m["member_id"] for m in first["members"]]
    halves = client.post("/studies/1/queries/1/split", headers=headers, json={"member_ids": group}).json()
    again = [[m["member_id"] for m in g["members"]] for g in _view(client, "ann")["groups"]]
    assert again[:2] == halves
    assert [[m["member_id"] for m in g["members"]] for g in _view(client, "bob")["groups"]][0] == group


def test_item_label_after_group_label_wins(client: TestClient) -> None:
    headers = login(client, "ann")
    first = [m["member_id"] for m in _view(client, "ann")["groups"][0]["members"]]
    _post(client, headers, first, "no", "group")
    _post(client, headers, first[:1], "yes", "item")
    labels = {m["member_id"]: m["label"] for m in _view(client, "ann")["groups"][0]["members"]}
    assert [labels[m] for m in first] == ["yes"] + ["no"] * (len(first) - 1)


def test_undo_split_merges_back_in_reverse_order(client: TestClient) -> None:
    headers = login(client, "ann")

    def groups() -> list[list[int]]:
        return [[m["member_id"] for m in g["members"]] for g in _view(client, "ann")["groups"]]

    def undo() -> int:
        return client.post("/studies/1/queries/1/split/undo", headers=headers).status_code

    original = groups()
    halves = client.post(
        "/studies/1/queries/1/split", headers=headers, json={"member_ids": original[0]}
    ).json()
    client.post("/studies/1/queries/1/split", headers=headers, json={"member_ids": halves[0]})
    assert len(groups()) == len(original) + 2 and _view(client, "ann")["undoable_splits"] == 2
    assert undo() == 200 and groups()[:2] == halves
    assert undo() == 200 and groups() == original
    assert undo() == 409 and _view(client, "ann")["undoable_splits"] == 0


def test_similar_images_are_ranked_by_their_closest_reference(client: TestClient) -> None:
    ann = login(client, "ann")
    view = client.get("/studies/1/queries/1", headers=ann).json()
    members = [m["member_id"] for g in view["groups"] for m in g["members"]]
    members += [m["member_id"] for m in view["individual"]]
    url = "/studies/1/queries/1/similar"
    one = client.get(url, params={"to": members[0], "k": 5}, headers=ann).json()
    assert len(one) == 5 and members[0] not in one
    several = client.get(url, params={"to": members[:3], "k": 50}, headers=ann).json()
    assert set(several) == set(members) - set(members[:3])
    assert client.get(url, params={"to": 999999}, headers=ann).status_code == 404
    study = client.get("/studies/1", headers=login(client, "root")).json()
    assert 1 <= len(study["cover_image_ids"]) <= 4


def test_suggestions_cluster_unjudged_images_around_the_seeds(client: TestClient) -> None:
    root, ann = login(client, "root"), login(client, "ann")
    url = "/studies/1/queries/1/suggestions"
    assert client.get(url, headers=ann).status_code == 403  # off by default
    settings = client.get("/studies/1", headers=root).json()["settings"]
    settings["suggest"] = {"enabled": True, "min_seeds": 1, "min_margin": 0.0}
    assert client.put("/studies/1/settings", json=settings, headers=root).status_code == 200
    view = client.get("/studies/1/queries/1", headers=ann).json()
    members = {m["doc_id"]: m["member_id"] for g in view["groups"] for m in g["members"]}
    members |= {m["doc_id"]: m["member_id"] for m in view["individual"]}

    def mark(doc_id: str, label: str) -> None:
        body = {"member_ids": [members[doc_id]], "label": label, "source": "item"}
        client.post("/studies/1/queries/1/judgments", json=body, headers=ann)

    assert not client.get(url, headers=ann).json()["ready"]
    # One Not Relevant image is enough to start; without a Relevant one, nothing is suggested Relevant.
    mark("d2", "no")
    found = client.get(url, headers=ann).json()
    assert found["ready"] and found["relevant_seeds"] == 0
    assert {c["label"] for c in found["clusters"]} <= {"no", None}
    mark("d0", "yes")
    clusters = client.get(url, headers=ann).json()["clusters"]
    assert {c["label"] for c in clusters} <= {"yes", "no", None}
    everyone = sorted(m for c in clusters for m in c["members"])
    assert everyone == sorted(set(members.values()) - {members["d0"], members["d2"]})
    first = next(c for c in clusters if c["label"])
    accept = {"member_ids": first["members"], "label": first["label"], "source": "suggestion"}
    assert client.post("/studies/1/queries/1/judgments", json=accept, headers=ann).status_code == 204
    left = client.get(url, headers=ann).json()["clusters"]
    assert not set(first["members"]) & {m for c in left for m in c["members"]}
