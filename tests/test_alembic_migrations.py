from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_DIR = PROJECT_ROOT / "alembic"
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
POSTGRES_ADMIN_URL = os.getenv("TEST_POSTGRESQL_ADMIN_URL", "").strip()
BACKEND_NAMES = ["sqlite", *(["postgresql"] if POSTGRES_ADMIN_URL else [])]


@dataclass(frozen=True)
class MigrationBackend:
    name: str
    database_url: str


@pytest.fixture(params=BACKEND_NAMES, ids=BACKEND_NAMES)
def migration_backend(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[MigrationBackend]:
    if request.param == "sqlite":
        database_url = f"sqlite+pysqlite:///{tmp_path / f'alembic_{uuid4().hex}.db'}"
        yield MigrationBackend(name="sqlite", database_url=database_url)
        return

    with _temporary_postgres_database(POSTGRES_ADMIN_URL) as database_url:
        yield MigrationBackend(name="postgresql", database_url=database_url)


def test_alembic_upgrade_head_smoke(migration_backend: MigrationBackend) -> None:
    _upgrade(migration_backend.database_url, "head")

    engine = create_engine(migration_backend.database_url)
    try:
        assert _current_heads(engine) == _script_heads()

        inspector = inspect(engine)
        for table_name in (
            "source_site",
            "crawl_job",
            "raw_document",
            "tender_notice",
            "notice_version",
            "tender_attachment",
            "crawl_error",
            "health_rule_config",
        ):
            assert inspector.has_table(table_name)
    finally:
        engine.dispose()


def test_migration_20260322_0009_preserves_rows_and_adds_lease_columns(
    migration_backend: MigrationBackend,
) -> None:
    _upgrade(migration_backend.database_url, "20260321_0008")

    before_engine = create_engine(migration_backend.database_url)
    created_at = datetime(2026, 3, 22, 8, 0, tzinfo=timezone.utc)
    started_at = created_at + timedelta(minutes=5)
    try:
        _insert_source_site(before_engine, source_site_id=1, code="migration_0009_source")
        _insert_crawl_jobs(
            before_engine,
            [
                {
                    "id": 1001,
                    "source_site_id": 1,
                    "job_type": "scheduled",
                    "status": "pending",
                    "triggered_by": "migration-test",
                    "started_at": started_at,
                    "message": "legacy row before 0009",
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            ],
        )
    finally:
        before_engine.dispose()

    _upgrade(migration_backend.database_url, "20260322_0009")

    after_engine = create_engine(migration_backend.database_url)
    try:
        inspector = inspect(after_engine)
        column_names = {column["name"] for column in inspector.get_columns("crawl_job")}
        assert {"heartbeat_at", "lease_expires_at"}.issubset(column_names)
        assert "ix_crawl_job_lease_expires_at" in {index["name"] for index in inspector.get_indexes("crawl_job")}

        row = _crawl_job_row(after_engine, 1001)
        assert row["status"] == "pending"
        assert row["message"] == "legacy row before 0009"
        assert _normalize_dt(row["created_at"]) == created_at
        assert _normalize_dt(row["started_at"]) == started_at
        assert row["heartbeat_at"] is None
        assert row["lease_expires_at"] is None
    finally:
        after_engine.dispose()


def test_migration_20260322_0010_backfills_queue_timestamps(migration_backend: MigrationBackend) -> None:
    _upgrade(migration_backend.database_url, "20260322_0009")

    before_engine = create_engine(migration_backend.database_url)
    base_time = datetime(2026, 3, 22, 16, 0, tzinfo=timezone.utc)
    running_started_at = base_time + timedelta(minutes=11)
    failed_started_at = base_time + timedelta(minutes=21)
    running_lease_expires_at = base_time + timedelta(minutes=45)
    try:
        _insert_source_site(before_engine, source_site_id=1, code="migration_0010_source")
        _insert_crawl_jobs(
            before_engine,
            [
                {
                    "id": 1010,
                    "source_site_id": 1,
                    "status": "pending",
                    "created_at": base_time,
                    "updated_at": base_time,
                    "lease_expires_at": base_time + timedelta(minutes=30),
                },
                {
                    "id": 1011,
                    "source_site_id": 1,
                    "status": "running",
                    "created_at": base_time + timedelta(minutes=10),
                    "updated_at": base_time + timedelta(minutes=10),
                    "started_at": running_started_at,
                    "lease_expires_at": running_lease_expires_at,
                },
                {
                    "id": 1012,
                    "source_site_id": 1,
                    "status": "failed",
                    "created_at": base_time + timedelta(minutes=20),
                    "updated_at": base_time + timedelta(minutes=20),
                    "started_at": failed_started_at,
                },
            ],
        )
    finally:
        before_engine.dispose()

    _upgrade(migration_backend.database_url, "20260322_0010")

    after_engine = create_engine(migration_backend.database_url)
    try:
        pending_row = _crawl_job_row(after_engine, 1010)
        assert _normalize_dt(pending_row["queued_at"]) == base_time
        assert pending_row["picked_at"] is None
        assert _normalize_dt(pending_row["timeout_at"]) == base_time + timedelta(minutes=30)

        running_row = _crawl_job_row(after_engine, 1011)
        assert _normalize_dt(running_row["queued_at"]) == base_time + timedelta(minutes=10)
        assert _normalize_dt(running_row["picked_at"]) == running_started_at
        assert _normalize_dt(running_row["timeout_at"]) == running_lease_expires_at

        failed_row = _crawl_job_row(after_engine, 1012)
        assert _normalize_dt(failed_row["queued_at"]) == base_time + timedelta(minutes=20)
        assert _normalize_dt(failed_row["picked_at"]) == failed_started_at
        assert failed_row["timeout_at"] is None
    finally:
        after_engine.dispose()


def test_migration_20260322_0011_collapses_duplicate_active_jobs_and_enforces_mutex(
    migration_backend: MigrationBackend,
) -> None:
    _upgrade(migration_backend.database_url, "20260322_0010")

    before_engine = create_engine(migration_backend.database_url)
    source_one_time = datetime(2026, 3, 22, 17, 30, tzinfo=timezone.utc)
    source_two_time = datetime(2026, 3, 22, 17, 45, tzinfo=timezone.utc)
    try:
        _insert_source_site(before_engine, source_site_id=1, code="migration_0011_source_one")
        _insert_source_site(before_engine, source_site_id=2, code="migration_0011_source_two")
        _insert_crawl_jobs(
            before_engine,
            [
                {
                    "id": 2010,
                    "source_site_id": 1,
                    "status": "pending",
                    "created_at": source_one_time,
                    "updated_at": source_one_time,
                    "queued_at": source_one_time,
                    "message": "older active job",
                },
                {
                    "id": 2011,
                    "source_site_id": 1,
                    "status": "running",
                    "created_at": source_one_time + timedelta(minutes=1),
                    "updated_at": source_one_time + timedelta(minutes=1),
                    "queued_at": source_one_time + timedelta(minutes=1),
                    "picked_at": source_one_time + timedelta(minutes=2),
                    "started_at": source_one_time + timedelta(minutes=2),
                    "heartbeat_at": source_one_time + timedelta(minutes=4),
                    "timeout_at": source_one_time + timedelta(minutes=20),
                    "lease_expires_at": source_one_time + timedelta(minutes=20),
                    "message": "latest active job",
                },
                {
                    "id": 2020,
                    "source_site_id": 2,
                    "status": "pending",
                    "created_at": source_two_time,
                    "updated_at": source_two_time,
                    "queued_at": source_two_time,
                },
                {
                    "id": 2021,
                    "source_site_id": 2,
                    "status": "pending",
                    "created_at": source_two_time,
                    "updated_at": source_two_time,
                    "queued_at": source_two_time,
                    "message": "same timestamp but higher id should win",
                },
                {
                    "id": 2022,
                    "source_site_id": 2,
                    "status": "failed",
                    "created_at": source_two_time - timedelta(minutes=5),
                    "updated_at": source_two_time - timedelta(minutes=5),
                    "started_at": source_two_time - timedelta(minutes=4),
                    "finished_at": source_two_time - timedelta(minutes=3),
                    "message": "already inactive",
                },
            ],
        )
    finally:
        before_engine.dispose()

    _upgrade(migration_backend.database_url, "20260322_0011")

    after_engine = create_engine(migration_backend.database_url)
    try:
        inspector = inspect(after_engine)
        assert "uq_crawl_job_source_active" in {index["name"] for index in inspector.get_indexes("crawl_job")}

        kept_source_one = _crawl_job_row(after_engine, 2011)
        assert kept_source_one["status"] == "running"
        assert _normalize_dt(kept_source_one["timeout_at"]) == source_one_time + timedelta(minutes=20)
        assert _normalize_dt(kept_source_one["lease_expires_at"]) == source_one_time + timedelta(minutes=20)

        collapsed_source_one = _crawl_job_row(after_engine, 2010)
        assert collapsed_source_one["status"] == "failed"
        assert _normalize_dt(collapsed_source_one["started_at"]) == source_one_time
        assert collapsed_source_one["finished_at"] is not None
        assert collapsed_source_one["heartbeat_at"] is not None
        assert collapsed_source_one["timeout_at"] is None
        assert collapsed_source_one["lease_expires_at"] is None
        assert "source_mutex_migration" in str(collapsed_source_one["message"])
        assert "#2011" in str(collapsed_source_one["message"])

        kept_source_two = _crawl_job_row(after_engine, 2021)
        assert kept_source_two["status"] == "pending"
        assert kept_source_two["message"] == "same timestamp but higher id should win"

        collapsed_source_two = _crawl_job_row(after_engine, 2020)
        assert collapsed_source_two["status"] == "failed"
        assert _normalize_dt(collapsed_source_two["started_at"]) == source_two_time
        assert "source_mutex_migration" in str(collapsed_source_two["message"])
        assert "#2021" in str(collapsed_source_two["message"])

        inactive_row = _crawl_job_row(after_engine, 2022)
        assert inactive_row["status"] == "failed"
        assert inactive_row["message"] == "already inactive"

        with pytest.raises(IntegrityError):
            _insert_crawl_jobs(
                after_engine,
                [
                    {
                        "id": 2023,
                        "source_site_id": 2,
                        "status": "pending",
                        "created_at": source_two_time + timedelta(minutes=10),
                        "updated_at": source_two_time + timedelta(minutes=10),
                    }
                ],
            )
    finally:
        after_engine.dispose()


def test_programmatic_upgrade_preserves_existing_app_loggers_and_handlers(
    migration_backend: MigrationBackend,
    caplog,
) -> None:
    root_logger = logging.getLogger()
    handlers_before = tuple(root_logger.handlers)

    app_logger = logging.getLogger("app.main")
    dispatch_logger = logging.getLogger("app.services.crawl_job_dispatch_service")
    assert app_logger.disabled is False
    assert dispatch_logger.disabled is False

    _upgrade(migration_backend.database_url, "head")

    assert tuple(root_logger.handlers) == handlers_before
    assert app_logger.disabled is False
    assert dispatch_logger.disabled is False

    with caplog.at_level(logging.INFO):
        app_logger.error(
            "host app logger still emits structured events after alembic upgrade",
            extra={"event": "host_logger_still_active_after_alembic_upgrade"},
        )
        dispatch_logger.warning(
            "dispatch logger still emits structured events after alembic upgrade",
            extra={"event": "dispatch_logger_still_active_after_alembic_upgrade"},
        )

    assert any(
        getattr(record, "event", "") == "host_logger_still_active_after_alembic_upgrade"
        for record in caplog.records
    )
    assert any(
        getattr(record, "event", "") == "dispatch_logger_still_active_after_alembic_upgrade"
        for record in caplog.records
    )


def _make_alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.attributes["database_url"] = database_url
    return config


def _upgrade(database_url: str, revision: str) -> None:
    command.upgrade(_make_alembic_config(database_url), revision)


def _script_heads() -> set[str]:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    return set(ScriptDirectory.from_config(config).get_heads())


def _current_heads(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(MigrationContext.configure(connection).get_current_heads())


def _insert_source_site(engine: Engine, *, source_site_id: int, code: str) -> None:
    source_site = _table(engine, "source_site")
    with engine.begin() as connection:
        connection.execute(
            source_site.insert().values(
                id=source_site_id,
                code=code,
                name=f"Source {source_site_id}",
                base_url=f"https://example.com/{code}",
            )
        )


def _insert_crawl_jobs(engine: Engine, rows: list[dict[str, object]]) -> None:
    crawl_job = _table(engine, "crawl_job")
    with engine.begin() as connection:
        for row in rows:
            connection.execute(crawl_job.insert().values(**row))


def _crawl_job_row(engine: Engine, job_id: int) -> dict[str, object]:
    crawl_job = _table(engine, "crawl_job")
    with engine.connect() as connection:
        return dict(
            connection.execute(select(crawl_job).where(crawl_job.c.id == job_id)).mappings().one()
        )


def _table(engine: Engine, table_name: str) -> sa.Table:
    return sa.Table(table_name, MetaData(), autoload_with=engine)


def _normalize_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise AssertionError(f"expected datetime, got {type(value)!r}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@contextmanager
def _temporary_postgres_database(admin_url: str) -> Iterator[str]:
    database_name = f"test_alembic_{uuid4().hex}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    database_url = str(make_url(admin_url).set(database=database_name))
    database_created = False
    try:
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'CREATE DATABASE "{database_name}"'))
        database_created = True
        yield database_url
    finally:
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(
                    sa.text(
                        """
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE datname = :database_name
                          AND pid <> pg_backend_pid()
                        """
                    ),
                    {"database_name": database_name},
                )
                connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()
