from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.api.schemas import (
    NoticeAttachmentResponse,
    NoticeDetailResponse,
    NoticeListItemResponse,
    NoticeListResponse,
    NoticeSourceResponse,
    NoticeType,
    NoticeVersionResponse,
    RawDocumentSummaryResponse,
)
from app.db.session import get_db
from app.repositories import NoticeListItemRecord, NoticeRepository, NoticeVersionRecord
from app.services import NoticeQueryService

router = APIRouter(tags=["notices"])


@router.get("/notices", response_model=NoticeListResponse)
def list_notices(
    keyword: str | None = Query(default=None),
    source_code: str | None = Query(default=None),
    notice_type: NoticeType | None = Query(default=None),
    region: str | None = Query(default=None),
    recent_hours: int | None = Query(default=None, ge=1, le=720),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    dedup: bool = Query(default=True),
    sort_by: str = Query(default="published_at"),
    sort_order: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> NoticeListResponse:
    result = _build_notice_service(db).list_notices(
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )

    return NoticeListResponse(
        items=[_to_notice_list_item_response(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/notices/export.csv")
def export_notices_csv(
    keyword: str | None = Query(default=None),
    source_code: str | None = Query(default=None),
    notice_type: NoticeType | None = Query(default=None),
    region: str | None = Query(default=None),
    recent_hours: int | None = Query(default=None, ge=1, le=720),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    dedup: bool = Query(default=True),
    sort_by: str = Query(default="published_at"),
    sort_order: str = Query(default="desc"),
    db: Session = Depends(get_db),
) -> Response:
    items = _load_notice_export_items(
        db=db,
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    headers = [
        "id",
        "source_code",
        "title",
        "notice_type",
        "issuer",
        "region",
        "published_at",
        "deadline_at",
        "budget_amount",
        "current_version_id",
    ]

    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    for item in items:
        writer.writerow(
            [
                item.id,
                item.source_code,
                item.title,
                item.notice_type,
                item.issuer or "",
                item.region or "",
                _export_csv_datetime(item.published_at),
                _export_csv_datetime(item.deadline_at),
                _export_csv_decimal(item.budget_amount),
                item.current_version_id if item.current_version_id is not None else "",
            ]
        )

    return Response(
        content=stream.getvalue(),
        media_type="text/csv; charset=utf-8",
    )


@router.get("/notices/export.json")
def export_notices_json(
    keyword: str | None = Query(default=None),
    source_code: str | None = Query(default=None),
    notice_type: NoticeType | None = Query(default=None),
    region: str | None = Query(default=None),
    recent_hours: int | None = Query(default=None, ge=1, le=720),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    dedup: bool = Query(default=True),
    sort_by: str = Query(default="published_at"),
    sort_order: str = Query(default="desc"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    items = _load_notice_export_items(
        db=db,
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    payload = [
        {
            "id": item.id,
            "source_code": item.source_code,
            "title": item.title,
            "notice_type": item.notice_type,
            "issuer": item.issuer,
            "region": item.region,
            "published_at": item.published_at,
            "deadline_at": item.deadline_at,
            "budget_amount": _export_json_decimal(item.budget_amount),
            "current_version_id": item.current_version_id,
        }
        for item in items
    ]
    return JSONResponse(
        content=jsonable_encoder(payload),
        media_type="application/json",
    )


@router.get("/notices/export.xlsx")
def export_notices_xlsx(
    keyword: str | None = Query(default=None),
    source_code: str | None = Query(default=None),
    notice_type: NoticeType | None = Query(default=None),
    region: str | None = Query(default=None),
    recent_hours: int | None = Query(default=None, ge=1, le=720),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    dedup: bool = Query(default=True),
    sort_by: str = Query(default="published_at"),
    sort_order: str = Query(default="desc"),
    db: Session = Depends(get_db),
) -> Response:
    items = _load_notice_export_items(
        db=db,
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type.value if notice_type else None,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    headers = [
        "id",
        "source_code",
        "title",
        "notice_type",
        "issuer",
        "region",
        "published_at",
        "deadline_at",
        "budget_amount",
        "current_version_id",
    ]
    workbook = Workbook()
    default_sheet = workbook.active
    sheet = workbook.create_sheet(title="notices")
    if default_sheet is not None:
        workbook.remove(default_sheet)
    sheet.append(headers)
    for item in items:
        sheet.append(
            [
                item.id,
                item.source_code,
                item.title,
                item.notice_type,
                item.issuer or "",
                item.region or "",
                _export_csv_datetime(item.published_at),
                _export_csv_datetime(item.deadline_at),
                _export_csv_decimal(item.budget_amount),
                item.current_version_id if item.current_version_id is not None else "",
            ]
        )

    output = BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="notices.xlsx"'},
    )


@router.get("/notices/{notice_id}", response_model=NoticeDetailResponse)
def get_notice_detail(notice_id: int, db: Session = Depends(get_db)) -> NoticeDetailResponse:
    item = _build_notice_service(db).get_notice_detail(notice_id)
    if item is None:
        raise HTTPException(status_code=404, detail="notice not found")

    return NoticeDetailResponse(
        id=item.id,
        source_site_id=item.source_site_id,
        source_code=item.source_code,
        external_id=item.external_id,
        project_code=item.project_code,
        title=item.title,
        notice_type=_to_notice_type(item.notice_type),
        issuer=item.issuer,
        region=item.region,
        published_at=item.published_at,
        deadline_at=item.deadline_at,
        budget_amount=item.budget_amount,
        budget_currency=item.budget_currency,
        summary=item.summary,
        first_published_at=item.first_published_at,
        latest_published_at=item.latest_published_at,
        current_version_id=item.current_version_id,
        source=NoticeSourceResponse(
            id=item.source.id,
            code=item.source.code,
            name=item.source.name,
            base_url=item.source.base_url,
            is_active=item.source.is_active,
            supports_js_render=item.source.supports_js_render,
            crawl_interval_minutes=item.source.crawl_interval_minutes,
        ),
        current_version=(
            _to_version_response(item.current_version)
            if item.current_version is not None
            else None
        ),
        versions=[_to_version_response(version) for version in item.versions],
        attachments=[
            NoticeAttachmentResponse(
                id=attachment.id,
                notice_version_id=attachment.notice_version_id,
                file_name=attachment.file_name,
                file_url=attachment.file_url,
                attachment_type=attachment.attachment_type,
                mime_type=attachment.mime_type,
                file_size_bytes=attachment.file_size_bytes,
                storage_uri=attachment.storage_uri,
            )
            for attachment in item.attachments
        ],
    )


def _to_version_response(item: NoticeVersionRecord) -> NoticeVersionResponse:
    return NoticeVersionResponse(
        id=item.id,
        notice_id=item.notice_id,
        raw_document_id=item.raw_document_id,
        version_no=item.version_no,
        is_current=item.is_current,
        content_hash=item.content_hash,
        title=item.title,
        notice_type=_to_notice_type(item.notice_type),
        issuer=item.issuer,
        region=item.region,
        published_at=item.published_at,
        deadline_at=item.deadline_at,
        budget_amount=item.budget_amount,
        budget_currency=item.budget_currency,
        change_summary=item.change_summary,
        structured_data=item.structured_data,
        raw_document=(
            RawDocumentSummaryResponse(
                id=item.raw_document.id,
                document_type=item.raw_document.document_type,
                fetched_at=item.raw_document.fetched_at,
                storage_uri=item.raw_document.storage_uri,
            )
            if item.raw_document is not None
            else None
        ),
    )


def _build_notice_service(db: Session) -> NoticeQueryService:
    return NoticeQueryService(repository=NoticeRepository(db))


def _load_notice_export_items(
    *,
    db: Session,
    keyword: str | None,
    source_code: str | None,
    notice_type: str | None,
    region: str | None,
    recent_hours: int | None,
    date_from: date | None,
    date_to: date | None,
    dedup: bool,
    sort_by: str,
    sort_order: str,
) -> list[NoticeListItemRecord]:
    return _build_notice_service(db).list_notices_for_export(
        keyword=keyword,
        source_code=source_code,
        notice_type=notice_type,
        region=region,
        recent_hours=recent_hours,
        date_from=date_from,
        date_to=date_to,
        dedup=dedup,
        sort_by=sort_by,
        sort_order=sort_order,
    )


def _to_notice_list_item_response(item: NoticeListItemRecord) -> NoticeListItemResponse:
    return NoticeListItemResponse(
        id=item.id,
        source_code=item.source_code,
        source_name=item.source_name,
        title=item.title,
        notice_type=_to_notice_type(item.notice_type),
        issuer=item.issuer,
        region=item.region,
        published_at=item.published_at,
        deadline_at=item.deadline_at,
        budget_amount=item.budget_amount,
        current_version_id=item.current_version_id,
        duplicate_count=item.duplicate_count,
        is_recent_new=item.is_recent_new,
    )


def _export_csv_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _export_csv_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def _export_json_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _to_notice_type(value: str) -> NoticeType:
    return NoticeType(value)
