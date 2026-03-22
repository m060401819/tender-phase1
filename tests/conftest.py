from __future__ import annotations

import pytest

from app.core.auth import AuthenticatedUser, UserRole, get_current_user
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
