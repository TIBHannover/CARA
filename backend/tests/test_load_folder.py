"""`cara load`: a folder becomes a dataset and a study ready to judge."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from cara.errors import Conflict
from cara.repositories.database import Database
from cara.services.pipeline import PipelineService

TOY = Path(__file__).parents[2] / "data" / "toy"


def test_a_folder_loads_as_a_dataset_and_a_study_ready_to_judge(clean: sessionmaker[Session]) -> None:
    with clean.begin() as session:
        db = Database(session)
        study = PipelineService(db).load_folder(TOY, "toy", [])
        assert [d.name for d in db.datasets.list_all()] == ["Toy shapes"]
        assert len(db.studies.list_pools(study.id)) == 3
        with pytest.raises(Conflict, match="study 'Toy shapes' already exists"):
            PipelineService(db).load_folder(TOY, "toy", [])
