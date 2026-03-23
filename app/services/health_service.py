from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import FromClause

from app.db.session import get_session_bind, ping_database
from app.models import CrawlJob, RawDocument, SourceSite, TenderNotice

SERVICE_NAME = "tender-phase1"
ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parents[2] / "alembic"
REQUIRED_TABLES: tuple[tuple[str, FromClause], ...] = (
    ("source_site", SourceSite.__table__),
    ("crawl_job", CrawlJob.__table__),
    ("tender_notice", TenderNotice.__table__),
    ("raw_document", RawDocument.__table__),
)


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    detail: str
    extra: dict[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "detail": self.detail,
        }
        payload.update(self.extra)
        return payload


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    service: str
    checks: dict[str, dict[str, object]]

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    def to_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "service": self.service,
            "checks": self.checks,
        }


class ReadinessService:
    """Readiness checks for database-backed API traffic."""

    def __init__(
        self,
        session: Session,
        *,
        service_name: str = SERVICE_NAME,
        alembic_script_location: Path | None = None,
        required_tables: Sequence[tuple[str, FromClause]] | None = None,
    ) -> None:
        self._session = session
        self._service_name = service_name
        self._alembic_script_location = Path(alembic_script_location or ALEMBIC_SCRIPT_LOCATION)
        self._required_tables = tuple(required_tables or REQUIRED_TABLES)

    def build_report(self) -> ReadinessReport:
        checks: dict[str, dict[str, object]] = {}

        database_ok = self._run_check(
            checks,
            "database_connection",
            self._check_database_connection,
        )
        if not database_ok:
            checks["required_tables"] = ReadinessCheck(
                status="skipped",
                detail="skipped because database connection failed",
            ).to_payload()
            checks["alembic_version"] = ReadinessCheck(
                status="skipped",
                detail="skipped because database connection failed",
            ).to_payload()
            return ReadinessReport(status="not_ready", service=self._service_name, checks=checks)

        self._run_check(checks, "required_tables", self._check_required_tables)
        self._run_check(checks, "alembic_version", self._check_alembic_version)

        is_ready = all(check["status"] == "ok" for check in checks.values())
        return ReadinessReport(
            status="ready" if is_ready else "not_ready",
            service=self._service_name,
            checks=checks,
        )

    def _run_check(
        self,
        checks: dict[str, dict[str, object]],
        name: str,
        operation: Callable[[], tuple[str, dict[str, object]]],
    ) -> bool:
        try:
            detail, extra = operation()
        except Exception as exc:
            checks[name] = ReadinessCheck(
                status="failed",
                detail=self._format_exception(exc),
            ).to_payload()
            return False

        checks[name] = ReadinessCheck(status="ok", detail=detail, extra=extra).to_payload()
        return True

    def _check_database_connection(self) -> tuple[str, dict[str, object]]:
        ping_database(self._session)
        dialect_name = get_session_bind(self._session).dialect.name
        return "database connection is available", {"dialect": dialect_name}

    def _check_required_tables(self) -> tuple[str, dict[str, object]]:
        table_names: list[str] = []
        for table_name, table in self._required_tables:
            self._session.execute(select(1).select_from(table).limit(1)).first()
            table_names.append(table_name)
        return "critical tables are queryable", {"tables": table_names}

    def _check_alembic_version(self) -> tuple[str, dict[str, object]]:
        connection = self._session.connection()
        current_heads = tuple(sorted(MigrationContext.configure(connection).get_current_heads()))
        expected_heads = self._load_expected_heads()
        if not current_heads:
            raise RuntimeError("alembic version table is missing or empty")
        if current_heads != expected_heads:
            raise RuntimeError(
                "database schema revision does not match code head "
                f"(current={','.join(current_heads)} expected={','.join(expected_heads)})"
            )
        return "database schema revision matches alembic head", {
            "current_heads": list(current_heads),
            "expected_heads": list(expected_heads),
        }

    def _load_expected_heads(self) -> tuple[str, ...]:
        config = Config()
        config.set_main_option("script_location", str(self._alembic_script_location))
        heads = tuple(sorted(ScriptDirectory.from_config(config).get_heads()))
        if not heads:
            raise RuntimeError("no alembic head revision found")
        return heads

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        message = str(exc).strip()
        if not message:
            return exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"
