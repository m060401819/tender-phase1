from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
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
class SeededNotices:
    notice_1_id: int
    notice_2_id: int
    notice_3_id: int
    notice_4_id: int
    notice_1_current_version_id: int
    notice_1_old_version_id: int



def _to_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))



def _seed_data(session_factory: sessionmaker) -> SeededNotices:
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
        )
        notice_4 = TenderNotice(
            id=104,
            source_site_id=source_anhui.id,
            external_id="AH-004",
            project_code="RFID-001",
            dedup_hash="dedup-ah-004",
            title="RFID 识别设备采购公告",
            notice_type="announcement",
            issuer="安徽电网供应中心",
            region="马鞍山",
            published_at=None,
            deadline_at=now + timedelta(days=9),
            budget_amount=Decimal("120000.00"),
            budget_currency="CNY",
            summary="rfid 项目",
            first_published_at=None,
            latest_published_at=None,
            current_version_id=None,
        )
        session.add_all([notice_1, notice_2, notice_3, notice_4])

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

        version_1_old = NoticeVersion(
            id=201,
            notice_id=notice_1.id,
            raw_document_id=raw_doc_v1.id,
            version_no=1,
            is_current=False,
            content_hash="content-ah-001-v1",
            title="低压透明化改造项目公告",
            notice_type="announcement",
            issuer=notice_1.issuer,
            region=notice_1.region,
            published_at=notice_1.published_at,
            deadline_at=notice_1.deadline_at,
            budget_amount=notice_1.budget_amount,
            budget_currency="CNY",
            structured_data={"source": "anhui", "version": 1},
            change_summary=None,
        )
        version_1_current = NoticeVersion(
            id=204,
            notice_id=notice_1.id,
            raw_document_id=raw_doc_v2.id,
            version_no=2,
            is_current=True,
            content_hash="content-ah-001-v2",
            title="低压透明化改造项目公告（更新）",
            notice_type="announcement",
            issuer=notice_1.issuer,
            region=notice_1.region,
            published_at=notice_1.published_at,
            deadline_at=notice_1.deadline_at,
            budget_amount=notice_1.budget_amount,
            budget_currency="CNY",
            structured_data={"source": "anhui", "version": 2},
            change_summary="补充参数",
        )
        version_2 = NoticeVersion(
            id=202,
            notice_id=notice_2.id,
            raw_document_id=None,
            version_no=1,
            is_current=True,
            content_hash="content-ah-002-v1",
            title=notice_2.title,
            notice_type=notice_2.notice_type,
            issuer=notice_2.issuer,
            region=notice_2.region,
            published_at=notice_2.published_at,
            deadline_at=notice_2.deadline_at,
            budget_amount=notice_2.budget_amount,
            budget_currency="CNY",
            structured_data={"source": "anhui", "version": 1},
            change_summary=None,
        )
        version_3 = NoticeVersion(
            id=203,
            notice_id=notice_3.id,
            raw_document_id=None,
            version_no=2,
            is_current=True,
            content_hash="content-ex-003-v2",
            title=notice_3.title,
            notice_type=notice_3.notice_type,
            issuer=notice_3.issuer,
            region=notice_3.region,
            published_at=notice_3.published_at,
            deadline_at=notice_3.deadline_at,
            budget_amount=notice_3.budget_amount,
            budget_currency="CNY",
            structured_data={"source": "example", "version": 2},
            change_summary="补充技术参数",
        )
        session.add_all([version_1_old, version_1_current, version_2, version_3])

        notice_1.current_version_id = version_1_current.id
        notice_2.current_version_id = version_2.id
        notice_3.current_version_id = version_3.id

        attachment_1 = TenderAttachment(
            id=301,
            source_site_id=source_anhui.id,
            notice_id=notice_1.id,
            notice_version_id=version_1_old.id,
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
            notice_version_id=version_1_current.id,
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
        attachment_deleted = TenderAttachment(
            id=303,
            source_site_id=source_anhui.id,
            notice_id=notice_1.id,
            notice_version_id=version_1_current.id,
            raw_document_id=raw_doc_v2.id,
            file_name="已失效附件.zip",
            attachment_type="other",
            file_url="https://ggzy.ah.gov.cn/files/ah-001-deleted.zip",
            url_hash="att-ah-001-3",
            file_hash=None,
            storage_uri=None,
            mime_type="application/zip",
            file_ext="zip",
            file_size_bytes=500,
            published_at=notice_1.published_at,
            downloaded_at=None,
            is_deleted=True,
        )
        session.add_all([attachment_1, attachment_2, attachment_deleted])

        session.commit()

    return SeededNotices(
        notice_1_id=notice_1.id,
        notice_2_id=notice_2.id,
        notice_3_id=notice_3.id,
        notice_4_id=notice_4.id,
        notice_1_current_version_id=version_1_current.id,
        notice_1_old_version_id=version_1_old.id,
    )



def _build_client(tmp_path: Path) -> tuple[TestClient, SeededNotices, object]:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'notice_api.db'}"
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



def test_notices_list_supports_search_filters_sort_and_pagination(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        response = client.get("/notices", params={"limit": 10, "offset": 0})
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 4
        assert [item["id"] for item in payload["items"]] == [
            seeded.notice_2_id,
            seeded.notice_1_id,
            seeded.notice_3_id,
            seeded.notice_4_id,
        ]
        assert payload["items"][0]["source_code"] == "anhui_ggzy_zfcg"
        assert payload["items"][0]["notice_type"] == "result"

        assert _to_decimal(payload["items"][1]["budget_amount"]) == Decimal("1000000.00")
        assert payload["items"][1]["current_version_id"] == seeded.notice_1_current_version_id

        by_title_keyword = client.get("/notices", params={"keyword": "低压透明化"})
        assert by_title_keyword.status_code == 200
        assert by_title_keyword.json()["total"] == 1
        assert by_title_keyword.json()["items"][0]["id"] == seeded.notice_1_id

        by_issuer_keyword = client.get("/notices", params={"keyword": "华东采购中心"})
        assert by_issuer_keyword.status_code == 200
        assert by_issuer_keyword.json()["total"] == 1
        assert by_issuer_keyword.json()["items"][0]["id"] == seeded.notice_3_id

        by_region_keyword = client.get("/notices", params={"keyword": "合肥"})
        assert by_region_keyword.status_code == 200
        assert by_region_keyword.json()["total"] == 2
        assert [item["id"] for item in by_region_keyword.json()["items"]] == [
            seeded.notice_1_id,
            seeded.notice_3_id,
        ]

        by_source = client.get("/notices", params={"source_code": "anhui_ggzy_zfcg"})
        assert by_source.status_code == 200
        assert by_source.json()["total"] == 3

        by_type = client.get("/notices", params={"notice_type": "result"})
        assert by_type.status_code == 200
        assert by_type.json()["total"] == 1
        assert by_type.json()["items"][0]["id"] == seeded.notice_2_id

        by_region_filter = client.get("/notices", params={"region": "合肥"})
        assert by_region_filter.status_code == 200
        assert by_region_filter.json()["total"] == 2

        paged = client.get("/notices", params={"limit": 2, "offset": 1})
        assert paged.status_code == 200
        paged_payload = paged.json()
        assert paged_payload["total"] == 4
        assert [item["id"] for item in paged_payload["items"]] == [
            seeded.notice_1_id,
            seeded.notice_3_id,
        ]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_notice_export_csv_and_json_reuse_filters_and_order(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        csv_response = client.get("/notices/export.csv")
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")

        csv_rows = list(csv.DictReader(StringIO(csv_response.text)))
        assert [int(item["id"]) for item in csv_rows] == [
            seeded.notice_2_id,
            seeded.notice_1_id,
            seeded.notice_3_id,
            seeded.notice_4_id,
        ]
        assert csv_rows[0]["source_code"] == "anhui_ggzy_zfcg"
        assert csv_rows[0]["notice_type"] == "result"
        assert csv_rows[0]["budget_amount"] == "560000.00"
        assert csv_rows[0]["current_version_id"] == "202"

        filtered_csv = client.get(
            "/notices/export.csv",
            params={
                "keyword": "低压",
                "source_code": "anhui_ggzy_zfcg",
                "notice_type": "announcement",
                "region": "合肥",
            },
        )
        filtered_csv_rows = list(csv.DictReader(StringIO(filtered_csv.text)))
        assert len(filtered_csv_rows) == 1
        assert int(filtered_csv_rows[0]["id"]) == seeded.notice_1_id

        json_response = client.get(
            "/notices/export.json",
            params={"source_code": "anhui_ggzy_zfcg"},
        )
        assert json_response.status_code == 200
        assert json_response.headers["content-type"].startswith("application/json")

        json_payload = json_response.json()
        assert [item["id"] for item in json_payload] == [
            seeded.notice_2_id,
            seeded.notice_1_id,
            seeded.notice_4_id,
        ]
        assert json_payload[1]["title"] == "低压透明化改造项目公告"
        assert json_payload[1]["current_version_id"] == seeded.notice_1_current_version_id
        assert _to_decimal(json_payload[1]["budget_amount"]) == Decimal("1000000.00")
        assert "published_at" in json_payload[0]
        assert "deadline_at" in json_payload[0]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_notice_detail_returns_versions_raw_document_attachments_and_source(tmp_path: Path) -> None:
    client, seeded, engine = _build_client(tmp_path)
    try:
        response = client.get(f"/notices/{seeded.notice_1_id}")
        assert response.status_code == 200

        payload = response.json()
        assert payload["id"] == seeded.notice_1_id
        assert payload["source_code"] == "anhui_ggzy_zfcg"
        assert payload["title"] == "低压透明化改造项目公告"
        assert payload["notice_type"] == "announcement"
        assert payload["issuer"] == "安徽电力公司"
        assert payload["region"] == "合肥"
        assert _to_decimal(payload["budget_amount"]) == Decimal("1000000.00")

        assert payload["source"]["code"] == "anhui_ggzy_zfcg"
        assert payload["source"]["name"] == "安徽省公共资源交易监管网（政府采购）"

        current_version = payload["current_version"]
        assert current_version is not None
        assert current_version["id"] == seeded.notice_1_current_version_id
        assert current_version["version_no"] == 2
        assert current_version["is_current"] is True
        assert current_version["content_hash"] == "content-ah-001-v2"
        assert current_version["raw_document_id"] == 402
        assert current_version["raw_document"] is not None
        assert current_version["raw_document"]["id"] == 402
        assert current_version["raw_document"]["document_type"] == "html"

        versions = payload["versions"]
        assert len(versions) == 2
        assert [item["version_no"] for item in versions] == [2, 1]
        assert versions[0]["is_current"] is True
        assert versions[0]["content_hash"] == "content-ah-001-v2"
        assert versions[0]["raw_document_id"] == 402
        assert versions[0]["raw_document"]["storage_uri"] == "file:///tmp/raw/ah-001-v2.html"
        assert versions[1]["is_current"] is False
        assert versions[1]["content_hash"] == "content-ah-001-v1"
        assert versions[1]["raw_document_id"] == 401

        attachments = payload["attachments"]
        assert len(attachments) == 2
        assert {item["file_name"] for item in attachments} == {"招标文件-v1.pdf", "招标文件-v2.pdf"}
        assert {item["notice_version_id"] for item in attachments} == {
            seeded.notice_1_old_version_id,
            seeded.notice_1_current_version_id,
        }

        not_found = client.get("/notices/999999")
        assert not_found.status_code == 404
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
