from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.logging import JsonLogFormatter, reset_request_id, set_request_id


def test_app_lifespan_skips_scheduler_when_embedded_mode_disabled(monkeypatch) -> None:
    calls = {"initialize": 0, "start": 0, "shutdown": 0}

    class StubRuntime:
        def start(self) -> None:
            calls["start"] += 1

    def fake_initialize(database_url: str, *, refresh_interval_seconds: int) -> StubRuntime:
        assert isinstance(database_url, str)
        assert isinstance(refresh_interval_seconds, int)
        calls["initialize"] += 1
        return StubRuntime()

    def fake_shutdown() -> None:
        calls["shutdown"] += 1

    monkeypatch.setattr(main_module.settings, "source_scheduler_embedded_enabled", False, raising=False)
    monkeypatch.setattr(main_module, "initialize_source_schedule_runtime", fake_initialize)
    monkeypatch.setattr(main_module, "shutdown_source_schedule_runtime", fake_shutdown)

    app = main_module.create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    assert calls["initialize"] == 0
    assert calls["start"] == 0
    assert calls["shutdown"] == 0


def test_app_lifespan_initializes_and_shutdowns_scheduler_when_embedded_enabled(monkeypatch) -> None:
    calls = {"initialize": 0, "start": 0, "shutdown": 0}

    class StubRuntime:
        def start(self) -> None:
            calls["start"] += 1

    def fake_initialize(database_url: str, *, refresh_interval_seconds: int) -> StubRuntime:
        assert isinstance(database_url, str)
        assert refresh_interval_seconds == 45
        calls["initialize"] += 1
        return StubRuntime()

    def fake_shutdown() -> None:
        calls["shutdown"] += 1

    monkeypatch.setattr(main_module.settings, "source_scheduler_embedded_enabled", True, raising=False)
    monkeypatch.setattr(main_module.settings, "source_scheduler_refresh_interval_seconds", 45, raising=False)
    monkeypatch.setattr(main_module, "initialize_source_schedule_runtime", fake_initialize)
    monkeypatch.setattr(main_module, "shutdown_source_schedule_runtime", fake_shutdown)

    app = main_module.create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    assert calls["initialize"] == 1
    assert calls["start"] == 1
    assert calls["shutdown"] >= 1


def test_app_lifespan_logs_structured_error_when_scheduler_startup_fails(monkeypatch, caplog) -> None:
    calls = {"shutdown": 0}

    class StubRuntime:
        def start(self) -> None:
            raise RuntimeError("scheduler boom")

    def fake_initialize(database_url: str, *, refresh_interval_seconds: int) -> StubRuntime:
        assert isinstance(database_url, str)
        assert isinstance(refresh_interval_seconds, int)
        return StubRuntime()

    def fake_shutdown() -> None:
        calls["shutdown"] += 1

    monkeypatch.setattr(main_module.settings, "source_scheduler_embedded_enabled", True, raising=False)
    monkeypatch.setattr(main_module, "initialize_source_schedule_runtime", fake_initialize)
    monkeypatch.setattr(main_module, "shutdown_source_schedule_runtime", fake_shutdown)

    app = main_module.create_app()
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.get("/healthz")
            assert response.status_code == 200

    startup_error = next(
        record for record in caplog.records if getattr(record, "event", "") == "source_scheduler_startup_skipped"
    )
    assert startup_error.levelno == logging.ERROR
    assert startup_error.job_type == "scheduled"
    assert startup_error.triggered_by == "embedded_scheduler"
    assert calls["shutdown"] == 1


def test_app_request_id_header_is_preserved() -> None:
    with TestClient(main_module.app) as client:
        response = client.get("/healthz", headers={"X-Request-ID": "req-test-001"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-001"


def test_json_log_formatter_serializes_structured_fields() -> None:
    request_id, token = set_request_id("req-log-001")
    try:
        record = logging.getLogger("tests.logging").makeRecord(
            "tests.logging",
            logging.ERROR,
            __file__,
            1,
            "structured %s",
            ("message",),
            None,
            extra={
                "event": "manual_crawl_background_failed",
                "source_code": "anhui_ggzy_zfcg",
                "crawl_job_id": 12,
                "job_type": "manual",
                "triggered_by": "admin_ui",
            },
        )
        payload = json.loads(JsonLogFormatter().format(record))
    finally:
        reset_request_id(token)

    assert request_id == "req-log-001"
    assert payload["message"] == "structured message"
    assert payload["event"] == "manual_crawl_background_failed"
    assert payload["source_code"] == "anhui_ggzy_zfcg"
    assert payload["crawl_job_id"] == 12
    assert payload["job_type"] == "manual"
    assert payload["triggered_by"] == "admin_ui"
    assert payload["request_id"] == "req-log-001"
