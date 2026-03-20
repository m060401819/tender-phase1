from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.endpoints.sources import get_crawl_command_runner
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite


class StubRunner:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.commands: list[list[str]] = []
        self.cwd_values: list[Path] = []

    def run(self, command: list[str], *, cwd: Path) -> int:
        self.commands.append(command)
        self.cwd_values.append(cwd)
        return self.return_code


@dataclass(slots=True)
class SeededSource:
    code: str
    name: str



def _next_id(session: Session, model_cls: type) -> int:
    return int(session.scalar(select(func.max(model_cls.id))) or 0) + 1



def _insert_source(
    *,
    session_factory: sessionmaker,
    code: str,
    name: str,
    base_url: str,
    supports_js_render: bool,
    crawl_interval_minutes: int,
    default_max_pages: int = 1,
) -> SeededSource:
    with session_factory() as session:
        session.add(
            SourceSite(
                id=_next_id(session, SourceSite),
                code=code,
                name=name,
                base_url=base_url,
                description=f"{name} source",
                is_active=True,
                supports_js_render=supports_js_render,
                crawl_interval_minutes=crawl_interval_minutes,
                default_max_pages=default_max_pages,
            )
        )
        session.commit()
    return SeededSource(code=code, name=name)



def _build_client(tmp_path: Path, *, runner: StubRunner) -> tuple[TestClient, sessionmaker, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'source_api.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_crawl_command_runner] = lambda: runner
    client = TestClient(app)

    return client, session_factory, engine



def test_sources_list_and_detail(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        _insert_source(
            session_factory=session_factory,
            code="anhui_ggzy_zfcg",
            name="Anhui GGZY",
            base_url="https://ggzy.ah.gov.cn/",
            supports_js_render=False,
            crawl_interval_minutes=60,
            default_max_pages=3,
        )
        _insert_source(
            session_factory=session_factory,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            supports_js_render=True,
            crawl_interval_minutes=30,
            default_max_pages=8,
        )

        list_response = client.get("/sources")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert [item["code"] for item in payload] == ["anhui_ggzy_zfcg", "example_source"]
        assert payload[0]["name"] == "Anhui GGZY"
        assert payload[0]["base_url"] == "https://ggzy.ah.gov.cn/"
        assert payload[0]["is_active"] is True
        assert payload[0]["supports_js_render"] is False
        assert payload[0]["crawl_interval_minutes"] == 60
        assert payload[0]["default_max_pages"] == 3

        detail_response = client.get("/sources/example_source")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["code"] == "example_source"
        assert detail["supports_js_render"] is True
        assert detail["default_max_pages"] == 8

        not_found = client.get("/sources/not-found")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_patch_source_updates_config_fields(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        _insert_source(
            session_factory=session_factory,
            code="anhui_ggzy_zfcg",
            name="Anhui GGZY",
            base_url="https://ggzy.ah.gov.cn/",
            supports_js_render=False,
            crawl_interval_minutes=60,
            default_max_pages=1,
        )

        response = client.patch(
            "/sources/anhui_ggzy_zfcg",
            json={
                "is_active": False,
                "crawl_interval_minutes": 15,
                "supports_js_render": True,
                "default_max_pages": 5,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == "anhui_ggzy_zfcg"
        assert payload["is_active"] is False
        assert payload["crawl_interval_minutes"] == 15
        assert payload["supports_js_render"] is True
        assert payload["default_max_pages"] == 5

        with session_factory() as session:
            updated = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert updated is not None
            assert updated.is_active is False
            assert updated.crawl_interval_minutes == 15
            assert updated.supports_js_render is True
            assert updated.default_max_pages == 5

        not_found = client.patch("/sources/not-found", json={"is_active": False})
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_trigger_manual_source_crawl_job_creates_job_and_runs_command(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        seeded = _insert_source(
            session_factory=session_factory,
            code="anhui_ggzy_zfcg",
            name="Anhui GGZY",
            base_url="https://ggzy.ah.gov.cn/",
            supports_js_render=False,
            crawl_interval_minutes=60,
        )

        response = client.post(
            f"/sources/{seeded.code}/crawl-jobs",
            json={"max_pages": 2, "triggered_by": "pytest"},
        )
        assert response.status_code == 201

        payload = response.json()
        assert payload["source_code"] == seeded.code
        assert payload["return_code"] == 0
        assert payload["job"]["job_type"] == "manual"
        assert payload["job"]["status"] == "succeeded"
        assert payload["job"]["started_at"] is not None
        assert payload["job"]["finished_at"] is not None
        assert "crawl anhui_ggzy_zfcg" in payload["command"]
        assert "max_pages=2" in payload["command"]

        assert len(runner.commands) == 1
        assert runner.commands[0][0:4] == [runner.commands[0][0], "-m", "scrapy", "crawl"]
        assert "crawl_job_id=" in " ".join(runner.commands[0])
        assert "max_pages=2" in " ".join(runner.commands[0])
        assert runner.cwd_values[0].name == "crawler"

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].job_type == "manual"
            assert jobs[0].status == "succeeded"
            assert jobs[0].triggered_by == "pytest"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_trigger_manual_source_crawl_job_failed_when_command_nonzero(tmp_path: Path) -> None:
    runner = StubRunner(return_code=9)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        _insert_source(
            session_factory=session_factory,
            code="anhui_ggzy_zfcg",
            name="Anhui GGZY",
            base_url="https://ggzy.ah.gov.cn/",
            supports_js_render=False,
            crawl_interval_minutes=60,
        )

        response = client.post("/sources/anhui_ggzy_zfcg/crawl-jobs", json={"max_pages": 1})
        assert response.status_code == 201
        payload = response.json()
        assert payload["return_code"] == 9
        assert payload["job"]["status"] == "failed"

        not_found = client.post("/sources/not-found/crawl-jobs", json={"max_pages": 1})
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
