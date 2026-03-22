from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models import CrawlJob, SourceSite
from app.services import CrawlJobService
from app.services.source_schedule_service import SOURCE_SCHEDULE_REFRESH_JOB_ID, SourceScheduleRuntime


class RecordingRunner:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.commands: list[list[str]] = []

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        heartbeat_callback=None,
        heartbeat_interval_seconds: int = 30,
    ) -> int:
        _ = (cwd, heartbeat_callback, heartbeat_interval_seconds)
        self.commands.append(command)
        return self.return_code


class BlockingRunner(RecordingRunner):
    def __init__(self, *, release_event: Event, return_code: int = 0) -> None:
        super().__init__(return_code=return_code)
        self.release_event = release_event
        self.started_event = Event()

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        heartbeat_callback=None,
        heartbeat_interval_seconds: int = 30,
    ) -> int:
        _ = (cwd, heartbeat_callback, heartbeat_interval_seconds)
        self.commands.append(command)
        self.started_event.set()
        released = self.release_event.wait(timeout=5)
        assert released, "blocking runner timed out waiting for release"
        return self.return_code


def _build_db(tmp_path: Path, name: str) -> tuple[str, sessionmaker]:
    db_path = tmp_path / name
    db_url = f"sqlite+pysqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return db_url, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_schedule_runtime_can_create_schedule_task(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_create.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=False,
                schedule_days=1,
            )
        )
        session.commit()

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime.start()
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is None

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            source.schedule_enabled = True
            source.schedule_days = 2
            session.add(source)
            session.commit()

        runtime.sync_source("anhui_ggzy_zfcg")
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is not None

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.next_scheduled_run_at is not None
    finally:
        runtime.shutdown()


def test_schedule_runtime_can_update_schedule_task(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_update.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=True,
                schedule_days=1,
            )
        )
        session.commit()

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime.start()
        job = runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg")
        assert job is not None
        assert job.trigger.interval.days == 1

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            source.schedule_days = 3
            session.add(source)
            session.commit()

        runtime.sync_source("anhui_ggzy_zfcg")
        job = runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg")
        assert job is not None
        assert job.trigger.interval.days == 3
    finally:
        runtime.shutdown()


def test_schedule_runtime_can_disable_schedule_task(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_disable.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=True,
                schedule_days=1,
            )
        )
        session.commit()

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime.start()
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is not None

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            source.schedule_enabled = False
            session.add(source)
            session.commit()

        runtime.sync_source("anhui_ggzy_zfcg")
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is None

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.next_scheduled_run_at is None
    finally:
        runtime.shutdown()


def test_schedule_runtime_restores_tasks_on_startup(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_restore.db")

    with session_factory() as session:
        session.add_all(
            [
                SourceSite(
                    id=1,
                    code="anhui_ggzy_zfcg",
                    name="Anhui",
                    base_url="https://ggzy.ah.gov.cn/",
                    description="",
                    is_active=True,
                    supports_js_render=False,
                    crawl_interval_minutes=60,
                    default_max_pages=1,
                    schedule_enabled=True,
                    schedule_days=7,
                ),
                SourceSite(
                    id=2,
                    code="example_source",
                    name="Example",
                    base_url="https://example.com/",
                    description="",
                    is_active=True,
                    supports_js_render=False,
                    crawl_interval_minutes=60,
                    default_max_pages=1,
                    schedule_enabled=False,
                    schedule_days=1,
                ),
            ]
        )
        session.commit()

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime.start()
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is not None
        assert runtime.scheduler.get_job("source_schedule::example_source") is None
        assert runtime.scheduler.get_job(SOURCE_SCHEDULE_REFRESH_JOB_ID) is not None
    finally:
        runtime.shutdown()


def test_schedule_runtime_restore_keeps_existing_next_run_time_when_source_unchanged(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_keep_next_run.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=True,
                schedule_days=2,
            )
        )
        session.commit()

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime.start()
        job = runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg")
        assert job is not None
        first_next_run = job.next_run_time

        runtime.restore_from_db()

        refreshed_job = runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg")
        assert refreshed_job is not None
        assert refreshed_job.next_run_time == first_next_run
    finally:
        runtime.shutdown()


def test_schedule_runtime_restore_refreshes_schedule_changes_from_db(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_refresh_from_db.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=False,
                schedule_days=1,
            )
        )
        session.commit()

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime.start()
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is None

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            source.schedule_enabled = True
            source.schedule_days = 3
            source.next_scheduled_run_at = datetime.now(timezone.utc) + timedelta(days=3)
            session.add(source)
            session.commit()

        runtime.restore_from_db()

        job = runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg")
        assert job is not None
        assert job.trigger.interval.days == 3

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.next_scheduled_run_at is not None
    finally:
        runtime.shutdown()


def test_schedule_runtime_restore_prunes_deleted_source_jobs(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_prune_deleted.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=True,
                schedule_days=1,
            )
        )
        session.commit()

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime.start()
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is not None

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            session.delete(source)
            session.commit()

        runtime.restore_from_db()
        assert runtime.scheduler.get_job("source_schedule::anhui_ggzy_zfcg") is None
    finally:
        runtime.shutdown()


def test_schedule_runtime_skips_source_when_active_job_already_exists(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_skip_active.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=True,
                schedule_days=1,
            )
        )
        session.commit()

    job_service = CrawlJobService(session_factory=session_factory)
    active_job = job_service.create_job(source_code="anhui_ggzy_zfcg", job_type="manual", triggered_by="pytest-active")
    job_service.start_job(active_job.id)

    runtime = SourceScheduleRuntime(database_url=db_url)
    try:
        runtime._run_scheduled_source("anhui_ggzy_zfcg")

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.last_schedule_status == "skipped"

            jobs = session.scalars(select(CrawlJob).order_by(CrawlJob.id.asc())).all()
            assert len(jobs) == 1
            assert jobs[0].id == active_job.id
            assert jobs[0].status == "running"
    finally:
        runtime.shutdown()


def test_schedule_runtime_multi_instance_duplicate_trigger_only_runs_once_per_source(tmp_path: Path) -> None:
    db_url, session_factory = _build_db(tmp_path, "source_schedule_multi_instance_mutex.db")

    with session_factory() as session:
        session.add(
            SourceSite(
                id=1,
                code="anhui_ggzy_zfcg",
                name="Anhui",
                base_url="https://ggzy.ah.gov.cn/",
                description="",
                is_active=True,
                supports_js_render=False,
                crawl_interval_minutes=60,
                default_max_pages=1,
                schedule_enabled=True,
                schedule_days=1,
            )
        )
        session.commit()

    release_event = Event()
    primary_runner = BlockingRunner(release_event=release_event, return_code=0)
    secondary_runner = RecordingRunner(return_code=0)
    primary_runtime = SourceScheduleRuntime(database_url=db_url, command_runner=primary_runner)
    secondary_runtime = SourceScheduleRuntime(database_url=db_url, command_runner=secondary_runner)
    first_attempt: dict[str, object] = {}

    try:
        primary_runtime.start()
        secondary_runtime.start()

        def _run_primary_scheduler() -> None:
            try:
                primary_runtime._run_scheduled_source("anhui_ggzy_zfcg")
            except Exception as exc:  # pragma: no cover - diagnostic guard for thread failure
                first_attempt["error"] = exc

        worker = Thread(target=_run_primary_scheduler)
        worker.start()
        assert primary_runner.started_event.wait(timeout=5)

        with session_factory() as session:
            jobs = session.scalars(
                select(CrawlJob)
                .where(CrawlJob.source_site_id == 1)
                .order_by(CrawlJob.id.asc())
            ).all()
            assert len(jobs) == 1
            assert jobs[0].status == "running"

        secondary_runtime._run_scheduled_source("anhui_ggzy_zfcg")

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.last_schedule_status == "skipped"

            jobs = session.scalars(
                select(CrawlJob)
                .where(CrawlJob.source_site_id == 1)
                .order_by(CrawlJob.id.asc())
            ).all()
            assert len(jobs) == 1
            assert jobs[0].status == "running"

        assert len(secondary_runner.commands) == 0

        release_event.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert "error" not in first_attempt

        with session_factory() as session:
            source = session.scalar(select(SourceSite).where(SourceSite.code == "anhui_ggzy_zfcg"))
            assert source is not None
            assert source.last_schedule_status == "succeeded"

            jobs = session.scalars(
                select(CrawlJob)
                .where(CrawlJob.source_site_id == 1)
                .order_by(CrawlJob.id.asc())
            ).all()
            assert len(jobs) == 1
            assert jobs[0].status == "succeeded"

        assert len(primary_runner.commands) == 1
    finally:
        release_event.set()
        primary_runtime.shutdown()
        secondary_runtime.shutdown()
