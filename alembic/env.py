import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401
from app.core.config import settings
from app.db.base import Base

config = context.config


def _configure_alembic_logging() -> None:
    if config.config_file_name is None:
        return

    # When Alembic runs inside an already-booted host process (for example pytest
    # invoking command.upgrade()), reloading alembic.ini logging would mutate the
    # root handlers and disable existing app loggers. Preserve the host logging
    # setup in that case and only initialize Alembic's default console logging
    # when the process has not configured logging yet.
    if logging.getLogger().handlers:
        return

    fileConfig(config.config_file_name, disable_existing_loggers=False)


_configure_alembic_logging()

database_url = str(config.attributes.get("database_url") or settings.database_url)
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
