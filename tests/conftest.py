from __future__ import annotations

from collections.abc import Mapping

import pytest
from fastapi.testclient import TestClient

from app.core.auth import (
    ADMIN_CSRF_COOKIE_NAME,
    ADMIN_CSRF_COOKIE_PATH,
    ADMIN_CSRF_FORM_FIELD,
    AuthenticatedUser,
    UserRole,
    build_admin_csrf_token,
    get_current_user,
)
from app.main import app


@pytest.fixture(autouse=True)
def _override_auth_for_tests():
    previous_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        username="pytest-admin",
        role=UserRole.admin,
    )
    try:
        yield
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous_override


@pytest.fixture
def admin_csrf():
    def _admin_csrf(
        client: TestClient,
        *,
        username: str = "pytest-admin",
        data: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        token = build_admin_csrf_token(username=username)
        client.cookies.jar.clear()
        client.cookies.set(ADMIN_CSRF_COOKIE_NAME, token, path=ADMIN_CSRF_COOKIE_PATH)
        payload = dict(data or {})
        payload[ADMIN_CSRF_FORM_FIELD] = token
        return payload

    return _admin_csrf
