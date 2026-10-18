"""The API's dependencies: settings, one transaction per request, the image store, and the services."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from cara.config import AppSettings
from cara.repositories.database import Database
from cara.repositories.image_store import ImageStore
from cara.services.admin import AdminService
from cara.services.annotation import AnnotationService
from cara.services.datasets import DatasetService
from cara.services.images import ImageService
from cara.services.pipeline import PipelineService
from cara.services.similarity import SimilarityService
from cara.services.simulator import SimulatorService
from cara.services.studies import StudyService
from cara.services.users import UserService


def get_app_settings(request: Request) -> AppSettings:
    """Return the settings read at startup."""
    settings: AppSettings = request.app.state.settings
    return settings


def get_database(request: Request) -> Iterator[Database]:
    """Open one transaction for the request; it commits when the route returns, or rolls back on an error."""
    with request.app.state.sessions.begin() as session:
        yield Database(session)


def get_image_store(request: Request) -> ImageStore:
    """Return the image store made at startup, so its thumbnail cache is shared by every request."""
    store: ImageStore = request.app.state.image_store
    return store


AppSettingsDep = Annotated[AppSettings, Depends(get_app_settings)]
DatabaseDep = Annotated[Database, Depends(get_database, scope="function")]
ImageStoreDep = Annotated[ImageStore, Depends(get_image_store)]


def get_users(db: DatabaseDep) -> UserService:
    """Return the account service on the request's transaction."""
    return UserService(db)


def get_studies(db: DatabaseDep) -> StudyService:
    """Return the study service on the request's transaction."""
    return StudyService(db)


def get_datasets(db: DatabaseDep) -> DatasetService:
    """Return the dataset service on the request's transaction."""
    return DatasetService(db)


def get_pipeline(db: DatabaseDep) -> PipelineService:
    """Return the pool and query service on the request's transaction."""
    return PipelineService(db)


def get_admin(db: DatabaseDep) -> AdminService:
    """Return the study admin service on the request's transaction."""
    return AdminService(db)


def get_annotation(db: DatabaseDep) -> AnnotationService:
    """Return the annotation service on the request's transaction."""
    return AnnotationService(db)


def get_similarity(db: DatabaseDep) -> SimilarityService:
    """Return the similar-images and Suggest mode service on the request's transaction."""
    return SimilarityService(db)


def get_images(db: DatabaseDep, store: ImageStoreDep) -> ImageService:
    """Return the image service on the request's transaction."""
    return ImageService(db, store)


def get_simulator(db: DatabaseDep) -> SimulatorService:
    """Return the simulator service on the request's transaction."""
    return SimulatorService(db)


UsersDep = Annotated[UserService, Depends(get_users)]
StudiesDep = Annotated[StudyService, Depends(get_studies)]
DatasetsDep = Annotated[DatasetService, Depends(get_datasets)]
PipelineDep = Annotated[PipelineService, Depends(get_pipeline)]
AdminDep = Annotated[AdminService, Depends(get_admin)]
AnnotationDep = Annotated[AnnotationService, Depends(get_annotation)]
SimilarityDep = Annotated[SimilarityService, Depends(get_similarity)]
ImagesDep = Annotated[ImageService, Depends(get_images)]
SimulatorDep = Annotated[SimulatorService, Depends(get_simulator)]
