from __future__ import annotations

import re
import socket
import time
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.request import urlopen

import pytest
import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.auth import AuthenticatedUser, UserRole, get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite
from app.services import CrawlJobService

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect
sync_playwright = playwright.sync_playwright
PlaywrightError = playwright.Error


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _wait_for_server(base_url: str, *, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(f"{base_url}/healthz", timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - best effort polling
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"server did not become ready: {last_error}")


def _seed_source(
    session: Session,
    *,
    code: str,
    name: str,
    base_url: str,
    official_url: str,
    list_url: str,
    is_active: bool,
    default_max_pages: int = 7,
    schedule_enabled: bool = False,
    schedule_days: int = 1,
) -> None:
    session.add(
        SourceSite(
            code=code,
            name=name,
            base_url=base_url,
            official_url=official_url,
            list_url=list_url,
            description="playwright e2e seed",
            is_active=is_active,
            supports_js_render=False,
            crawl_interval_minutes=60,
            default_max_pages=default_max_pages,
            schedule_enabled=schedule_enabled,
            schedule_days=schedule_days,
        )
    )


def _seed_failed_job(session_factory: sessionmaker) -> int:
    service = CrawlJobService(session_factory=session_factory)
    try:
        failed = service.create_job(
            source_code="anhui_ggzy_zfcg",
            job_type="manual",
            triggered_by="pytest-seed",
        )
        service.start_job(failed.id)
        service.record_stats(
            failed.id,
            pages_fetched=1,
            documents_saved=1,
            notices_upserted=0,
            deduplicated_count=0,
            error_count=1,
        )
        service.finish_job(
            failed.id,
            status="failed",
            message="seed failed job for playwright retry",
        )
        return int(failed.id)
    finally:
        service.close()


def _finish_job_after_delay(
    session_factory: sessionmaker,
    *,
    job_id: int,
    delay_seconds: float,
) -> None:
    time.sleep(delay_seconds)
    service = CrawlJobService(session_factory=session_factory)
    try:
        service.start_job(job_id)
        service.record_stats(
            job_id,
            pages_fetched=3,
            documents_saved=2,
            notices_upserted=1,
            deduplicated_count=0,
            error_count=0,
        )
        service.finish_job(
            job_id,
            status="succeeded",
            message="playwright auto-finished job",
        )
    finally:
        service.close()


class AdminE2ERuntime:
    def __init__(
        self,
        *,
        tmp_path: Path,
        include_inactive_source: bool = False,
        seed_failed_job: bool = False,
    ) -> None:
        self.db_url = f"sqlite+pysqlite:///{tmp_path / 'admin_e2e.db'}"
        self.engine = create_engine(self.db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        with self.session_factory() as session:
            _seed_source(
                session,
                code="anhui_ggzy_zfcg",
                name="安徽省公共资源交易监管网（政府采购）",
                base_url="https://ggzy.ah.gov.cn/",
                official_url="https://ggzy.ah.gov.cn/",
                list_url="https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
                is_active=True,
            )
            if include_inactive_source:
                _seed_source(
                    session,
                    code="ggzy_gov_cn_deal",
                    name="全国公共资源交易平台（政府采购）",
                    base_url="https://www.ggzy.gov.cn/",
                    official_url="https://www.ggzy.gov.cn/",
                    list_url="https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02",
                    is_active=False,
                )
            session.commit()

        self.failed_job_id: int | None = None
        if seed_failed_job:
            self.failed_job_id = _seed_failed_job(self.session_factory)

        self._previous_overrides = dict(app.dependency_overrides)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            username="pytest-admin",
            role=UserRole.admin,
        )

        self.port = _pick_free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
        )
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = lambda: None
        self.server_thread = Thread(target=self.server.run, daemon=True)
        self.server_thread.start()
        _wait_for_server(self.base_url)

    def close(self) -> None:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self._previous_overrides)
        self.server.should_exit = True
        self.server_thread.join(timeout=10)
        self.engine.dispose()


@pytest.fixture
def browser():
    with sync_playwright() as playwright_instance:
        try:
            browser_instance = playwright_instance.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Playwright Chromium is unavailable: {exc}")
        try:
            yield browser_instance
        finally:
            browser_instance.close()


def test_source_sites_manual_crawl_e2e_redirects_and_refreshes_status(tmp_path: Path, browser) -> None:
    runtime = AdminE2ERuntime(tmp_path=tmp_path)
    context = browser.new_context(base_url=runtime.base_url)
    page = context.new_page()
    allow_navigation = Event()

    def delay_manual_crawl(route: Any) -> None:
        allow_navigation.wait(timeout=5)
        route.continue_()

    page.route("**/admin/sources/anhui_ggzy_zfcg/manual-crawl", delay_manual_crawl)
    try:
        page.goto("/admin/source-sites", wait_until="networkidle")

        state = page.evaluate(
            """() => {
                const button = document.querySelector('[data-testid="manual-crawl-btn-anhui_ggzy_zfcg"]');
                if (!button) {
                    throw new Error('manual crawl button not found');
                }
                button.click();
                return {
                    disabled: button.disabled,
                    text: button.textContent,
                };
            }"""
        )
        assert state == {"disabled": True, "text": "提交中"}
        allow_navigation.set()

        page.wait_for_url(f"{runtime.base_url}/admin/crawl-jobs?source_code=anhui_ggzy_zfcg&created_job_id=1")
        expect(page.get_by_test_id("created-job-banner")).to_contain_text("已创建手动抓取任务 #1")
        expect(page.get_by_test_id("crawl-jobs-live-refresh")).to_be_visible()
        expect(page.get_by_test_id("crawl-job-status-1")).to_contain_text("排队中")

        worker = Thread(
            target=_finish_job_after_delay,
            args=(runtime.session_factory,),
            kwargs={"job_id": 1, "delay_seconds": 0.5},
            daemon=True,
        )
        worker.start()

        expect(page.get_by_test_id("crawl-job-status-1")).to_contain_text("已完成", timeout=9000)
        expect(page.get_by_test_id("crawl-job-progress-1")).to_contain_text("已完成", timeout=9000)
        expect(page.get_by_test_id("crawl-jobs-live-refresh")).to_have_count(0, timeout=9000)
    finally:
        page.unroute("**/admin/sources/anhui_ggzy_zfcg/manual-crawl", delay_manual_crawl)
        context.close()
        runtime.close()


def test_source_detail_schedule_config_e2e_updates_and_persists(tmp_path: Path, browser) -> None:
    runtime = AdminE2ERuntime(tmp_path=tmp_path)
    context = browser.new_context(base_url=runtime.base_url)
    page = context.new_page()
    try:
        page.goto("/admin/sources/anhui_ggzy_zfcg", wait_until="networkidle")

        page.get_by_label("是否启用自动抓取").select_option("true")
        page.get_by_label("抓取周期").select_option("3")
        page.get_by_test_id("source-schedule-submit").click()

        page.wait_for_url(re.compile(rf"{re.escape(runtime.base_url)}/admin/sources/anhui_ggzy_zfcg\?schedule_updated=1$"))
        expect(page.get_by_test_id("source-schedule-updated-banner")).to_have_text("配置已更新")
        expect(page.get_by_text("当前调度摘要：已启用 / 3天一次", exact=False)).to_be_visible()

        with runtime.session_factory() as session:
            source = session.query(SourceSite).filter(SourceSite.code == "anhui_ggzy_zfcg").one()
            assert source.schedule_enabled is True
            assert int(source.schedule_days) == 3
    finally:
        context.close()
        runtime.close()


def test_crawl_jobs_retry_e2e_disables_button_and_creates_retry_job(tmp_path: Path, browser) -> None:
    runtime = AdminE2ERuntime(tmp_path=tmp_path, seed_failed_job=True)
    assert runtime.failed_job_id == 1
    context = browser.new_context(base_url=runtime.base_url)
    page = context.new_page()
    allow_navigation = Event()

    def delay_retry(route: Any) -> None:
        allow_navigation.wait(timeout=5)
        route.continue_()

    page.route("**/admin/crawl-jobs/1/retry", delay_retry)
    try:
        page.goto("/admin/crawl-jobs", wait_until="networkidle")

        state = page.evaluate(
            """() => {
                const button = document.querySelector('[data-testid="retry-job-btn-1"]');
                if (!button) {
                    throw new Error('retry button not found');
                }
                button.click();
                return {
                    disabled: button.disabled,
                    text: button.textContent,
                };
            }"""
        )
        assert state == {"disabled": True, "text": "提交中"}
        allow_navigation.set()

        page.wait_for_url(f"{runtime.base_url}/admin/crawl-jobs?retry_created_job_id=2")
        expect(page.get_by_test_id("retry-created-job-banner")).to_contain_text("重试任务已创建：#2")
        expect(page.get_by_test_id("crawl-job-retry-state-1")).to_contain_text("已重试")
        expect(page.get_by_test_id("crawl-job-row-2")).to_be_visible()

        with runtime.session_factory() as session:
            retry_job = session.get(CrawlJob, 2)
            assert retry_job is not None
            assert retry_job.retry_of_job_id == 1
            assert retry_job.job_type == "manual_retry"
    finally:
        page.unroute("**/admin/crawl-jobs/1/retry", delay_retry)
        context.close()
        runtime.close()


def test_source_sites_manual_crawl_e2e_shows_error_for_inactive_source(tmp_path: Path, browser) -> None:
    runtime = AdminE2ERuntime(tmp_path=tmp_path, include_inactive_source=True)
    context = browser.new_context(base_url=runtime.base_url)
    page = context.new_page()
    try:
        page.goto("/admin/source-sites", wait_until="networkidle")
        page.get_by_test_id("manual-crawl-btn-ggzy_gov_cn_deal").click()

        expect(page.get_by_test_id("manual-crawl-error-banner")).to_contain_text("来源未启用，无法手动抓取")
        expect(page.get_by_test_id("manual-crawl-error-banner")).to_contain_text("ggzy_gov_cn_deal")
        expect(page.get_by_test_id("source-row-ggzy_gov_cn_deal")).to_contain_text("已停用")
    finally:
        context.close()
        runtime.close()
