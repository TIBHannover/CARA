"""The app's simulator and pilot report: ground truths, annotator profiles, the event stream, pilot timing."""

import json
from pathlib import Path

import pytest
from conftest import login
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cara.core.pilot import Action, annotator_stats
from cara.repositories.database import Database
from cara.services.admin import AdminService
from cara.services.annotation import AnnotationService
from cara.services.pipeline import PipelineService
from cara.services.users import UserService

QRELS = "q1 0 d0 1\nq1 0 d1 1\nq1 0 d2 0\n"
Result = dict[str, object]


def _simulate(client: TestClient, user: str, **body: object) -> tuple[int, list[Result]]:
    response = client.post("/studies/1/simulator", json=body, headers=login(client, user))
    return response.status_code, response.json()


def _result(results: list[Result], strategy: str) -> Result:
    return next(result for result in results if result["strategy"] == strategy)


def _typical(result: Result) -> dict[str, object]:
    annotators = result["annotators"]
    assert isinstance(annotators, list)
    first: dict[str, object] = annotators[0]
    return first


def test_without_labels_only_structure_is_reported(client: TestClient) -> None:
    assert _simulate(client, "ann", source="none")[0] == 403
    status, results = _simulate(client, "root", source="none")
    baseline = _result(results, "one at a time")
    assert status == 200 and baseline["min_actions_pc"] == 1.0 and baseline["actions_pc"] is None
    assert not any(_typical(result)["best_tradeoff"] for result in results)
    assert sum(bool(result["is_current"]) for result in results) >= 1


def test_qrels_give_effort_recall_and_one_best_tradeoff(client: TestClient) -> None:
    status, results = _simulate(client, "root", source="qrels", qrels=QRELS)
    assert status == 200
    assert _result(results, "one at a time")["actions_pc"] == 1.0
    grouped = next(
        r for r in results if str(r["strategy"]).startswith("agglomerative (average), groups of up to 8")
    )
    assert grouped["actions_pc"] < 1.0 and _typical(grouped)["recall"] is not None  # type: ignore[operator]
    assert sum(bool(_typical(result)["best_tradeoff"]) for result in results) == 1
    assert _simulate(client, "root", source="qrels", qrels="other 0 d0 1\n")[0] == 422
    assert _simulate(client, "root", source="qrels", qrels="broken line\n")[0] == 422


def test_pilot_queries_are_judged_singly_and_do_not_lock(
    client: TestClient, clean: sessionmaker[Session]
) -> None:
    root, ann = login(client, "root"), login(client, "ann")
    assert _simulate(client, "root", source="pilot")[0] == 422
    assert client.put("/studies/1/pilot", json={"count": 1}, headers=root).json() == {
        "queries": ["q1"],
        "assigned": {},
    }
    assert client.put("/studies/1/pilot", json={"count": 5}, headers=root).status_code == 422
    # Once there is a pilot, annotators see only what is assigned to them.
    assert client.get("/studies/1/queries/1", headers=ann).status_code == 403
    assigned = client.put("/studies/1/pilot", json={"annotators": ["ann"]}, headers=root).json()["assigned"]
    assert assigned == {"ann": 1}
    view = client.get("/studies/1/queries/1", headers=ann).json()
    assert view["is_pilot"] and view["groups"] == [] and len(view["individual"]) == 12
    for member in view["individual"]:
        label = "yes" if member["doc_id"] in {"d0", "d1"} else "no"
        body = {"member_ids": [member["member_id"]], "label": label, "source": "item"}
        client.post("/studies/1/queries/1/judgments", json=body, headers=ann)
    assert not client.get("/studies/1", headers=root).json()["locked"]
    status, results = _simulate(client, "root", source="pilot")
    assert status == 200 and _typical(_result(results, "one at a time"))["recall"] is not None
    assert client.put("/studies/1/pilot", json={"count": 1}, headers=root).status_code == 409
    with clean.begin() as session:
        PipelineService(Database(session)).cluster(1)


def test_stream_reports_each_step_and_ends_with_the_results(client: TestClient) -> None:
    def stream(**body: object) -> list[dict[str, object]]:
        response = client.post("/studies/1/simulator/stream", json=body, headers=login(client, "root"))
        assert response.status_code == 200
        return [json.loads(line) for line in response.text.splitlines() if line]

    events = stream(source="qrels", qrels=QRELS)
    assert [e["step"] for e in events][0] == "labels" and events[-1]["step"] == "compare"
    assert {"labels", "embeddings", "replay", "compare"} <= {e["step"] for e in events}
    assert all(0 <= e["done"] <= e["total"] for e in events)  # type: ignore[operator]
    results = events[-1]["results"]
    assert isinstance(results, list) and sum(bool(_typical(r)["best_tradeoff"]) for r in results) == 1
    failed = stream(source="pilot")
    assert failed[-1]["step"] == "error" and "pilot" in str(failed[-1]["message"])


def test_the_admin_chooses_the_candidate_settings(client: TestClient) -> None:
    plan = {
        "agglomerative": {"linkage": ["average", "complete"], "max_size": [4]},
        "kmeans": {"n_groups": [2], "max_size": [6]},
        "hdbscan": None,
        "solo_percentile": [0],
        "top_k_individual": [0],
    }
    status, results = _simulate(client, "root", source="qrels", qrels=QRELS, plan=plan)
    names = [str(result["strategy"]) for result in results]
    assert status == 200 and "one at a time" in names
    assert "agglomerative (complete), groups of up to 4" in names
    assert "k-means k=2, groups of up to 6" in names
    assert sum(name.startswith("current: ") for name in names) == 1 and len(names) == 5
    too_many = plan | {"agglomerative": {"linkage": ["average"], "max_size": list(range(2, 70))}}
    assert _simulate(client, "root", source="none", plan=too_many)[0] == 422
    scope = client.get("/studies/1/simulator/scope", headers=login(client, "root")).json()
    assert scope["queries"] == 1 and scope["images"] == 12 and scope["labelled_pilot_queries"] == 0


def test_several_annotator_profiles_are_simulated_side_by_side(client: TestClient) -> None:
    exact = {"kind": "realistic", "acc_relevant": 1.0, "acc_nonrelevant": 1.0}
    plan = {
        "annotators": [
            {"name": "Expert", "model": exact, "time": {"single_s": 5.0}},
            {"name": "Slow expert", "model": exact, "time": {"single_s": 10.0}},
            {"name": "Novice", "model": {"kind": "realistic", "acc_relevant": 0.6}},
        ]
    }
    status, results = _simulate(client, "root", source="qrels", qrels=QRELS, plan=plan)
    annotators = _result(results, "one at a time")["annotators"]
    assert status == 200 and isinstance(annotators, list)
    expert, slow, novice = annotators
    assert [a["name"] for a in annotators] == ["Expert", "Slow expert", "Novice"]
    assert expert["recall"] == 1.0 and novice["recall"] < 1.0
    assert slow["seconds_pc"] == pytest.approx(2 * expert["seconds_pc"], rel=0.05)
    assert all(sum(bool(r["annotators"][i]["best_tradeoff"]) for r in results) == 1 for i in range(3))  # type: ignore[index]
    same_names = {"annotators": [{"name": "A"}, {"name": "A"}]}
    assert _simulate(client, "root", source="none", plan=same_names)[0] == 422
    six = {"annotators": [{"name": str(i)} for i in range(6)]}
    assert _simulate(client, "root", source="none", plan=six)[0] == 422


def test_perfect_and_careless_annotators_are_profiles_too(client: TestClient) -> None:
    plan = {
        "annotators": [
            {"name": "Perfect", "model": {"kind": "perfect"}},
            {"name": "Careless", "model": {"kind": "rubber_stamp"}},
            {"name": "Typical"},
        ]
    }
    status, results = _simulate(client, "root", source="qrels", qrels=QRELS, plan=plan)
    assert status == 200
    for result in results:
        perfect, careless, _ = result["annotators"]  # type: ignore[misc]
        assert perfect["recall"] == 1.0 and careless["recall"] == result["recall_uncorrected"]


def test_minimum_time_per_profile_needs_no_labels(client: TestClient) -> None:
    plan = {
        "annotators": [
            {"name": "Fast", "time": {"single_s": 4.0}},
            {"name": "Slow", "time": {"single_s": 8.0}},
        ]
    }
    status, results = _simulate(client, "root", source="none", plan=plan)
    fast, slow = _result(results, "one at a time")["annotators"]  # type: ignore[misc]
    assert status == 200 and fast["seconds_pc"] is None and fast["recall"] is None
    assert fast["min_seconds_pc"] == pytest.approx(4.0) and slow["min_seconds_pc"] == pytest.approx(8.0)
    assert all(a["min_seconds_pc"] is not None for r in results for a in r["annotators"])  # type: ignore[attr-defined]
    _, labelled = _simulate(client, "root", source="qrels", qrels=QRELS)
    assert all(
        a["min_seconds_pc"] <= a["seconds_pc"] + 1e-9
        for r in labelled
        for a in r["annotators"]  # type: ignore[attr-defined]
    )


def test_a_pilot_study_can_be_recorded_from_qrels(client: TestClient, clean: sessionmaker[Session]) -> None:
    with clean.begin() as session:
        db = Database(session)
        users, annotation = UserService(db), AnnotationService(db)
        assert PipelineService(db).set_pilot(1, 1, 0, among={"q1"}) == ["q1"]
        assert AdminService(db).assign_pilot(1, ["ann"], 1) == {"ann": 1}
        assert annotation.judge_from_labels(users.get("ann"), 1, {"q1": {"d0", "d1"}}, {1}) == 12
        assert annotation.queue(users.get("bob"), 1) == []
    assert not client.get("/studies/1", headers=login(client, "root")).json()["locked"]
    status, results = _simulate(client, "root", source="pilot")
    assert status == 200 and _typical(_result(results, "one at a time"))["recall"] is not None
    with clean.begin() as session:
        PipelineService(Database(session)).cluster(1)


def test_the_sample_qrels_shipped_with_a_study_can_be_downloaded(client: TestClient, tmp_path: Path) -> None:
    url, root = "/studies/1/simulator/sample-qrels", login(client, "root")
    assert client.get(url, headers=root).status_code == 404
    (tmp_path / "toy" / "sample.qrels").write_text(QRELS)
    assert client.get(url, headers=root).text == QRELS
    assert client.get(url, headers=login(client, "ann")).status_code == 403


def test_only_the_chosen_pilot_annotators_labels_count(client: TestClient) -> None:
    root = login(client, "root")
    client.put(
        "/studies/1/pilot", json={"count": 1, "annotators": ["ann", "bob"], "per_query": 2}, headers=root
    )
    for user, positives in (("ann", {"d0", "d1"}), ("bob", {"d0"})):
        headers = login(client, user)
        view = client.get("/studies/1/queries/1", headers=headers).json()
        for member in view["individual"]:
            label = "yes" if member["doc_id"] in positives else "no"
            body = {"member_ids": [member["member_id"]], "label": label, "source": "item"}
            client.post("/studies/1/queries/1/judgments", json=body, headers=headers)
    scope = client.get("/studies/1/simulator/scope", headers=root).json()
    # The two disagree on d1, so their consensus leaves it undecided: no pilot query is fully labelled.
    assert scope["labelled_pilot_queries"] == 0
    assert [(a["username"], a["judged"]) for a in scope["pilot_annotators"]] == [("ann", 1), ("bob", 1)]
    assert all(a["kappa"] is not None and a["kappa"] < 1 for a in scope["pilot_annotators"])
    only_ann = client.get("/studies/1/simulator/scope", params={"pilot_users": ["ann"]}, headers=root).json()
    assert only_ann["labelled_pilot_queries"] == 1
    assert _simulate(client, "root", source="pilot")[0] == 422
    status, results = _simulate(client, "root", source="pilot", pilot_users=["ann"])
    assert status == 200 and _typical(_result(results, "one at a time"))["recall"] is not None


def test_the_pilot_report_measures_each_annotator_against_the_others(client: TestClient) -> None:
    root = login(client, "root")
    client.put(
        "/studies/1/pilot", json={"count": 1, "annotators": ["ann", "bob"], "per_query": 2}, headers=root
    )
    for user, positives in (("ann", {"d0", "d1"}), ("bob", {"d0"})):
        headers = login(client, user)
        view = client.get("/studies/1/queries/1", headers=headers).json()
        for member in view["individual"]:
            if user == "ann" and member["doc_id"] == "d2":  # a slip, corrected below
                body = {"member_ids": [member["member_id"]], "label": "yes", "source": "item"}
                client.post("/studies/1/queries/1/judgments", json=body, headers=headers)
            label = "yes" if member["doc_id"] in positives else "no"
            body = {"member_ids": [member["member_id"]], "label": label, "source": "item"}
            client.post("/studies/1/queries/1/judgments", json=body, headers=headers)
    report = client.get("/studies/1/pilot/report", headers=root).json()
    assert report["pilot_queries"] == 1 and report["alpha"] is not None
    ann, bob = report["annotators"]
    assert (ann["username"], ann["queries_judged"], ann["images"], ann["corrections"]) == ("ann", 1, 12, 1)
    # Against bob, ann found his one Relevant image and called 1 of his 11 Not Relevant ones Relevant.
    assert (ann["acc_relevant"], ann["acc_nonrelevant"], ann["compared"]) == (1.0, 10 / 11, 12)
    assert (bob["acc_relevant"], bob["acc_nonrelevant"], bob["corrections"]) == (0.5, 1.0, 0)
    assert client.get("/studies/1/pilot/report", headers=login(client, "ann")).status_code == 403


def test_pilot_timing_skips_breaks_and_times_single_images() -> None:
    def act(time: float, label: str | None = "yes", n: int = 1) -> Action:
        return Action("ann", time, label, tuple(("q", f"d{i}") for i in range(n)))

    actions = [act(0), act(4), act(10, None), act(2000), act(2006, n=3), act(2008)]
    (stats,) = annotator_stats(actions, {"ann": {("q", "d0"): "yes"}}, {"q": 1}, {"yes": 1})
    # Gaps 4, 6, 6, 2 (the 1990 s break is left out); single-image labels follow gaps 4 and 2.
    assert stats.seconds_per_image == 3 and stats.active_minutes == 18 / 60
    scripted = [act(i * 0.01) for i in range(5)]
    (stats,) = annotator_stats(scripted, {"ann": {("q", "d0"): "yes"}}, {"q": 1}, {"yes": 1})
    assert stats.seconds_per_image is None
