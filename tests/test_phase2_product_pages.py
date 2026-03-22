from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite, TenderNotice


def _seed_data(session_factory: sessionmaker) -> None:
    now = datetime.combine(datetime.now(timezone.utc).date(), time(hour=9), tzinfo=timezone.utc)

    with session_factory() as session:
        source_1 = SourceSite(
            id=1,
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="phase2 source 1",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=1440,
            default_max_pages=2,
            schedule_enabled=True,
            schedule_days=3,
            next_scheduled_run_at=now + timedelta(days=3),
            last_scheduled_run_at=now - timedelta(days=1),
            last_schedule_status="succeeded",
        )
        source_2 = SourceSite(
            id=2,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            description="phase2 source 2",
            is_active=False,
            supports_js_render=True,
            crawl_interval_minutes=10080,
            default_max_pages=1,
            schedule_enabled=False,
            schedule_days=7,
            next_scheduled_run_at=None,
            last_scheduled_run_at=None,
            last_schedule_status=None,
        )
        session.add_all([source_1, source_2])

        session.add(
            CrawlJob(
                id=901,
                source_site_id=source_1.id,
                job_type="manual",
                status="succeeded",
                triggered_by="test",
                started_at=now,
                finished_at=now + timedelta(minutes=3),
                pages_fetched=3,
                documents_saved=3,
                notices_upserted=7,
                deduplicated_count=0,
                error_count=0,
                message="ok",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            CrawlJob(
                id=902,
                source_site_id=source_2.id,
                job_type="manual",
                status="failed",
                triggered_by="test",
                started_at=now - timedelta(hours=6),
                finished_at=now - timedelta(hours=5, minutes=30),
                pages_fetched=1,
                documents_saved=1,
                notices_upserted=0,
                deduplicated_count=0,
                error_count=1,
                message="network timeout",
                created_at=now - timedelta(hours=6),
                updated_at=now - timedelta(hours=6),
            )
        )

        session.add(
            TenderNotice(
                id=1001,
                source_site_id=source_1.id,
                external_id="PH2-001",
                project_code="PH2-001",
                dedup_hash="dedup-ph2-001",
                title="phase2 recent notice",
                notice_type="announcement",
                issuer="issuer",
                region="合肥",
                published_at=now,
                deadline_at=now + timedelta(days=7),
                budget_amount=None,
                budget_currency="CNY",
                summary=None,
                first_published_at=now,
                latest_published_at=now,
                current_version_id=None,
                created_at=now,
                updated_at=now,
            )
        )

        session.commit()


def _build_client(tmp_path: Path) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'phase2_product_pages.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _seed_data(session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, engine


def test_admin_home_page_exposes_product_entrypoints(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/home")
        assert response.status_code == 200
        assert "系统总览 Dashboard" in response.text
        assert "今日新增" in response.text
        assert "最近24小时新增" in response.text
        assert "/admin/source-sites" in response.text
        assert "/admin/notices" in response.text
        assert "进入招标信息工作台" in response.text
        assert "打开 /admin/notices" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_source_sites_page_shows_business_fields_and_manual_trigger_entry(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path)
    try:
        response = client.get("/admin/source-sites")
        assert response.status_code == 200
        assert "来源网站列表" in response.text
        assert "新增来源网站" in response.text
        assert "/admin/sources/new" in response.text
        assert "前往 /admin/notices" in response.text
        assert "最近24小时新增" in response.text
        assert "来源名称" in response.text
        assert "官网网址" in response.text
        assert "健康状态" in response.text
        assert "最近抓取结果" in response.text
        assert "最近失败原因摘要" in response.text
        assert "自动抓取" in response.text
        assert "抓取周期" in response.text
        assert "下次抓取时间" in response.text
        assert "最近调度结果" in response.text
        assert "上次抓取时间" in response.text
        assert "上次新增条数" in response.text
        assert "今日运营摘要" in response.text
        assert "最近一次重试" in response.text
        assert '/reports/source-ops.xlsx?recent_hours=24' in response.text

        assert "3天一次" in response.text
        assert "7天一次" in response.text
        assert "succeeded" in response.text
        assert "正常" in response.text
        assert "异常" in response.text
        assert "新增 7 条" in response.text
        assert "新增 0 条" in response.text
        assert "row-hot" in response.text

        assert "https://ggzy.ah.gov.cn/" in response.text
        assert 'action="/admin/sources/anhui_ggzy_zfcg/manual-crawl"' in response.text
        assert "手动抓取" in response.text
        assert "/admin/crawl-jobs?source_code=anhui_ggzy_zfcg" in response.text
        assert "/admin/crawl-errors?source_code=anhui_ggzy_zfcg" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
