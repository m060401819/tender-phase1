"""init phase1 schema

Revision ID: 20260319_0001
Revises: 
Create Date: 2026-03-19 11:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260319_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_site",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("supports_js_render", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("crawl_interval_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_source_site_code"),
    )

    op.create_table(
        "crawl_job",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_site_id", sa.BigInteger(), nullable=False),
        sa.Column("job_type", sa.String(length=32), server_default="scheduled", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("triggered_by", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("documents_saved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notices_upserted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deduplicated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'partial')",
            name="ck_crawl_job_status",
        ),
        sa.CheckConstraint(
            "job_type IN ('scheduled', 'manual', 'backfill')",
            name="ck_crawl_job_type",
        ),
        sa.ForeignKeyConstraint(["source_site_id"], ["source_site.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_job_source_started_at", "crawl_job", ["source_site_id", "started_at"], unique=False)
    op.create_index("ix_crawl_job_status", "crawl_job", ["status"], unique=False)

    op.create_table(
        "raw_document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_site_id", sa.BigInteger(), nullable=False),
        sa.Column("crawl_job_id", sa.BigInteger(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("document_type", sa.String(length=16), server_default="html", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("charset", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=True),
        sa.Column("is_duplicate_url", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_duplicate_content", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("extra_meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "document_type IN ('html', 'pdf', 'json', 'other')",
            name="ck_raw_document_type",
        ),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_job.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_site_id"], ["source_site.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_site_id", "url_hash", name="uq_raw_document_source_url_hash"),
    )
    op.create_index("ix_raw_document_url_hash", "raw_document", ["url_hash"], unique=False)
    op.create_index("ix_raw_document_content_hash", "raw_document", ["content_hash"], unique=False)
    op.create_index("ix_raw_document_crawl_job", "raw_document", ["crawl_job_id"], unique=False)
    op.create_index("ix_raw_document_fetched_at", "raw_document", ["fetched_at"], unique=False)

    op.create_table(
        "tender_notice",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_site_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("project_code", sa.String(length=128), nullable=True),
        sa.Column("dedup_hash", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("notice_type", sa.String(length=32), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=True),
        sa.Column("region", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("budget_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("budget_currency", sa.String(length=16), server_default="CNY", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "notice_type IN ('announcement', 'change', 'result')",
            name="ck_tender_notice_type",
        ),
        sa.ForeignKeyConstraint(["source_site_id"], ["source_site.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_site_id", "dedup_hash", name="uq_tender_notice_source_dedup_hash"),
        sa.UniqueConstraint("source_site_id", "external_id", name="uq_tender_notice_source_external_id"),
    )
    op.create_index(
        "ix_tender_notice_source_published",
        "tender_notice",
        ["source_site_id", "published_at"],
        unique=False,
    )
    op.create_index("ix_tender_notice_type", "tender_notice", ["notice_type"], unique=False)
    op.create_index("ix_tender_notice_deadline", "tender_notice", ["deadline_at"], unique=False)
    op.create_index("ix_tender_notice_region", "tender_notice", ["region"], unique=False)
    op.create_index("ix_tender_notice_issuer", "tender_notice", ["issuer"], unique=False)

    op.create_table(
        "notice_version",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("notice_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_document_id", sa.BigInteger(), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("notice_type", sa.String(length=32), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=True),
        sa.Column("region", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("budget_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("budget_currency", sa.String(length=16), server_default="CNY", nullable=False),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "notice_type IN ('announcement', 'change', 'result')",
            name="ck_notice_version_type",
        ),
        sa.ForeignKeyConstraint(["notice_id"], ["tender_notice.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_document_id"], ["raw_document.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notice_id", "content_hash", name="uq_notice_version_notice_content_hash"),
        sa.UniqueConstraint("notice_id", "version_no", name="uq_notice_version_notice_version_no"),
    )
    op.create_index("ix_notice_version_content_hash", "notice_version", ["content_hash"], unique=False)
    op.create_index("ix_notice_version_notice_current", "notice_version", ["notice_id", "is_current"], unique=False)
    op.create_index("ix_notice_version_raw_document", "notice_version", ["raw_document_id"], unique=False)

    op.create_table(
        "tender_attachment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_site_id", sa.BigInteger(), nullable=False),
        sa.Column("notice_id", sa.BigInteger(), nullable=False),
        sa.Column("notice_version_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_document_id", sa.BigInteger(), nullable=True),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("attachment_type", sa.String(length=32), server_default="notice_file", nullable=False),
        sa.Column("file_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("storage_uri", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_ext", sa.String(length=32), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "attachment_type IN ('notice_file', 'bid_file', 'other')",
            name="ck_tender_attachment_type",
        ),
        sa.ForeignKeyConstraint(["notice_id"], ["tender_notice.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notice_version_id"], ["notice_version.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_document_id"], ["raw_document.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_site_id"], ["source_site.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_site_id", "url_hash", name="uq_tender_attachment_source_url_hash"),
    )
    op.create_index("ix_tender_attachment_notice", "tender_attachment", ["notice_id"], unique=False)
    op.create_index(
        "ix_tender_attachment_notice_version",
        "tender_attachment",
        ["notice_version_id"],
        unique=False,
    )
    op.create_index("ix_tender_attachment_file_hash", "tender_attachment", ["file_hash"], unique=False)

    op.create_table(
        "crawl_error",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_site_id", sa.BigInteger(), nullable=False),
        sa.Column("crawl_job_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_document_id", sa.BigInteger(), nullable=True),
        sa.Column("stage", sa.String(length=32), server_default="fetch", nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "stage IN ('fetch', 'parse', 'persist')",
            name="ck_crawl_error_stage",
        ),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_job.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_document_id"], ["raw_document.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_site_id"], ["source_site.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_error_source_occurred", "crawl_error", ["source_site_id", "occurred_at"], unique=False)
    op.create_index("ix_crawl_error_job", "crawl_error", ["crawl_job_id"], unique=False)
    op.create_index("ix_crawl_error_raw_document", "crawl_error", ["raw_document_id"], unique=False)

    op.create_foreign_key(
        "fk_tender_notice_current_version_id",
        "tender_notice",
        "notice_version",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tender_notice_current_version_id", "tender_notice", type_="foreignkey")

    op.drop_index("ix_crawl_error_raw_document", table_name="crawl_error")
    op.drop_index("ix_crawl_error_job", table_name="crawl_error")
    op.drop_index("ix_crawl_error_source_occurred", table_name="crawl_error")
    op.drop_table("crawl_error")

    op.drop_index("ix_tender_attachment_file_hash", table_name="tender_attachment")
    op.drop_index("ix_tender_attachment_notice_version", table_name="tender_attachment")
    op.drop_index("ix_tender_attachment_notice", table_name="tender_attachment")
    op.drop_table("tender_attachment")

    op.drop_index("ix_notice_version_raw_document", table_name="notice_version")
    op.drop_index("ix_notice_version_notice_current", table_name="notice_version")
    op.drop_index("ix_notice_version_content_hash", table_name="notice_version")
    op.drop_table("notice_version")

    op.drop_index("ix_tender_notice_issuer", table_name="tender_notice")
    op.drop_index("ix_tender_notice_region", table_name="tender_notice")
    op.drop_index("ix_tender_notice_deadline", table_name="tender_notice")
    op.drop_index("ix_tender_notice_type", table_name="tender_notice")
    op.drop_index("ix_tender_notice_source_published", table_name="tender_notice")
    op.drop_table("tender_notice")

    op.drop_index("ix_raw_document_fetched_at", table_name="raw_document")
    op.drop_index("ix_raw_document_crawl_job", table_name="raw_document")
    op.drop_index("ix_raw_document_content_hash", table_name="raw_document")
    op.drop_index("ix_raw_document_url_hash", table_name="raw_document")
    op.drop_table("raw_document")

    op.drop_index("ix_crawl_job_status", table_name="crawl_job")
    op.drop_index("ix_crawl_job_source_started_at", table_name="crawl_job")
    op.drop_table("crawl_job")

    op.drop_table("source_site")
