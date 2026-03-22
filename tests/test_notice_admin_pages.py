from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import NoticeVersion, RawDocument, SourceSite, TenderAttachment, TenderNotice


@dataclass(slots=True)
class SeededAdminNotices:
    notice_1_id: int
    notice_2_id: int
    notice_3_id: int
    notice_1_version_1_id: int
    notice_1_version_2_id: int



def _seed_data(session_factory: sessionmaker) -> SeededAdminNotices:
    now = datetime.now(timezone.utc)

    with session_factory() as session:
        source_anhui = SourceSite(
            id=1,
            code="anhui_ggzy_zfcg",
            name="安徽省公共资源交易监管网（政府采购）",
            base_url="https://ggzy.ah.gov.cn/",
            description="anhui source",
            is_active=True,
            supports_js_render=False,
            crawl_interval_minutes=60,
        )
        source_example = SourceSite(
            id=2,
            code="example_source",
            name="Example Source",
            base_url="https://example.com/",
            description="example source",
            is_active=True,
            supports_js_render=True,
            crawl_interval_minutes=30,
        )
        session.add_all([source_anhui, source_example])

        notice_1 = TenderNotice(
            id=101,
            source_site_id=source_anhui.id,
            external_id="AH-001",
            project_code="LV-001",
            dedup_hash="dedup-ah-001",
            title="低压透明化改造项目公告",
            notice_type="announcement",
            issuer="安徽电力公司",
            region="合肥",
            published_at=now - timedelta(days=2),
            deadline_at=now + timedelta(days=7),
            budget_amount=Decimal("1000000.00"),
            budget_currency="CNY",
            summary="低压透明化项目一期",
            first_published_at=now - timedelta(days=2),
            latest_published_at=now - timedelta(days=1, hours=20),
            current_version_id=None,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=2),
        )
        notice_2 = TenderNotice(
            id=102,
            source_site_id=source_anhui.id,
            external_id="AH-002",
            project_code="LOAD-001",
            dedup_hash="dedup-ah-002",
            title="负荷管理平台采购结果公示",
            notice_type="result",
            issuer="安徽能源集团",
            region="芜湖",
            published_at=now - timedelta(days=1),
            deadline_at=None,
            budget_amount=Decimal("560000.00"),
            budget_currency="CNY",
            summary="负荷管理平台结果",
            first_published_at=now - timedelta(days=1),
            latest_published_at=now - timedelta(days=1),
            current_version_id=None,
            created_at=now - timedelta(hours=30),
            updated_at=now - timedelta(hours=30),
        )
        notice_3 = TenderNotice(
            id=103,
            source_site_id=source_example.id,
            external_id="EX-003",
            project_code="CARBON-001",
            dedup_hash="dedup-ex-003",
            title="碳计量系统变更公告",
            notice_type="change",
            issuer="华东采购中心",
            region="合肥",
            published_at=now - timedelta(days=3),
            deadline_at=now + timedelta(days=3),
            budget_amount=Decimal("800000.00"),
            budget_currency="CNY",
            summary="碳计量变更",
            first_published_at=now - timedelta(days=3),
            latest_published_at=now - timedelta(days=3),
            current_version_id=None,
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(days=3),
        )
        session.add_all([notice_1, notice_2, notice_3])

        raw_doc_v1 = RawDocument(
            id=401,
            source_site_id=source_anhui.id,
            crawl_job_id=None,
            url="https://ggzy.ah.gov.cn/notice/ah-001?v=1",
            normalized_url="https://ggzy.ah.gov.cn/notice/ah-001?v=1",
            url_hash="raw-ah-001-v1",
            content_hash="content-ah-001-v1",
            document_type="html",
            http_status=200,
            mime_type="text/html",
            charset="utf-8",
            title="低压透明化改造项目公告 v1",
            fetched_at=now - timedelta(days=2),
            storage_uri="file:///tmp/raw/ah-001-v1.html",
            content_length=1024,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"version": 1},
        )
        raw_doc_v2 = RawDocument(
            id=402,
            source_site_id=source_anhui.id,
            crawl_job_id=None,
            url="https://ggzy.ah.gov.cn/notice/ah-001?v=2",
            normalized_url="https://ggzy.ah.gov.cn/notice/ah-001?v=2",
            url_hash="raw-ah-001-v2",
            content_hash="content-ah-001-v2",
            document_type="html",
            http_status=200,
            mime_type="text/html",
            charset="utf-8",
            title="低压透明化改造项目公告 v2",
            fetched_at=now - timedelta(days=1, hours=20),
            storage_uri="file:///tmp/raw/ah-001-v2.html",
            content_length=2048,
            is_duplicate_url=False,
            is_duplicate_content=False,
            extra_meta={"version": 2},
        )
        session.add_all([raw_doc_v1, raw_doc_v2])

        version_1 = NoticeVersion(
            id=201,
            notice_id=notice_1.id,
            raw_document_id=raw_doc_v1.id,
            version_no=1,
            is_current=False,
            content_hash="content-ah-001-v1",
            title=notice_1.title,
            notice_type=notice_1.notice_type,
            issuer=notice_1.issuer,
            region=notice_1.region,
            published_at=notice_1.published_at,
            deadline_at=notice_1.deadline_at,
            budget_amount=notice_1.budget_amount,
            budget_currency="CNY",
            structured_data={"source": "anhui", "version": 1},
            change_summary=None,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=2),
        )
        version_2 = NoticeVersion(
            id=204,
            notice_id=notice_1.id,
            raw_document_id=raw_doc_v2.id,
            version_no=2,
            is_current=True,
            content_hash="content-ah-001-v2",
            title="低压透明化改造项目公告（更新）",
            notice_type=notice_1.notice_type,
            issuer=notice_1.issuer,
            region=notice_1.region,
            published_at=notice_1.published_at,
            deadline_at=notice_1.deadline_at,
            budget_amount=notice_1.budget_amount,
            budget_currency="CNY",
            structured_data={"source": "anhui", "version": 2},
            change_summary="补充参数",
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=3),
        )
        session.add_all([version_1, version_2])

        notice_1.current_version_id = version_2.id

        attachment_1 = TenderAttachment(
            id=301,
            source_site_id=source_anhui.id,
            notice_id=notice_1.id,
            notice_version_id=version_1.id,
            raw_document_id=raw_doc_v1.id,
            file_name="招标文件-v1.pdf",
            attachment_type="notice_file",
            file_url="https://ggzy.ah.gov.cn/files/ah-001-bid-v1.pdf",
            url_hash="att-ah-001-1",
            file_hash=None,
            storage_uri="file:///tmp/ah-001-bid-v1.pdf",
            mime_type="application/pdf",
            file_ext="pdf",
            file_size_bytes=12345,
            published_at=notice_1.published_at,
            downloaded_at=None,
            is_deleted=False,
        )
        attachment_2 = TenderAttachment(
            id=302,
            source_site_id=source_anhui.id,
            notice_id=notice_1.id,
            notice_version_id=version_2.id,
            raw_document_id=raw_doc_v2.id,
            file_name="招标文件-v2.pdf",
            attachment_type="notice_file",
            file_url="https://ggzy.ah.gov.cn/files/ah-001-bid-v2.pdf",
            url_hash="att-ah-001-2",
            file_hash=None,
            storage_uri=None,
            mime_type="application/pdf",
            file_ext="pdf",
            file_size_bytes=45678,
            published_at=notice_1.published_at,
            downloaded_at=None,
            is_deleted=False,
        )
        session.add_all([attachment_1, attachment_2])

        session.commit()

    return SeededAdminNotices(
        notice_1_id=notice_1.id,
        notice_2_id=notice_2.id,
        notice_3_id=notice_3.id,
        notice_1_version_1_id=version_1.id,
        notice_1_version_2_id=version_2.id,
    )



def _build_client(tmp_path: Path) -> tuple[TestClient, SeededAdminNotices, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'notice_admin_pages.db'}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    seeded = _seed_data(session_factory)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    return client, seeded, engine


def _insert_cross_source_duplicate_notice(engine: object) -> int:
    now = datetime.now(timezone.utc)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with session_factory() as session:
        duplicate_notice = TenderNotice(
            id=104,
            source_site_id=2,
            external_id="EX-DUP-ADMIN-001",
            project_code="ADMIN-DUP-001",
            dedup_hash="dedup-ah-001",
            title="低压透明化改造项目公告（跨来源重复）",
            notice_type="announcement",
            issuer="华东采购中心",
            region="合肥",
            published_at=now,
            deadline_at=now + timedelta(days=4),
            budget_amount=Decimal("900000.00"),
            budget_currency="CNY",
            summary="admin duplicate",
            first_published_at=now,
            latest_published_at=now,
            current_version_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(duplicate_notice)
        session.commit()
        return int(duplicate_notice.id)



def test_admin_notices_list_page_supports_filter_and_pagination(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        duplicate_notice_id = _insert_cross_source_duplicate_notice(engine)

        response = client.get("/admin/notices")
        assert response.status_code == 200
        assert "招标信息汇总工作台" in response.text
        assert "关键词（标题/发布方/地区）" in response.text
        assert "最近新增：全部" in response.text
        assert "默认去重汇总展示" in response.text
        assert "当前展示模式：去重总展示" in response.text
        assert "原始抓取数" in response.text
        assert "去重后数" in response.text
        assert "最近24小时新增数" in response.text
        assert "查看版本/重复项" in response.text
        assert f"/admin/notices/{duplicate_notice_id}" in response.text
        assert f"/admin/notices/{seeded.notice_2_id}" in response.text
        assert 'href="/notices/export.csv?' in response.text
        assert 'href="/notices/export.json?' in response.text
        assert 'href="/notices/export.xlsx?' in response.text
        assert "低压透明化改造项目公告（跨来源重复）" in response.text
        assert "低压透明化改造项目公告</div>" not in response.text

        no_dedup = client.get("/admin/notices", params={"dedup": "false"})
        assert no_dedup.status_code == 200
        assert "当前展示模式：版本明细展示" in no_dedup.text
        assert f"/admin/notices/{seeded.notice_1_id}" in no_dedup.text
        assert f"/admin/notices/{duplicate_notice_id}" in no_dedup.text

        sorted_by_budget = client.get("/admin/notices", params={"sort_by": "budget_amount", "sort_order": "desc"})
        assert sorted_by_budget.status_code == 200
        body = sorted_by_budget.text
        first_idx = body.find("900000.00")
        second_idx = body.find("800000.00")
        third_idx = body.find("560000.00")
        assert first_idx != -1 and second_idx != -1 and third_idx != -1
        assert first_idx < second_idx < third_idx

        filtered = client.get(
            "/admin/notices",
            params={
                "keyword": "低压",
                "source_code": "anhui_ggzy_zfcg",
                "notice_type": "announcement",
                "region": "合肥",
            },
        )
        assert filtered.status_code == 200
        assert "低压透明化改造项目公告" in filtered.text
        assert "负荷管理平台采购结果公示" not in filtered.text
        assert "keyword=%E4%BD%8E%E5%8E%8B" in filtered.text
        assert "source_code=anhui_ggzy_zfcg" in filtered.text
        assert "notice_type=announcement" in filtered.text
        assert "region=%E5%90%88%E8%82%A5" in filtered.text
        assert "sort_by=published_at" in filtered.text
        assert "sort_order=desc" in filtered.text

        recent = client.get("/admin/notices", params={"recent_hours": 24})
        assert recent.status_code == 200
        assert "最近24小时新增筛选中" in recent.text
        assert "查看全部" in recent.text
        assert f"/admin/notices/{duplicate_notice_id}" in recent.text
        assert f"/admin/notices/{seeded.notice_2_id}" not in recent.text
        assert f"/admin/notices/{seeded.notice_3_id}" not in recent.text
        assert 'href="/notices/export.csv?recent_hours=24' in recent.text
        assert 'href="/notices/export.json?recent_hours=24' in recent.text
        assert 'href="/notices/export.xlsx?recent_hours=24' in recent.text
        assert "最近新增" in recent.text

        paged = client.get(
            "/admin/notices",
            params={"limit": 1, "offset": 1},
        )
        assert paged.status_code == 200
        assert "total=3 | limit=1 | offset=1" in paged.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_admin_notice_detail_page_shows_versions_raw_document_and_attachment_version(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        response = client.get(f"/admin/notices/{seeded.notice_1_id}")
        assert response.status_code == 200
        assert f"公告详情 #{seeded.notice_1_id}" in response.text
        assert "来源信息" in response.text
        assert "版本/重复记录" in response.text
        assert "该公告共" in response.text
        assert "当前版本" in response.text
        assert "历史版本" in response.text
        assert "版本查看器" in response.text
        assert "版本附件列表" in response.text
        assert '"source_code": "anhui_ggzy_zfcg"' in response.text
        assert '"version_no": 2' in response.text

        viewer_default = _between(response.text, "<h1>版本查看器</h1>", "<h1>历史版本</h1>")
        assert "content-ah-001-v2" in viewer_default
        assert "file:///tmp/raw/ah-001-v2.html" in viewer_default
        assert "/admin/raw-documents/402" in viewer_default

        history_region = _between(response.text, "<h1>历史版本</h1>", "<h1>版本附件列表</h1>")
        assert "/admin/raw-documents/401" in history_region
        assert "/admin/raw-documents/402" in history_region

        attachments_default = _between(response.text, "<h1>版本附件列表</h1>", "<h1>原始 JSON</h1>")
        assert "当前版本 version_no=2，展示 1 / 2 条" in attachments_default
        assert "招标文件-v2.pdf" in attachments_default
        assert "招标文件-v1.pdf" not in attachments_default

        by_version_no = client.get(
            f"/admin/notices/{seeded.notice_1_id}",
            params={"version_no": 1},
        )
        assert by_version_no.status_code == 200
        viewer_v1 = _between(by_version_no.text, "<h1>版本查看器</h1>", "<h1>历史版本</h1>")
        assert "content-ah-001-v1" in viewer_v1
        assert "file:///tmp/raw/ah-001-v1.html" in viewer_v1
        attachments_v1 = _between(by_version_no.text, "<h1>版本附件列表</h1>", "<h1>原始 JSON</h1>")
        assert "当前版本 version_no=1，展示 1 / 2 条" in attachments_v1
        assert "招标文件-v1.pdf" in attachments_v1
        assert "招标文件-v2.pdf" not in attachments_v1

        by_version_id = client.get(
            f"/admin/notices/{seeded.notice_1_id}",
            params={"version_id": seeded.notice_1_version_2_id},
        )
        assert by_version_id.status_code == 200
        viewer_v2_by_id = _between(by_version_id.text, "<h1>版本查看器</h1>", "<h1>历史版本</h1>")
        assert "content-ah-001-v2" in viewer_v2_by_id
        attachments_v2_by_id = _between(by_version_id.text, "<h1>版本附件列表</h1>", "<h1>原始 JSON</h1>")
        assert "当前版本 version_no=2，展示 1 / 2 条" in attachments_v2_by_id
        assert "招标文件-v2.pdf" in attachments_v2_by_id

        not_found = client.get("/admin/notices/999999")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _between(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[start_idx:end_idx]
