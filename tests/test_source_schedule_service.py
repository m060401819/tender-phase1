from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db.base import Base
from app.models import SourceSite
from app.services.source_schedule_service import SourceScheduleRuntime


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
    finally:
        runtime.shutdown()
