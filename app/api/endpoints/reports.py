from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import SourceOpsService

router = APIRouter(tags=["reports"])


@router.get("/reports/source-ops.xlsx")
def export_source_ops_report_xlsx(
    recent_hours: int = Query(default=24, ge=1, le=720),
    source_code: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    items = SourceOpsService(session=db).list_source_ops(
        recent_hours=recent_hours,
        source_code=source_code,
    )
    workbook = Workbook()
    default_sheet = workbook.active
    sheet = workbook.create_sheet(title="source_ops")
    if default_sheet is not None:
        workbook.remove(default_sheet)
    sheet.append(
        [
            "source_code",
            "source_name",
            "official_url",
            "is_active",
            "schedule_enabled",
            "schedule_days",
            "today_crawl_job_count",
            "today_success_count",
            "today_failed_count",
            "today_partial_count",
            "today_new_notice_count",
            "last_job_status",
            "last_job_finished_at",
            "last_error_message",
            "last_retry_status",
        ]
    )
    for item in items:
        sheet.append(
            [
                item.source_code,
                item.source_name,
                item.official_url,
                item.is_active,
                item.schedule_enabled,
                item.schedule_days,
                item.today_crawl_job_count,
                item.today_success_count,
                item.today_failed_count,
                item.today_partial_count,
                item.today_new_notice_count,
                item.last_job_status or "",
                _fmt_datetime(item.last_job_finished_at),
                item.last_error_message or "",
                item.last_retry_status or "",
            ]
        )

    output = BytesIO()
    workbook.save(output)
    filename = f"source-ops-report-{datetime.now(timezone.utc).strftime('%Y%m%d')}.xlsx"
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _fmt_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()
