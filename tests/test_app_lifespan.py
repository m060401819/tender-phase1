from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module


def test_app_lifespan_initializes_and_shutdowns_scheduler(monkeypatch) -> None:
    calls = {"initialize": 0, "start": 0, "shutdown": 0}

    class StubRuntime:
        def start(self) -> None:
            calls["start"] += 1

    def fake_initialize(database_url: str) -> StubRuntime:
        assert isinstance(database_url, str)
        calls["initialize"] += 1
        return StubRuntime()

    def fake_shutdown() -> None:
        calls["shutdown"] += 1

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
