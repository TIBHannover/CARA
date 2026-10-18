"""Datasets, for the New study page."""

from dataclasses import asdict

from fastapi import APIRouter, Depends

from cara.api.auth import require_superuser
from cara.api.deps import DatasetsDep
from cara.api.schemas import DatasetOut, QuerySetOut

router = APIRouter(prefix="/datasets", tags=["datasets"], dependencies=[Depends(require_superuser)])


@router.get("")
def list_datasets(datasets: DatasetsDep) -> list[DatasetOut]:
    """Return every dataset with its query sets, encoders, and how many studies use it."""
    return [
        DatasetOut(
            id=summary.id,
            name=summary.name,
            description=summary.description,
            images=summary.images,
            query_sets=summary.query_sets,
            encoders=summary.encoders,
            studies=summary.studies,
            sets=[QuerySetOut(**asdict(info)) for info in datasets.query_sets(summary.id)],
        )
        for summary in datasets.summaries()
    ]
