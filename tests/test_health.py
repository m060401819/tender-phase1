from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tender-phase1"}


def test_readyz_returns_ready_when_database_and_schema_are_available(tmp_path: Path) -> None:
    client, engine = _build_sqlite_client(
        tmp_path,
        "health_ready.db",
        revision=_alembic_heads()[0],
    )
    try:
        response = client.get("/readyz")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["service"] == "tender-phase1"
    assert payload["checks"]["database_connection"]["status"] == "ok"
    assert payload["checks"]["required_tables"]["status"] == "ok"
    assert payload["checks"]["alembic_version"]["status"] == "ok"
    assert payload["checks"]["alembic_version"]["current_heads"] == _alembic_heads()


def test_readyz_returns_not_ready_when_database_is_unavailable(tmp_path: Path) -> None:
    client, engine = _build_client(f"sqlite+pysqlite:///{tmp_path / 'missing-dir' / 'health_down.db'}")
    try:
        response = client.get("/readyz")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database_connection"]["status"] == "failed"
    assert payload["checks"]["required_tables"]["status"] == "skipped"
    assert payload["checks"]["alembic_version"]["status"] == "skipped"


def test_readyz_returns_not_ready_when_alembic_revision_is_behind_head(tmp_path: Path) -> None:
    client, engine = _build_sqlite_client(
        tmp_path,
        "health_stale_revision.db",
        revision=_stale_alembic_revision(),
    )
    try:
        response = client.get("/readyz")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database_connection"]["status"] == "ok"
    assert payload["checks"]["required_tables"]["status"] == "ok"
    assert payload["checks"]["alembic_version"]["status"] == "failed"
    assert "does not match code head" in payload["checks"]["alembic_version"]["detail"]


def _build_client(database_url: str) -> tuple[TestClient, object]:
    engine = create_engine(database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), engine


def _build_sqlite_client(tmp_path: Path, name: str, *, revision: str) -> tuple[TestClient, object]:
    client, engine = _build_client(f"sqlite+pysqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )
    return client, engine


def _alembic_heads() -> list[str]:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    return sorted(ScriptDirectory.from_config(config).get_heads())


def _stale_alembic_revision() -> str:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = set(script.get_heads())
    for revision in script.walk_revisions():
        if revision.revision not in heads:
            return revision.revision
    raise AssertionError("expected at least one non-head alembic revision")
