from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.endpoints.sources import get_crawl_command_runner
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlError, CrawlJob, SourceSite


class StubRunner:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.commands: list[list[str]] = []
        self.cwd_values: list[Path] = []

    def run(self, command: list[str], *, cwd: Path) -> int:
        self.commands.append(command)
        self.cwd_values.append(cwd)
        return self.return_code


class ErrorRecordingRunner(StubRunner):
    def __init__(self, *, database_url: str, return_code: int = 0, error_message: str) -> None:
        super().__init__(return_code=return_code)
        self.database_url = database_url
        self.error_message = error_message

    def run(self, command: list[str], *, cwd: Path) -> int:
        result = super().run(command, cwd=cwd)
        crawl_job_id = _extract_crawl_job_id(command)
        engine = create_engine(self.database_url)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        try:
            with session_factory() as session:
                job = session.get(CrawlJob, crawl_job_id)
                assert job is not None
                session.add(
                    CrawlError(
                        id=_next_id(session, CrawlError),
                        source_site_id=int(job.source_site_id),
                        crawl_job_id=crawl_job_id,
                        raw_document_id=None,
                        stage="fetch",
                        url="https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList",
                        error_type="ListPageError",
                        error_message=self.error_message,
                        traceback=None,
                        retryable=True,
                        occurred_at=datetime.now(timezone.utc),
                        resolved=False,
                    )
                )
                job.error_count = int(job.error_count or 0) + 1
                session.commit()
        finally:
            engine.dispose()
        return result


@dataclass(slots=True)
class SeededSource:
    code: str
    name: str



def _next_id(session: Session, model_cls: type) -> int:
    return int(session.scalar(select(func.max(model_cls.id))) or 0) + 1


def _extract_crawl_job_id(command: list[str]) -> int:
    for part in command:
        if part.startswith("crawl_job_id="):
            return int(part.split("=", maxsplit=1)[1])
    raise AssertionError("crawl_job_id missing from command")



def _insert_source(
    *,
    session_factory: sessionmaker,
    code: str,
    name: str,
    base_url: str,
    supports_js_render: bool,
    crawl_interval_minutes: int,
    default_max_pages: int = 1,
    schedule_enabled: bool = False,
    schedule_days: int = 1,
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
                schedule_enabled=schedule_enabled,
                schedule_days=schedule_days,
            )
        )
        session.commit()
    return SeededSource(code=code, name=name)


def _insert_crawl_job(
    *,
    session_factory: sessionmaker,
    source_code: str,
    status: str,
    started_at: datetime,
    notices_upserted: int,
    error_count: int,
    message: str | None,
) -> int:
    with session_factory() as session:
        source = session.scalar(select(SourceSite).where(SourceSite.code == source_code))
        assert source is not None
        next_job_id = _next_id(session, CrawlJob)
        session.add(
            CrawlJob(
                id=next_job_id,
                source_site_id=int(source.id),
                job_type="manual",
                status=status,
                triggered_by="pytest",
                started_at=started_at,
                finished_at=started_at + timedelta(minutes=3),
                pages_fetched=2,
                documents_saved=2,
                notices_upserted=notices_upserted,
                deduplicated_count=0,
                error_count=error_count,
                message=message,
                created_at=started_at,
                updated_at=started_at,
            )
        )
        session.commit()
        return next_job_id


def _insert_crawl_error(
    *,
    session_factory: sessionmaker,
    source_code: str,
    crawl_job_id: int,
    created_at: datetime,
    message: str,
) -> None:
    with session_factory() as session:
        source = session.scalar(select(SourceSite).where(SourceSite.code == source_code))
        assert source is not None
        session.add(
            CrawlError(
                id=_next_id(session, CrawlError),
                source_site_id=int(source.id),
                crawl_job_id=crawl_job_id,
                raw_document_id=None,
                stage="parse",
                url="https://example.com/source-health",
                error_type="HealthError",
                error_message=message,
                traceback=None,
                retryable=False,
                occurred_at=created_at,
                resolved=False,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()



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
        assert payload[0]["official_url"] == "https://ggzy.ah.gov.cn/"
        assert payload[0]["list_url"] == "https://ggzy.ah.gov.cn/"
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
        assert detail["official_url"] == "https://example.com/"
        assert detail["list_url"] == "https://example.com/"

        not_found = client.get("/sources/not-found")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_create_source_success_and_duplicate_validation(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        create_resp = client.post(
            "/sources",
            json={
                "source_code": "manual_new_source",
                "source_name": "Manual New Source",
                "official_url": "https://manual-new-source.example.com/",
                "list_url": "https://manual-new-source.example.com/list",
                "remark": "manual create",
                "is_active": True,
                "schedule_enabled": True,
                "schedule_days": 3,
                "crawl_interval_minutes": 180,
                "default_max_pages": 6,
            },
        )
        assert create_resp.status_code == 201
        payload = create_resp.json()
        assert payload["code"] == "manual_new_source"
        assert payload["name"] == "Manual New Source"
        assert payload["base_url"] == "https://manual-new-source.example.com/"
        assert payload["official_url"] == "https://manual-new-source.example.com/"
        assert payload["list_url"] == "https://manual-new-source.example.com/list"
        assert payload["is_active"] is True
        assert payload["default_max_pages"] == 6

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "manual_new_source"))
            assert source is not None
            assert source.name == "Manual New Source"
            assert source.list_url == "https://manual-new-source.example.com/list"
            assert source.description == "manual create"
            assert source.schedule_enabled is True
            assert source.schedule_days == 3
            assert source.crawl_interval_minutes == 180
            assert source.next_scheduled_run_at is not None

        duplicate = client.post(
            "/sources",
            json={
                "source_code": "manual_new_source",
                "source_name": "Manual New Source 2",
                "official_url": "https://manual-new-source-2.example.com/",
                "list_url": "https://manual-new-source-2.example.com/list",
                "is_active": True,
                "schedule_enabled": False,
                "schedule_days": 1,
                "crawl_interval_minutes": 60,
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "source_code already exists"
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


def test_source_schedule_get_and_patch(tmp_path: Path) -> None:
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
            schedule_enabled=False,
            schedule_days=1,
        )

        before = client.get("/sources/anhui_ggzy_zfcg/schedule")
        assert before.status_code == 200
        before_payload = before.json()
        assert before_payload["source_code"] == "anhui_ggzy_zfcg"
        assert before_payload["schedule_enabled"] is False
        assert before_payload["schedule_days"] == 1
        assert before_payload["next_scheduled_run_at"] is None
        assert before_payload["last_scheduled_run_at"] is None
        assert before_payload["last_schedule_status"] is None

        patched = client.patch(
            "/sources/anhui_ggzy_zfcg/schedule",
            json={"schedule_enabled": True, "schedule_days": 2},
        )
        assert patched.status_code == 200
        payload = patched.json()
        assert payload["source_code"] == "anhui_ggzy_zfcg"
        assert payload["schedule_enabled"] is True
        assert payload["schedule_days"] == 2
        assert payload["next_scheduled_run_at"] is not None

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.schedule_enabled is True
            assert source.schedule_days == 2
            assert source.next_scheduled_run_at is not None

        invalid = client.patch(
            "/sources/anhui_ggzy_zfcg/schedule",
            json={"schedule_days": 5},
        )
        assert invalid.status_code == 422

        not_found_get = client.get("/sources/not-found/schedule")
        assert not_found_get.status_code == 404
        not_found_patch = client.patch("/sources/not-found/schedule", json={"schedule_enabled": True})
        assert not_found_patch.status_code == 404
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


def test_trigger_manual_source_crawl_job_marks_fetch_error_as_failed(tmp_path: Path) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'source_api.db'}"
    runner = ErrorRecordingRunner(
        database_url=db_url,
        return_code=0,
        error_message="页面获取失败: 列表接口返回 code=800 message=系统繁忙，请稍后再试!",
    )
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        _insert_source(
            session_factory=session_factory,
            code="ggzy_gov_cn_deal",
            name="GGZY Deal",
            base_url="https://www.ggzy.gov.cn/",
            supports_js_render=False,
            crawl_interval_minutes=60,
            default_max_pages=5,
        )

        response = client.post("/sources/ggzy_gov_cn_deal/crawl-jobs", json={"max_pages": 1})
        assert response.status_code == 201
        payload = response.json()
        assert payload["return_code"] == 0
        assert payload["job"]["status"] == "failed"
        assert payload["job"]["error_count"] == 1
        assert "failure_reason=页面获取失败: 列表接口返回 code=800 message=系统繁忙，请稍后再试!" in (
            payload["job"]["message"] or ""
        )
        assert "failure_reason=页面获取失败: 页面获取失败:" not in (payload["job"]["message"] or "")

        with session_factory() as session:
            job = session.scalar(select(CrawlJob).where(CrawlJob.source_site_id == 1))
            assert job is not None
            assert job.status == "failed"
            assert int(job.error_count or 0) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_trigger_backfill_source_crawl_job_creates_job_and_passes_backfill_year(tmp_path: Path) -> None:
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
            default_max_pages=120,
        )

        response = client.post(
            f"/sources/{seeded.code}/crawl-jobs",
            json={"job_type": "backfill", "backfill_year": 2026, "triggered_by": "pytest-backfill", "max_pages": 999},
        )
        assert response.status_code == 201

        payload = response.json()
        assert payload["job"]["job_type"] == "backfill"
        assert payload["job"]["status"] == "succeeded"
        assert "backfill_year=2026" in payload["command"]
        assert "max_pages=999" in payload["command"]

        assert len(runner.commands) == 1
        command_text = " ".join(runner.commands[0])
        assert "backfill_year=2026" in command_text
        assert "max_pages=999" in command_text

        with session_factory() as session:
            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].job_type == "backfill"
            assert jobs[0].triggered_by == "pytest-backfill"

        missing_year = client.post(
            f"/sources/{seeded.code}/crawl-jobs",
            json={"job_type": "backfill", "triggered_by": "pytest-backfill"},
        )
        assert missing_year.status_code == 422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_source_health_api_returns_normal_warning_and_critical(tmp_path: Path) -> None:
    runner = StubRunner(return_code=0)
    client, session_factory, engine = _build_client(tmp_path, runner=runner)
    try:
        now = datetime.now(timezone.utc)
        _insert_source(
            session_factory=session_factory,
            code="source_normal",
            name="Normal Source",
            base_url="https://normal.example.com/",
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        _insert_source(
            session_factory=session_factory,
            code="source_warning",
            name="Warning Source",
            base_url="https://warning.example.com/",
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        _insert_source(
            session_factory=session_factory,
            code="source_critical",
            name="Critical Source",
            base_url="https://critical.example.com/",
            supports_js_render=False,
            crawl_interval_minutes=60,
        )

        _insert_crawl_job(
            session_factory=session_factory,
            source_code="source_normal",
            status="succeeded",
            started_at=now - timedelta(hours=3),
            notices_upserted=4,
            error_count=0,
            message="normal ok",
        )

        warning_job_id = _insert_crawl_job(
            session_factory=session_factory,
            source_code="source_warning",
            status="partial",
            started_at=now - timedelta(hours=2),
            notices_upserted=1,
            error_count=1,
            message="warning partial",
        )
        for idx in range(3):
            _insert_crawl_error(
                session_factory=session_factory,
                source_code="source_warning",
                crawl_job_id=warning_job_id,
                created_at=now - timedelta(hours=1, minutes=idx),
                message=f"warning error {idx}",
            )

        critical_job_id_1 = _insert_crawl_job(
            session_factory=session_factory,
            source_code="source_critical",
            status="failed",
            started_at=now - timedelta(hours=4),
            notices_upserted=0,
            error_count=2,
            message="critical failed 1",
        )
        critical_job_id_2 = _insert_crawl_job(
            session_factory=session_factory,
            source_code="source_critical",
            status="failed",
            started_at=now - timedelta(hours=1),
            notices_upserted=0,
            error_count=1,
            message="critical failed 2",
        )
        _insert_crawl_error(
            session_factory=session_factory,
            source_code="source_critical",
            crawl_job_id=critical_job_id_2,
            created_at=now - timedelta(minutes=20),
            message="critical latest error",
        )
        _insert_crawl_error(
            session_factory=session_factory,
            source_code="source_critical",
            crawl_job_id=critical_job_id_1,
            created_at=now - timedelta(hours=3),
            message="critical older error",
        )

        normal = client.get("/sources/source_normal/health")
        assert normal.status_code == 200
        normal_payload = normal.json()
        assert normal_payload["health_status"] == "normal"
        assert normal_payload["health_status_label"] == "正常"
        assert normal_payload["latest_job_status"] == "succeeded"

        warning = client.get("/sources/source_warning/health")
        assert warning.status_code == 200
        warning_payload = warning.json()
        assert warning_payload["health_status"] == "warning"
        assert warning_payload["health_status_label"] == "警告"
        assert warning_payload["latest_job_status"] == "partial"
        assert warning_payload["recent_7d_error_count"] >= 3

        critical = client.get("/sources/source_critical/health")
        assert critical.status_code == 200
        critical_payload = critical.json()
        assert critical_payload["health_status"] == "critical"
        assert critical_payload["health_status_label"] == "异常"
        assert critical_payload["latest_job_status"] == "failed"
        assert critical_payload["consecutive_failed"] is True
        assert "critical latest error" in critical_payload["latest_failure_reason"]

        not_found = client.get("/sources/not-found/health")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
