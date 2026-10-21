"""The API application: its startup, its routers, and how CARA's errors become HTTP statuses."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from cara.api.routes import admin, annotation, auth, datasets, studies
from cara.config import AppSettings, app_settings
from cara.db.session import make_sessions
from cara.errors import Conflict, Forbidden, Invalid, NotFound
from cara.repositories.database import Database
from cara.repositories.image_store import ImageStore
from cara.services.users import UserService

logger = logging.getLogger(__name__)


def _first_admin(sessions: sessionmaker[Session], settings: AppSettings) -> None:
    """Create the first superuser from `CARA_ADMIN_*` on an empty database.

    Every API worker tries at startup; when two try at the same moment, the loser's IntegrityError is
    expected.
    """
    if settings.admin_password is None:
        return
    try:
        with sessions.begin() as session:
            if UserService(Database(session)).add_first_admin(
                settings.admin_username, settings.admin_password
            ):
                logger.warning("created the first superuser, %s", settings.admin_username)
    except IntegrityError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Read the settings, connect to the database, make the image store, and create the first admin."""
    app.state.settings = app_settings()
    settings = app.state.settings
    app.state.image_store = ImageStore(settings.image_root)
    app.state.sessions = make_sessions(settings.database_url, settings.db_pool_size, settings.db_max_overflow)
    _first_admin(app.state.sessions, settings)
    yield


app = FastAPI(title="CARA", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(studies.router)
app.include_router(datasets.router)
app.include_router(annotation.router)
app.include_router(annotation.images_router)
app.include_router(admin.router)
app.include_router(admin.adjudication)
app.include_router(admin.accounts)

STATUS_OF: dict[type[Exception], int] = {
    NotFound: status.HTTP_404_NOT_FOUND,
    Forbidden: status.HTTP_403_FORBIDDEN,
    Conflict: status.HTTP_409_CONFLICT,
    Invalid: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def _service_error(_: Request, error: Exception) -> JSONResponse:
    """Answer a CARA error with its HTTP status and its message as the detail."""
    return JSONResponse({"detail": str(error)}, status_code=STATUS_OF[type(error)])


for error_type in STATUS_OF:
    app.add_exception_handler(error_type, _service_error)


@app.get("/health")
def health() -> dict[str, str]:
    """Answer that the API is up; Docker's health check calls it."""
    return {"status": "ok"}
