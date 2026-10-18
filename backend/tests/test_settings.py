"""Study settings validation and the server's environment settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cara.config import app_settings
from cara.settings import StudySettings

LABELS = [
    {"name": "Relevant", "grade": 1, "colour": "#2ecc71"},
    {"name": "Not Relevant", "grade": 0, "colour": "#e74c3c"},
    {"name": "Unsure", "grade": None, "colour": "#f1c40f"},
]


def settings(**unsure: object) -> StudySettings:
    labels = [*LABELS[:2], LABELS[2] | unsure]
    return StudySettings.model_validate({"name": "p", "encoder": "pixels", "labels": labels})


def test_only_labels_without_a_grade_can_be_switched_off() -> None:
    assert not settings(offered=False).labels[2].offered
    with pytest.raises(ValidationError, match="only labels without a grade"):
        StudySettings.model_validate(
            {"name": "p", "encoder": "pixels", "labels": [LABELS[0] | {"offered": False}, *LABELS[1:]]}
        )


def test_missing_environment_variables_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARA_DATABASE_URL", "postgresql+psycopg://x")
    monkeypatch.delenv("CARA_IMAGE_ROOT", raising=False)
    monkeypatch.setenv("CARA_SECRET_KEY", "")
    with pytest.raises(ValueError, match="CARA_IMAGE_ROOT, CARA_SECRET_KEY not set"):
        app_settings()


def test_a_bad_settings_file_is_named(tmp_path: Path) -> None:
    path = tmp_path / "study.yaml"
    path.write_text("name: x\nencoder: e\nlabels: []\n")
    with pytest.raises(ValueError, match="study.yaml: invalid study settings"):
        StudySettings.from_yaml(path)
