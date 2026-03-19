from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import mimetypes
from urllib.parse import urlparse, urlsplit, unquote

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings as app_settings
from app.models import (
    CrawlError,
    NoticeVersion,
    RawDocument,
    SourceSite,
    TenderAttachment,
    TenderNotice,
)
from tender_crawler.services import DeduplicationService
from tender_crawler.writers.base import BaseErrorWriter, BaseNoticeWriter, BaseRawDocumentWriter

DEDUP_SERVICE = DeduplicationService()


def resolve_database_url(config: object) -> str:
    """Resolve crawler database url from Scrapy settings/env/app settings."""
    settings_url = None
    if hasattr(config, "get"):
        settings_url = config.get("CRAWLER_DATABASE_URL")

    return (
        (str(settings_url).strip() if settings_url else "")
        or os.getenv("CRAWLER_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
        or app_settings.database_url
    )


class SqlAlchemyWriterContext:
    """Shared SQLAlchemy context for crawler writers."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._source_cache: dict[str, int] = {}
        self._closed = False

    def session(self) -> Session:
        return self.session_factory()

    def close(self) -> None:
        if self._closed:
            return
        self.engine.dispose()
        self._closed = True

    def source_site_id(
        self,
        session: Session,
        *,
        source_code: str,
        source_name: str | None,
        source_url: str | None,
    ) -> int:
        cache_key = source_code
        cached = self._source_cache.get(cache_key)
        if cached is not None:
            return cached

        source = session.scalar(select(SourceSite).where(SourceSite.code == source_code))
        if source is None:
            source = SourceSite(
                **_model_create_kwargs(
                    session,
                    SourceSite,
                    code=source_code,
                    name=source_name or source_code,
                    base_url=source_url or "https://example.com",
                    description="auto-created by crawler",
                    is_active=True,
                    supports_js_render=False,
                    crawl_interval_minutes=60,
                )
            )
            session.add(source)
            session.flush()

        self._source_cache[cache_key] = source.id
        return source.id


class SqlAlchemyRawDocumentWriter(BaseRawDocumentWriter):
    def __init__(self, context: SqlAlchemyWriterContext) -> None:
        self.context = context

    def close(self) -> None:
        self.context.close()

    def write_raw_document(self, item: dict) -> None:
        item = DEDUP_SERVICE.normalize_raw_document_item(item)
        with self.context.session() as session:
            try:
                source_site_id = self.context.source_site_id(
                    session,
                    source_code=_as_str(item.get("source_code")) or "unknown_source",
                    source_name=_as_str(item.get("source_site_name")),
                    source_url=_as_str(item.get("source_site_url")) or _guess_base_url(item),
                )

                url_hash = _as_str(item.get("url_hash"))
                if not url_hash:
                    return

                existing = session.scalar(
                    select(RawDocument).where(
                        RawDocument.source_site_id == source_site_id,
                        RawDocument.url_hash == url_hash,
                    )
                )

                content_hash = _as_str(item.get("content_hash"))
                duplicate_content_id = None
                if content_hash:
                    duplicate_content_id = session.scalar(
                        select(RawDocument.id)
                        .where(
                            RawDocument.source_site_id == source_site_id,
                            RawDocument.content_hash == content_hash,
                        )
                        .limit(1)
                    )

                fetched_at = _as_datetime(item.get("fetched_at")) or datetime.now(timezone.utc)
                payload = {
                    "crawl_job_id": _as_int(item.get("crawl_job_id")),
                    "url": _as_str(item.get("url")) or "",
                    "normalized_url": _as_str(item.get("normalized_url")) or _as_str(item.get("url")) or "",
                    "url_hash": url_hash,
                    "content_hash": content_hash,
                    "document_type": _as_str(item.get("document_type")) or "html",
                    "http_status": _as_int(item.get("http_status")),
                    "mime_type": _as_str(item.get("mime_type")),
                    "charset": _as_str(item.get("charset")),
                    "title": _as_str(item.get("title")),
                    "fetched_at": fetched_at,
                    "storage_uri": _as_str(item.get("storage_uri")) or "",
                    "content_length": _as_int(item.get("content_length")),
                    "extra_meta": item.get("extra_meta") if isinstance(item.get("extra_meta"), dict) else None,
                }

                is_dup_content = bool(
                    duplicate_content_id is not None
                    and (existing is None or duplicate_content_id != existing.id)
                )

                if existing is None:
                    record = RawDocument(
                        **_model_create_kwargs(
                            session,
                            RawDocument,
                            source_site_id=source_site_id,
                            is_duplicate_url=False,
                            is_duplicate_content=is_dup_content,
                            **payload,
                        )
                    )
                    session.add(record)
                else:
                    for key, value in payload.items():
                        setattr(existing, key, value)
                    existing.is_duplicate_url = True
                    existing.is_duplicate_content = is_dup_content

                session.commit()
            except Exception:
                session.rollback()
                raise


class SqlAlchemyNoticeWriter(BaseNoticeWriter):
    def __init__(self, context: SqlAlchemyWriterContext) -> None:
        self.context = context

    def close(self) -> None:
        self.context.close()

    def write_notice(self, item: dict) -> None:
        item = DEDUP_SERVICE.normalize_notice_item(item)
        with self.context.session() as session:
            try:
                source_site_id = self.context.source_site_id(
                    session,
                    source_code=_as_str(item.get("source_code")) or "unknown_source",
                    source_name=_as_str(item.get("source_site_name")),
                    source_url=_as_str(item.get("source_site_url")) or _guess_base_url(item),
                )

                notice = _resolve_notice(session, source_site_id=source_site_id, item=item)
                if notice is None:
                    return

                _apply_notice_fields(notice, item)
                session.commit()
            except Exception:
                session.rollback()
                raise

    def write_notice_version(self, item: dict) -> None:
        item = DEDUP_SERVICE.normalize_notice_item(item)
        with self.context.session() as session:
            try:
                source_site_id = self.context.source_site_id(
                    session,
                    source_code=_as_str(item.get("source_code")) or "unknown_source",
                    source_name=_as_str(item.get("source_site_name")),
                    source_url=_as_str(item.get("source_site_url")) or _guess_base_url(item),
                )

                notice = _resolve_notice(session, source_site_id=source_site_id, item=item)
                if notice is None:
                    return

                _apply_notice_fields(notice, item)

                version = _resolve_notice_version(session, notice_id=notice.id, item=item)
                if version is None:
                    return

                raw_document_id = None
                raw_url_hash = _as_str(item.get("raw_document_url_hash"))
                if raw_url_hash:
                    raw_document_id = session.scalar(
                        select(RawDocument.id)
                        .where(
                            RawDocument.source_site_id == source_site_id,
                            RawDocument.url_hash == raw_url_hash,
                        )
                        .limit(1)
                    )

                if version.version_no is None:
                    version.version_no = _as_int(item.get("version_no")) or 1
                version.is_current = _as_bool(item.get("is_current"), default=True)
                version.content_hash = _as_str(item.get("content_hash")) or version.content_hash
                version.title = _as_str(item.get("title")) or notice.title
                version.notice_type = _normalize_notice_type(_as_str(item.get("notice_type")) or notice.notice_type)
                version.issuer = _as_str(item.get("issuer"))
                version.region = _as_str(item.get("region"))
                version.published_at = _as_datetime(item.get("published_at"))
                version.deadline_at = _as_datetime(item.get("deadline_at"))
                version.budget_amount = _as_decimal(item.get("budget_amount"))
                version.budget_currency = _as_str(item.get("budget_currency")) or "CNY"
                version.change_summary = _as_str(item.get("change_summary"))
                version.raw_document_id = raw_document_id

                structured_data = item.get("structured_data") if isinstance(item.get("structured_data"), dict) else {}
                structured_data = dict(structured_data)
                structured_data.update(
                    {
                        "source_site_name": _as_str(item.get("source_site_name")),
                        "source_site_url": _as_str(item.get("source_site_url")),
                        "list_page_url": _as_str(item.get("list_page_url")),
                        "detail_page_url": _as_str(item.get("detail_page_url")),
                        "content_text": _as_str(item.get("content_text")),
                    }
                )
                version.structured_data = {k: v for k, v in structured_data.items() if v is not None}

                session.flush()

                if version.is_current:
                    session.execute(
                        update(NoticeVersion)
                        .where(
                            NoticeVersion.notice_id == notice.id,
                            NoticeVersion.id != version.id,
                        )
                        .values(is_current=False)
                    )
                    notice.current_version_id = version.id

                if version.published_at:
                    published = _coerce_utc_datetime(version.published_at)
                    first = _coerce_utc_datetime(notice.first_published_at)
                    latest = _coerce_utc_datetime(notice.latest_published_at)
                    if published is not None:
                        if first is None or published < first:
                            notice.first_published_at = published
                        if latest is None or published > latest:
                            notice.latest_published_at = published

                session.commit()
            except Exception:
                session.rollback()
                raise

    def write_attachment(self, item: dict) -> None:
        item = DEDUP_SERVICE.normalize_notice_item(item)
        item = DEDUP_SERVICE.normalize_attachment_item(item)
        with self.context.session() as session:
            try:
                source_site_id = self.context.source_site_id(
                    session,
                    source_code=_as_str(item.get("source_code")) or "unknown_source",
                    source_name=_as_str(item.get("source_site_name")),
                    source_url=_as_str(item.get("source_site_url")) or _guess_base_url(item),
                )

                notice = _resolve_notice(session, source_site_id=source_site_id, item=item)
                if notice is None:
                    return

                _apply_notice_fields(notice, item)

                url_hash = _as_str(item.get("url_hash"))
                file_url = _as_str(item.get("file_url"))
                file_name = _as_str(item.get("file_name")) or _infer_attachment_file_name(file_url)
                if not url_hash or not file_url or not file_name:
                    session.commit()
                    return

                attachment = session.scalar(
                    select(TenderAttachment).where(
                        TenderAttachment.source_site_id == source_site_id,
                        TenderAttachment.url_hash == url_hash,
                    )
                )

                notice_version_id = None
                version_no = _as_int(item.get("notice_version_no"))
                if version_no is not None:
                    notice_version_id = session.scalar(
                        select(NoticeVersion.id)
                        .where(
                            NoticeVersion.notice_id == notice.id,
                            NoticeVersion.version_no == version_no,
                        )
                        .limit(1)
                    )
                if notice_version_id is None:
                    notice_version_id = notice.current_version_id

                raw_document_id = session.scalar(
                    select(RawDocument.id)
                    .where(
                        RawDocument.source_site_id == source_site_id,
                        RawDocument.url_hash == url_hash,
                    )
                    .limit(1)
                )

                file_ext = _as_str(item.get("file_ext")) or _infer_attachment_file_ext(file_name=file_name, file_url=file_url)
                mime_type = _infer_attachment_mime_type(
                    mime_type=_as_str(item.get("mime_type")),
                    file_name=file_name,
                    file_url=file_url,
                )

                if attachment is None:
                    attachment = TenderAttachment(
                        **_model_create_kwargs(
                            session,
                            TenderAttachment,
                            source_site_id=source_site_id,
                            notice_id=notice.id,
                            notice_version_id=notice_version_id,
                            raw_document_id=raw_document_id,
                            file_name=file_name,
                            attachment_type=_normalize_attachment_type(_as_str(item.get("attachment_type"))),
                            file_url=file_url,
                            url_hash=url_hash,
                            file_hash=_as_str(item.get("file_hash")),
                            storage_uri=_as_str(item.get("storage_uri")),
                            mime_type=mime_type,
                            file_ext=file_ext,
                            file_size_bytes=_as_int(item.get("file_size_bytes")),
                            published_at=_as_datetime(item.get("published_at")),
                            downloaded_at=_as_datetime(item.get("downloaded_at")),
                            is_deleted=False,
                        )
                    )
                    session.add(attachment)
                else:
                    attachment.notice_id = notice.id
                    attachment.notice_version_id = notice_version_id
                    attachment.raw_document_id = raw_document_id
                    attachment.file_name = file_name
                    attachment.attachment_type = _normalize_attachment_type(_as_str(item.get("attachment_type")))
                    attachment.file_url = file_url
                    attachment.file_hash = _as_str(item.get("file_hash"))
                    attachment.storage_uri = _as_str(item.get("storage_uri"))
                    attachment.mime_type = mime_type
                    attachment.file_ext = file_ext
                    attachment.file_size_bytes = _as_int(item.get("file_size_bytes"))
                    attachment.published_at = _as_datetime(item.get("published_at"))
                    downloaded_at = _as_datetime(item.get("downloaded_at"))
                    if downloaded_at is not None:
                        attachment.downloaded_at = downloaded_at

                session.commit()
            except Exception:
                session.rollback()
                raise


class SqlAlchemyErrorWriter(BaseErrorWriter):
    def __init__(self, context: SqlAlchemyWriterContext) -> None:
        self.context = context

    def close(self) -> None:
        self.context.close()

    def write_error(self, item: dict) -> None:
        with self.context.session() as session:
            try:
                source_site_id = self.context.source_site_id(
                    session,
                    source_code=_as_str(item.get("source_code")) or "unknown_source",
                    source_name=_as_str(item.get("source_site_name")),
                    source_url=_as_str(item.get("source_site_url")) or _guess_base_url(item),
                )

                error = CrawlError(
                    **_model_create_kwargs(
                        session,
                        CrawlError,
                        source_site_id=source_site_id,
                        crawl_job_id=_as_int(item.get("crawl_job_id")),
                        raw_document_id=None,
                        stage=_normalize_error_stage(_as_str(item.get("stage"))),
                        url=_as_str(item.get("url")),
                        error_type=_as_str(item.get("error_type")) or "UnknownError",
                        error_message=_as_str(item.get("error_message")) or "",
                        traceback=_as_str(item.get("traceback")),
                        retryable=_as_bool(item.get("retryable"), default=False),
                        occurred_at=_as_datetime(item.get("occurred_at")) or datetime.now(timezone.utc),
                        resolved=False,
                    )
                )
                session.add(error)
                session.commit()
            except Exception:
                session.rollback()
                raise


def _resolve_notice(session: Session, *, source_site_id: int, item: dict) -> TenderNotice | None:
    dedup_hash = _as_str(item.get("dedup_hash") or item.get("notice_dedup_hash"))
    external_id = _as_str(item.get("external_id") or item.get("notice_external_id"))

    notice = None
    if dedup_hash:
        notice = session.scalar(
            select(TenderNotice).where(
                TenderNotice.source_site_id == source_site_id,
                TenderNotice.dedup_hash == dedup_hash,
            )
        )
    if notice is None and external_id:
        notice = session.scalar(
            select(TenderNotice).where(
                TenderNotice.source_site_id == source_site_id,
                TenderNotice.external_id == external_id,
            )
        )

    if notice is None:
        title = _as_str(item.get("title"))
        if not title:
            return None
        notice = TenderNotice(
            **_model_create_kwargs(
                session,
                TenderNotice,
                source_site_id=source_site_id,
                external_id=external_id,
                project_code=_as_str(item.get("project_code")),
                dedup_hash=dedup_hash,
                title=title,
                notice_type=_normalize_notice_type(_as_str(item.get("notice_type"))),
                issuer=_as_str(item.get("issuer")),
                region=_as_str(item.get("region")),
                published_at=_as_datetime(item.get("published_at")),
                deadline_at=_as_datetime(item.get("deadline_at")),
                budget_amount=_as_decimal(item.get("budget_amount")),
                budget_currency=_as_str(item.get("budget_currency")) or "CNY",
                summary=_as_str(item.get("summary")) or _as_str(item.get("content_text")),
                first_published_at=_as_datetime(item.get("published_at")),
                latest_published_at=_as_datetime(item.get("published_at")),
                current_version_id=None,
            )
        )
        session.add(notice)
        session.flush()

    return notice


def _apply_notice_fields(notice: TenderNotice, item: dict) -> None:
    title = _as_str(item.get("title"))
    if title:
        notice.title = title

    notice.notice_type = _normalize_notice_type(_as_str(item.get("notice_type")) or notice.notice_type)
    notice.external_id = _as_str(item.get("external_id") or item.get("notice_external_id")) or notice.external_id
    notice.project_code = _as_str(item.get("project_code")) or notice.project_code
    notice.dedup_hash = _as_str(item.get("dedup_hash") or item.get("notice_dedup_hash")) or notice.dedup_hash
    notice.issuer = _as_str(item.get("issuer")) or notice.issuer
    notice.region = _as_str(item.get("region")) or notice.region

    published = _as_datetime(item.get("published_at"))
    if published is not None:
        notice.published_at = published
        first = _coerce_utc_datetime(notice.first_published_at)
        latest = _coerce_utc_datetime(notice.latest_published_at)
        if first is None or published < first:
            notice.first_published_at = published
        if latest is None or published > latest:
            notice.latest_published_at = published

    deadline = _as_datetime(item.get("deadline_at"))
    if deadline is not None:
        notice.deadline_at = deadline

    budget = _as_decimal(item.get("budget_amount"))
    if budget is not None:
        notice.budget_amount = budget

    currency = _as_str(item.get("budget_currency"))
    if currency:
        notice.budget_currency = currency

    summary = _as_str(item.get("summary")) or _as_str(item.get("content_text"))
    if summary:
        notice.summary = summary


def _resolve_notice_version(session: Session, *, notice_id: int, item: dict) -> NoticeVersion | None:
    content_hash = _as_str(item.get("content_hash"))
    requested_version_no = _as_int(item.get("version_no")) or 1

    if content_hash:
        version = session.scalar(
            select(NoticeVersion).where(
                NoticeVersion.notice_id == notice_id,
                NoticeVersion.content_hash == content_hash,
            )
        )
        if version is not None:
            return version

    version = session.scalar(
        select(NoticeVersion).where(
            NoticeVersion.notice_id == notice_id,
            NoticeVersion.version_no == requested_version_no,
        )
    )
    if version is not None:
        if not content_hash or version.content_hash == content_hash:
            return version

        max_version_no = session.scalar(
            select(func.max(NoticeVersion.version_no)).where(NoticeVersion.notice_id == notice_id)
        )
        requested_version_no = (max_version_no or 0) + 1

    title = _as_str(item.get("title"))
    if not title or not content_hash:
        return None

    version = NoticeVersion(
        **_model_create_kwargs(
            session,
            NoticeVersion,
            notice_id=notice_id,
            raw_document_id=None,
            version_no=requested_version_no,
            is_current=_as_bool(item.get("is_current"), default=True),
            content_hash=content_hash,
            title=title,
            notice_type=_normalize_notice_type(_as_str(item.get("notice_type"))),
            issuer=_as_str(item.get("issuer")),
            region=_as_str(item.get("region")),
            published_at=_as_datetime(item.get("published_at")),
            deadline_at=_as_datetime(item.get("deadline_at")),
            budget_amount=_as_decimal(item.get("budget_amount")),
            budget_currency=_as_str(item.get("budget_currency")) or "CNY",
            structured_data=item.get("structured_data") if isinstance(item.get("structured_data"), dict) else {},
            change_summary=_as_str(item.get("change_summary")),
        )
    )
    session.add(version)
    session.flush()

    return version


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def _coerce_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _normalize_notice_type(value: str | None) -> str:
    return DEDUP_SERVICE.normalize_notice_type(value)


def _normalize_attachment_type(value: str | None) -> str:
    if value in {"notice_file", "bid_file", "other"}:
        return value
    return "notice_file"


def _normalize_error_stage(value: str | None) -> str:
    if value in {"fetch", "parse", "persist"}:
        return value
    return "parse"


def _guess_base_url(item: dict) -> str:
    for key in ("source_site_url", "detail_page_url", "source_url", "url", "file_url"):
        value = _as_str(item.get(key))
        if not value:
            continue
        split = urlsplit(value)
        if split.scheme and split.netloc:
            return f"{split.scheme}://{split.netloc}"
    return "https://example.com"


def _infer_attachment_file_name(file_url: str | None) -> str | None:
    if not file_url:
        return None
    parsed = urlparse(file_url)
    file_name = unquote(parsed.path.rsplit("/", maxsplit=1)[-1]).strip()
    return file_name or None


def _infer_attachment_file_ext(*, file_name: str | None, file_url: str | None) -> str | None:
    candidate = None
    if file_name and "." in file_name:
        candidate = file_name.rsplit(".", maxsplit=1)[-1].strip()
    if not candidate and file_url:
        parsed = urlparse(file_url)
        tail = parsed.path.rsplit("/", maxsplit=1)[-1]
        if "." in tail:
            candidate = tail.rsplit(".", maxsplit=1)[-1].strip()

    return candidate.lower() if candidate else None


def _infer_attachment_mime_type(*, mime_type: str | None, file_name: str | None, file_url: str | None) -> str | None:
    if mime_type:
        return mime_type

    guessed = None
    if file_name:
        guessed, _ = mimetypes.guess_type(file_name)
    if guessed:
        return guessed
    if file_url:
        guessed, _ = mimetypes.guess_type(file_url)
    return guessed


def _model_create_kwargs(session: Session, model_cls: type, **kwargs: object) -> dict:
    if not _is_sqlite(session):
        return kwargs
    if "id" in kwargs and kwargs["id"] is not None:
        return kwargs

    next_id = session.scalar(select(func.max(model_cls.id)))
    payload = dict(kwargs)
    payload["id"] = (next_id or 0) + 1
    return payload


def _is_sqlite(session: Session) -> bool:
    bind = session.get_bind()
    if bind is None:
        return False
    return bind.dialect.name == "sqlite"
