"""Database connections."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_sessions(database_url: str, pool_size: int = 5, max_overflow: int = 10) -> sessionmaker[Session]:
    """Make the session factory for one process.

    Connections are checked before use (`pool_pre_ping`), so a database restart costs one retry, not an error.
    Objects stay readable after a commit (`expire_on_commit=False`), because routes return them after their
    session has committed.

    Args:
        database_url: A SQLAlchemy URL, such as `postgresql+psycopg://cara:cara@db:5432/cara`.
        pool_size: Connections the process keeps open.
        max_overflow: Extra connections it may open under load.
    """
    engine: Engine = create_engine(
        database_url, pool_pre_ping=True, pool_size=pool_size, max_overflow=max_overflow
    )
    return sessionmaker(engine, expire_on_commit=False)
