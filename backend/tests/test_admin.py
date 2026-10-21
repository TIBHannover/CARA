"""The study admin's work: progress, agreement, adjudication, exports, team, stages, pilot and assignments."""

import json

from conftest import login
from fastapi.testclient import TestClient


def _judge_all(client: TestClient, user: str, positives: set[str]) -> None:
    headers = login(client, user)
    view = client.get("/studies/1/queries/1", headers=headers).json()
    members = [m for g in view["groups"] for m in g["members"]] + view["individual"]
    for member in members:
        label = "yes" if member["doc_id"] in positives else "no"
        body = {"member_ids": [member["member_id"]], "label": label, "source": "item"}
        client.post("/studies/1/queries/1/judgments", json=body, headers=headers)


def test_progress_agreement_adjudication_and_exports(client: TestClient) -> None:
    root = login(client, "root")
    assert client.put("/studies/1/assignments", json={"per_query": 2}, headers=root).json() == {
        "ann": 1,
        "bob": 1,
    }
    assert client.put("/studies/1/assignments", json={"per_query": 3}, headers=root).status_code == 422
    _judge_all(client, "ann", {"d0"})
    _judge_all(client, "bob", {"d0", "d1"})

    progress = {row["username"]: row for row in client.get("/studies/1/admin/progress", headers=root).json()}
    assert progress["ann"]["complete"] == 1 and progress["ann"]["judgments"] == 12

    report = client.get("/studies/1/adjudication/agreement", headers=root).json()
    assert report["items_with_two_or_more"] == 12 and report["pairs"][0]["shared_items"] == 12
    assert sum(report["label_counts"].values()) == 24
    assert report["queries"][0]["disagreements"] == 1

    items = client.get("/studies/1/adjudication/items/1", headers=root).json()
    assert len(items) == 12
    differ = [(i["doc_id"], i["labels"]) for i in items if len(set(i["labels"].values())) > 1]
    assert differ == [("d1", {"ann": "no", "bob": "yes"})]
    d1 = next(i for i in items if i["doc_id"] == "d1")
    body = {"member_id": d1["member_id"], "label": "yes"}
    assert client.put("/studies/1/adjudication/final-labels", json=body, headers=root).status_code == 204

    def export(name: str, **params: str) -> str:
        response = client.get(f"/studies/1/admin/exports/{name}", params=params, headers=root)
        response.raise_for_status()
        return response.text

    assert "q1 0 d1 1" in export("consensus_qrels") and "q1 0 d1 0" in export("qrels", username="ann")
    assert json.loads(export("pairs"))["positives"] == ["d0", "d1"]
    first_action = json.loads(export("actions").splitlines()[0])
    assert first_action["username"] in {"ann", "bob"} and first_action["kind"] == "label"
    assert client.get("/studies/1/admin/exports/qrels", headers=root).status_code == 422


def test_team_management_is_for_admins(client: TestClient) -> None:
    root, ann = login(client, "root"), login(client, "ann")
    assert client.get("/studies/1/members", headers=ann).status_code == 403
    assert (
        client.post("/users", json={"username": "new", "password": "secret"}, headers=ann).status_code == 403
    )
    assert (
        client.post("/users", json={"username": "new", "password": "secret"}, headers=root).status_code == 204
    )
    client.put("/studies/1/members", json={"username": "new", "role": "admin"}, headers=root)
    members = {m["username"]: m["role"] for m in client.get("/studies/1/members", headers=root).json()}
    assert members == {"ann": "annotator", "bob": "annotator", "new": "admin"}


def test_regroup_follows_new_settings_until_judging_starts(client: TestClient) -> None:
    root = login(client, "root")
    settings = client.get("/studies/1", headers=root).json()["settings"]
    settings["grouping"] = {"method": "none"}
    assert client.put("/studies/1/settings", json=settings, headers=root).status_code == 200
    assert client.post("/studies/1/groups", headers=root).status_code == 204
    assert client.get("/studies/1/queries/1", headers=login(client, "ann")).json()["groups"] == []
    assert client.post("/studies/1/pools", headers=root).status_code == 409
    assert client.post("/studies/1/groups", headers=login(client, "ann")).status_code == 403


def test_stage_follows_assignments_and_judgments(client: TestClient) -> None:
    root = login(client, "root")

    def overview() -> dict:
        return client.get("/studies/1", headers=root).json()["overview"]

    assert overview() == {
        "stage": "new",
        "pilot_queries": 0,
        "pilot_judged": 0,
        "annotation_queries": 1,
        "annotation_assignments": 0,
        "annotation_complete": 0,
    }
    assert client.get("/studies/1", headers=login(client, "ann")).json()["overview"] is None
    client.put("/studies/1/assignments", json={"per_query": 2}, headers=root)
    assert overview()["stage"] == "annotation" and overview()["annotation_assignments"] == 2
    _judge_all(client, "ann", {"d0"})
    assert overview()["annotation_complete"] == 1 and overview()["stage"] == "annotation"
    _judge_all(client, "bob", {"d0"})
    assert overview()["stage"] == "done"


def test_assigning_the_study_keeps_the_pilot_assignments(client: TestClient) -> None:
    root = login(client, "root")
    pilot = {"count": 1, "annotators": ["ann", "bob"], "per_query": 2}
    assert client.put("/studies/1/pilot", json=pilot, headers=root).json()["assigned"] == {
        "ann": 1,
        "bob": 1,
    }
    assert client.put("/studies/1/pilot", json={"annotators": ["eve"]}, headers=root).status_code == 422
    # The only query is a pilot query: the study has nothing to assign, and the pilot keeps its annotators.
    body = {"per_query": 1, "annotators": ["bob"]}
    assert client.put("/studies/1/assignments", json=body, headers=root).json() == {"ann": 1, "bob": 1}
    assert client.get("/studies/1", headers=root).json()["overview"]["stage"] == "pilot"


def test_admins_manage_and_annotators_judge(client: TestClient) -> None:
    root = login(client, "root")
    body = {"member_ids": [1], "label": "no", "source": "item"}
    assert client.post("/studies/1/queries/1/judgments", json=body, headers=root).status_code == 403
    assert client.get("/studies/1/queue", headers=root).status_code == 403
    assert client.get("/studies/1/images/1?size=64", headers=root).status_code == 200


def test_adjudicators_set_final_labels_but_do_not_manage(client: TestClient) -> None:
    root = login(client, "root")
    assert client.put(
        "/studies/1/members", json={"username": "bob", "role": "adjudicator"}, headers=root
    ).is_success
    _judge_all(client, "ann", {"d0"})
    bob = login(client, "bob")
    report = client.get("/studies/1/adjudication/agreement", headers=bob).json()
    assert report["queries"][0]["annotators"] == 1 and report["queries"][0]["unsure"] == 0
    item = client.get("/studies/1/adjudication/items/1", headers=bob).json()[0]
    body = {"member_id": item["member_id"], "label": "yes"}
    assert client.put("/studies/1/adjudication/final-labels", json=body, headers=bob).status_code == 204
    body["label"] = None
    assert client.put("/studies/1/adjudication/final-labels", json=body, headers=bob).status_code == 204
    assert client.get("/studies/1/admin/progress", headers=bob).status_code == 403
    assert client.get("/studies/1/adjudication/agreement", headers=login(client, "ann")).status_code == 403


def test_the_pilot_is_fixed_once_the_study_has_assignments(client: TestClient) -> None:
    root = login(client, "root")
    assert client.put("/studies/1/assignments", json={"per_query": 1}, headers=root).status_code == 200
    # The only query is a study query now; choosing it as pilot is refused once any study query is assigned.
    response = client.put("/studies/1/pilot", json={"count": 1, "annotators": ["ann"]}, headers=root)
    assert response.status_code == 409
