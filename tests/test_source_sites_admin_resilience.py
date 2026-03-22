from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import app.models  # noqa: F401
from app.api.endpoints import admin_sources
from app.api.schemas import SourceSiteAdminRow
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import CrawlJob, SourceSite


def _seed_source(session_factory: sessionmaker) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="安徽省公共资源交易监管网（政府采购）",
                base_url="https://ggzy.ah.gov.cn/",
                official_url="https://ggzy.ah.gov.cn/",
                list_url="https://ggzy.ah.gov.cn/jyxx/002001/002001004/002001004001/",
                description="source sites resilience test",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=10,
                schedule_enabled=False,
                schedule_days=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _build_client(tmp_path: Path, db_name: str) -> tuple[TestClient, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / db_name}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _seed_source(session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, engine


def test_admin_source_sites_page_returns_200(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path, "source_sites_page_200.db")
    try:
        response = client.get("/admin/source-sites")
        assert response.status_code == 200
        assert "来源网站列表" in response.text
        assert "anhui_ggzy_zfcg" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_source_sites_page_handles_sparse_source_fields(tmp_path: Path, monkeypatch) -> None:
    client, engine = _build_client(tmp_path, "source_sites_sparse_fields.db")
    try:
        sparse_source = SimpleNamespace(
            id=2,
            code="sparse_source",
            name="Sparse Source",
            base_url="https://sparse.example.com/",
        )
        monkeypatch.setattr(admin_sources.SourceSiteService, "list_sources", lambda self: [sparse_source])
        monkeypatch.setattr(admin_sources.SourceHealthService, "build_health_map", lambda self, _: {})
        monkeypatch.setattr(admin_sources.SourceOpsService, "list_source_ops", lambda self, recent_hours=24: [])
        monkeypatch.setattr(
            admin_sources,
            "_build_source_sites_list_row",
            lambda **_: {
                "code": "sparse_source",
                "name": "Sparse Source",
                "official_url": "https://sparse.example.com/",
            },
        )

        response = client.get("/admin/source-sites")
        assert response.status_code == 200
        assert "Sparse Source" in response.text
        assert "成功 0 / 失败 0 / 新增 0" in response.text
        assert "新增 0 条" in response.text
        assert ">无<" in response.text
        assert 'action="/admin/sources/sparse_source/manual-crawl"' in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_normalize_source_sites_list_row_returns_typed_view_model() -> None:
    source = SimpleNamespace(
        id=2,
        code="typed_source",
        name="Typed Source",
        base_url="https://typed.example.com/",
        schedule_days=3,
        crawl_interval_minutes=120,
        default_max_pages=8,
    )

    row = admin_sources._normalize_source_sites_list_row(
        {
            "code": "typed_source",
            "name": "Typed Source",
            "official_url": "https://typed.example.com/",
        },
        source=source,
    )

    assert isinstance(row, SourceSiteAdminRow)
    assert row.code == "typed_source"
    assert row.name == "Typed Source"
    assert row.list_url == "https://typed.example.com/"
    assert row.crawl_interval_label == "120 分钟"
    assert row.schedule_days_label == "3天一次"
    assert row.today_ops_summary == "成功 0 / 失败 0 / 新增 0"
    assert row.last_retry_label == "无"
    assert row.actions.manual_crawl_post_url == "/admin/sources/typed_source/manual-crawl"
    assert row.actions.crawl_jobs_url == "/admin/crawl-jobs?source_code=typed_source"
    assert row.active_crawl.id is None
    assert row.has_active_crawl is False


def test_admin_source_sites_page_renders_contract_fields_from_view_model(tmp_path: Path, monkeypatch) -> None:
    client, engine = _build_client(tmp_path, "source_sites_contract_fields.db")
    try:
        contract_source = SimpleNamespace(
            id=3,
            code="contract_source",
            name="Contract Source",
            base_url="https://contract.example.com/",
            official_url="https://contract.example.com/",
            list_url="https://contract.example.com/list",
            is_active=True,
            schedule_enabled=True,
            schedule_days=3,
            crawl_interval_minutes=30,
            default_max_pages=20,
        )
        monkeypatch.setattr(admin_sources.SourceSiteService, "list_sources", lambda self: [contract_source])
        monkeypatch.setattr(admin_sources.SourceHealthService, "build_health_map", lambda self, _: {})
        monkeypatch.setattr(admin_sources.SourceOpsService, "list_source_ops", lambda self, recent_hours=24: [])
        monkeypatch.setattr(
            admin_sources,
            "_build_source_sites_list_row",
            lambda **_: {
                "code": "contract_source",
                "name": "Contract Source",
                "business_code": "power_vpp",
                "supported_job_types_label": "manual / backfill",
                "official_url": "https://contract.example.com/",
                "list_url": "https://contract.example.com/list",
                "is_active": True,
                "health_status": "critical",
                "health_badge": "tag-health-critical",
                "health_status_label": "严重",
                "recent_7d_error_count": 2,
                "last_crawl_result": "最近成功",
                "latest_list_items_seen": 15,
                "latest_list_items_unique": 12,
                "latest_list_items_source_duplicates_skipped": 2,
                "latest_detail_pages_fetched": 9,
                "has_source_duplicates_latest": True,
                "last_failure_summary": "网络波动",
                "schedule_enabled": True,
                "schedule_days_label": "3天一次",
                "next_scheduled_run_at": "2026-03-22T10:00:00+00:00",
                "last_schedule_status": "已排队",
                "last_crawled_at": "2026-03-22T08:00:00+00:00",
                "last_new_notice_count": 7,
                "today_ops_summary": "成功 3 / 失败 1 / 新增 7",
                "today_crawl_job_count": 4,
                "last_retry_job_id": 77,
                "last_retry_label": "retry_succeeded",
                "actions": {
                    "manual_crawl_post_url": "/admin/sources/contract_source/manual-crawl",
                    "crawl_jobs_url": "/admin/crawl-jobs?source_code=contract_source",
                    "crawl_errors_url": "/admin/crawl-errors?source_code=contract_source",
                    "config_url": "/admin/sources/contract_source",
                },
            },
        )

        response = client.get("/admin/source-sites")

        assert response.status_code == 200
        assert "Contract Source" in response.text
        assert "power_vpp" in response.text
        assert "manual / backfill" in response.text
        assert "https://contract.example.com/" in response.text
        assert "https://contract.example.com/list" in response.text
        assert "严重" in response.text
        assert "7天错误 2" in response.text
        assert "最近成功" in response.text
        assert "列表 15" in response.text
        assert "唯一 12" in response.text
        assert "列表去重跳过 2" in response.text
        assert "详情 9" in response.text
        assert "源站本次存在重复列表项，系统已自动抑制" in response.text
        assert "网络波动" in response.text
        assert "3天一次" in response.text
        assert "2026-03-22T10:00:00+00:00" in response.text
        assert "已排队" in response.text
        assert "2026-03-22T08:00:00+00:00" in response.text
        assert "新增 7 条" in response.text
        assert "成功 3 / 失败 1 / 新增 7" in response.text
        assert "今日抓取 4 次" in response.text
        assert "retry_succeeded" in response.text
        assert 'href="/admin/crawl-jobs/77"' in response.text
        assert 'action="/admin/sources/contract_source/manual-crawl"' in response.text
        assert 'href="/admin/crawl-jobs?source_code=contract_source"' in response.text
        assert 'href="/admin/crawl-errors?source_code=contract_source"' in response.text
        assert 'href="/admin/sources/contract_source"' in response.text
        assert "row-risk" in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_admin_source_sites_page_shows_live_progress_for_active_schedule_job(tmp_path: Path) -> None:
    client, engine = _build_client(tmp_path, "source_sites_active_job.db")
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        with session_factory() as session:
            session.add(
                CrawlJob(
                    id=99,
                    source_site_id=1,
                    job_type="scheduled",
                    status="running",
                    triggered_by="scheduler",
                    started_at=now,
                    finished_at=None,
                    pages_fetched=3,
                    documents_saved=1,
                    notices_upserted=1,
                    deduplicated_count=0,
                    error_count=0,
                    list_items_seen=12,
                    list_items_unique=12,
                    list_items_source_duplicates_skipped=0,
                    detail_pages_fetched=5,
                    records_inserted=1,
                    records_updated=0,
                    source_duplicates_suppressed=0,
                    message="scheduler running",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        response = client.get("/admin/source-sites")
        assert response.status_code == 200
        assert "自动抓取进行中" in response.text
        assert "自动抓取 #99" in response.text
        assert "抓取详情与入库 / 列表页 3 / 列表项 12 / 唯一项 12 / 详情页 5 / 公告 1 / 归档 1" in response.text
        assert 'data-live-refresh="true"' in response.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
