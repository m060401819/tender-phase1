from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.endpoints.sources import get_crawl_command_runner, get_crawl_job_dispatcher
from app.core.auth import (
    ADMIN_CSRF_COOKIE_NAME,
    ADMIN_CSRF_COOKIE_PATH,
    ADMIN_CSRF_FORM_FIELD,
    AuthenticatedUser,
    UserRole,
    build_admin_csrf_token,
    get_current_user,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import SourceSite
from app.repositories import SourceSiteRepository
from app.services import SourceCrawlTriggerService


class StubRunner:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.commands: list[list[str]] = []

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        heartbeat_callback=None,
        heartbeat_interval_seconds: int = 30,
    ) -> int:
        _ = (cwd, heartbeat_callback, heartbeat_interval_seconds)
        self.commands.append(command)
        return self.return_code


class InlineDispatcher:
    def __init__(self, *, session_factory: sessionmaker, runner: StubRunner) -> None:
        self.session_factory = session_factory
        self.runner = runner

    def dispatch(self, request, *, project_root: Path, database_url: str) -> None:  # type: ignore[no-untyped-def]
        _ = database_url
        with self.session_factory() as session:
            source = SourceSiteRepository(session).get_model_by_code(request.source_code)
            assert source is not None
            service = SourceCrawlTriggerService(
                session=session,
                command_runner=self.runner,
                project_root=project_root,
            )
            service.execute_crawl_job(
                source=source,
                crawl_job_id=request.crawl_job_id,
                job_type=request.job_type,
                max_pages=request.max_pages,
                backfill_year=request.backfill_year,
            )


def _next_id(session: Session, model_cls: type) -> int:
    return int(session.scalar(select(func.max(model_cls.id))) or 0) + 1


def _seed_source(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        session.add(
            SourceSite(
                id=_next_id(session, SourceSite),
                code="anhui_ggzy_zfcg",
                name="安徽省公共资源交易监管网（政府采购）",
                base_url="https://ggzy.ah.gov.cn/",
                description="csrf admin test",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=5,
                schedule_enabled=False,
                schedule_days=1,
            )
        )
        session.commit()


def _build_client(tmp_path: Path) -> tuple[TestClient, StubRunner, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'admin_csrf.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _seed_source(session_factory)
    runner = StubRunner(return_code=0)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_crawl_command_runner] = lambda: runner
    app.dependency_overrides[get_crawl_job_dispatcher] = (
        lambda: InlineDispatcher(session_factory=session_factory, runner=runner)
    )
    client = TestClient(app)
    return client, runner, engine


def _override_user(role: UserRole, *, username: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(username=username, role=role)


def test_admin_post_rejects_missing_csrf_token_and_logs_event(tmp_path: Path, caplog) -> None:
    client, runner, engine = _build_client(tmp_path)
    try:
        _override_user(UserRole.ops, username="ops-user")

        with caplog.at_level(logging.WARNING):
            response = client.post(
                "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
                data={"job_type": "manual", "max_pages": "1"},
                follow_redirects=False,
            )

        assert response.status_code == 403
        assert "CSRF 校验失败" in response.text
        assert "缺少 CSRF Cookie" in response.text
        assert runner.commands == []
        assert any(getattr(record, "event", None) == "csrf_validation_failed" for record in caplog.records)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_post_rejects_wrong_csrf_token(tmp_path: Path) -> None:
    client, runner, engine = _build_client(tmp_path)
    try:
        _override_user(UserRole.ops, username="ops-user")

        token = build_admin_csrf_token(username="ops-user")
        client.cookies.set(ADMIN_CSRF_COOKIE_NAME, token, path=ADMIN_CSRF_COOKIE_PATH)

        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
            data={
                "job_type": "manual",
                "max_pages": "1",
                ADMIN_CSRF_FORM_FIELD: "wrong-token",
            },
            follow_redirects=False,
        )

        assert response.status_code == 403
        assert "CSRF Token 不匹配" in response.text
        assert runner.commands == []
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_post_accepts_valid_csrf_token(tmp_path: Path, admin_csrf) -> None:
    client, runner, engine = _build_client(tmp_path)
    try:
        _override_user(UserRole.ops, username="ops-user")

        response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
            data=admin_csrf(
                client,
                username="ops-user",
                data={"job_type": "manual", "max_pages": "2"},
            ),
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers.get("location", "").startswith("/admin/crawl-jobs/")
        assert len(runner.commands) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_role_checks_and_csrf_are_enforced_together(tmp_path: Path, admin_csrf) -> None:
    client, runner, engine = _build_client(tmp_path)
    try:
        _override_user(UserRole.viewer, username="viewer-user")
        viewer_response = client.post(
            "/admin/sources/anhui_ggzy_zfcg/crawl-jobs",
            data=admin_csrf(
                client,
                username="viewer-user",
                data={"job_type": "manual", "max_pages": "1"},
            ),
            follow_redirects=False,
        )
        assert viewer_response.status_code == 403
        assert viewer_response.json()["detail"] == "ops role required"
        assert runner.commands == []

        _override_user(UserRole.ops, username="ops-user")
        ops_response = client.post(
            "/admin/settings/health-rules",
            data=admin_csrf(
                client,
                username="ops-user",
                data={
                    "recent_error_warning_threshold": "2",
                    "recent_error_critical_threshold": "5",
                    "consecutive_failure_warning_threshold": "1",
                    "consecutive_failure_critical_threshold": "2",
                    "partial_warning_enabled": "false",
                },
            ),
            follow_redirects=False,
        )
        assert ops_response.status_code == 403
        assert ops_response.json()["detail"] == "admin role required"

        _override_user(UserRole.admin, username="admin-user")
        admin_response = client.post(
            "/admin/settings/health-rules",
            data=admin_csrf(
                client,
                username="admin-user",
                data={
                    "recent_error_warning_threshold": "2",
                    "recent_error_critical_threshold": "5",
                    "consecutive_failure_warning_threshold": "1",
                    "consecutive_failure_critical_threshold": "2",
                    "partial_warning_enabled": "false",
                },
            ),
            follow_redirects=False,
        )
        assert admin_response.status_code == 303
        assert admin_response.headers.get("location") == "/admin/settings/health-rules?updated=1"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
