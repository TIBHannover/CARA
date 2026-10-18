"""How Alembic reaches the database: the URL from `CARA_DATABASE_URL`, the tables from `cara.db.models`."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cara.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", os.environ["CARA_DATABASE_URL"])


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    """Leave the per-encoder HNSW indexes out of autogenerate's comparison.

    They are created when an encoder's embeddings are first stored
    (`cara.repositories.images.ensure_hnsw_index`), not by migrations, so autogenerate must not propose
    dropping them.
    """
    return not (type_ == "index" and name is not None and name.startswith("ix_embeddings_hnsw_"))


def run_migrations_offline() -> None:
    """Write the migrations as SQL instead of running them (`alembic upgrade --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations against the database, in one transaction."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
