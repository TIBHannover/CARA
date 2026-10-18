"""Login, who sees which studies, and who may change which settings."""

from conftest import SETTINGS, login
from fastapi.testclient import TestClient


def test_login(client: TestClient) -> None:
    assert client.post("/auth/token", data={"username": "ann", "password": "no"}).status_code == 401
    assert client.get("/auth/me", headers=login(client, "ann")).json() == {
        "username": "ann",
        "is_superuser": False,
    }
    assert client.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_members_see_their_studies_only(client: TestClient) -> None:
    assert [p["role"] for p in client.get("/studies", headers=login(client, "ann")).json()] == ["annotator"]
    assert client.get("/studies", headers=login(client, "eve")).json() == []
    assert client.get("/studies/1", headers=login(client, "eve")).status_code == 403
    assert client.get("/studies/99", headers=login(client, "root")).status_code == 404


def test_only_admins_change_settings_and_labels_stay_fixed(client: TestClient) -> None:
    new = SETTINGS.model_copy(update={"top_k_individual": 5}).model_dump(mode="json")
    assert client.put("/studies/1/settings", json=new, headers=login(client, "ann")).status_code == 403
    response = client.put("/studies/1/settings", json=new, headers=login(client, "root"))
    assert response.json()["settings"]["top_k_individual"] == 5
    relabelled = {**new, "labels": [{"name": "a", "grade": 1, "colour": "x"}] * 2}
    assert (
        client.put("/studies/1/settings", json=relabelled, headers=login(client, "root")).status_code == 422
    )
    relabelled["labels"][1] = {"name": "b", "grade": 0, "colour": "x"}
    assert (
        client.put("/studies/1/settings", json=relabelled, headers=login(client, "root")).status_code == 409
    )


def test_label_colours_and_short_names_stay_editable(client: TestClient) -> None:
    new = SETTINGS.model_dump(mode="json")
    new["labels"][0] |= {"colour": "#123456", "short": "Y"}
    response = client.put("/studies/1/settings", json=new, headers=login(client, "root"))
    assert response.status_code == 200 and response.json()["settings"]["labels"][0]["short"] == "Y"
