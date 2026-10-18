"""The API's deployment settings, read from `CARA_*` environment variables (see `.env.example`)."""

from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """The API's settings: each field is read from `CARA_<FIELD>`; an empty variable keeps the default.

    Attributes:
        image_root: The folder dataset paths are relative to (`/data` in the containers).
        secret_key: Signs login tokens.
        token_minutes: How long a login lasts.
        db_pool_size: Database connections each API process keeps open.
        db_max_overflow: Extra connections each process may open under load.
        admin_username: The first superuser, created when the API starts on a database with no users and
            `admin_password` is set.
    """

    model_config = SettingsConfigDict(env_prefix="CARA_", env_ignore_empty=True, frozen=True)

    database_url: str
    image_root: Path
    secret_key: str
    token_minutes: int = Field(default=720, ge=1)
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    admin_username: str = "admin"
    admin_password: str | None = None


def app_settings() -> AppSettings:
    """Read the settings from the environment.

    Raises:
        ValueError: A required variable (`CARA_DATABASE_URL`, `CARA_IMAGE_ROOT`, `CARA_SECRET_KEY`) is not
            set, the message naming each one missing; or a value is invalid (pydantic's `ValidationError`).
    """
    try:
        return AppSettings()  # type: ignore[call-arg]
    except ValidationError as error:
        missing = [f"CARA_{e['loc'][0]}".upper() for e in error.errors() if e["type"] == "missing"]
        if not missing:
            raise
        raise ValueError(f"{', '.join(missing)} not set: copy .env.example to .env and fill it in") from error
