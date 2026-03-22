from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ValidationError

from app.core.config import settings


class UserRole(StrEnum):
    viewer = "viewer"
    ops = "ops"
    admin = "admin"


_ROLE_LEVELS: dict[UserRole, int] = {
    UserRole.viewer: 1,
    UserRole.ops: 2,
    UserRole.admin: 3,
}


class _ConfiguredAuthUser(BaseModel):
    username: str
    password: str
    role: UserRole


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    username: str
    role: UserRole


_http_basic = HTTPBasic(auto_error=False)


def has_required_role(user_role: UserRole, required_role: UserRole) -> bool:
    return _ROLE_LEVELS[user_role] >= _ROLE_LEVELS[required_role]


def get_current_user(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_http_basic),
) -> AuthenticatedUser:
    if credentials is None:
        raise _unauthorized("authentication required")

    try:
        configured_users = _parse_configured_users(settings.auth_basic_users_json)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if not configured_users:
        raise _unauthorized("authentication required")

    for configured_user in configured_users:
        username_matches = secrets.compare_digest(configured_user.username, credentials.username)
        password_matches = secrets.compare_digest(configured_user.password, credentials.password)
        if username_matches and password_matches:
            user = AuthenticatedUser(username=configured_user.username, role=configured_user.role)
            request.state.auth_user = user
            return user

    raise _unauthorized("invalid credentials")


def require_min_role(required_role: UserRole):
    def dependency(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not has_required_role(current_user.role, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{required_role.value} role required",
            )
        return current_user

    return dependency


require_viewer_user = require_min_role(UserRole.viewer)
require_ops_user = require_min_role(UserRole.ops)
require_admin_user = require_min_role(UserRole.admin)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": f'Basic realm="{settings.auth_basic_realm}"'},
    )


@lru_cache(maxsize=8)
def _parse_configured_users(raw_value: str) -> tuple[_ConfiguredAuthUser, ...]:
    text = raw_value.strip()
    if not text:
        return ()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AUTH_BASIC_USERS_JSON 配置无效，必须是 JSON 数组") from exc

    if not isinstance(payload, list):
        raise RuntimeError("AUTH_BASIC_USERS_JSON 配置无效，必须是 JSON 数组")

    try:
        return tuple(_ConfiguredAuthUser.model_validate(item) for item in payload)
    except ValidationError as exc:
        raise RuntimeError("AUTH_BASIC_USERS_JSON 配置无效，必须包含 username/password/role") from exc
