from __future__ import annotations

import hashlib
import hmac
import html
import json
import secrets
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from app.core.config import settings

ADMIN_CSRF_COOKIE_NAME = "admin_csrf_token"
ADMIN_CSRF_FORM_FIELD = "csrf_token"
ADMIN_CSRF_HEADER_NAME = "X-CSRF-Token"
ADMIN_CSRF_COOKIE_PATH = "/admin"
ADMIN_CSRF_TTL_SECONDS = 12 * 60 * 60
DEV_ADMIN_CSRF_SIGNING_SECRET = "dev-admin-csrf-secret"


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


class CsrfValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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


def build_admin_csrf_token(*, username: str, issued_at: int | None = None, nonce: str | None = None) -> str:
    normalized_issued_at = int(issued_at or time.time())
    normalized_nonce = nonce or secrets.token_urlsafe(24)
    signature = _sign_admin_csrf_token(
        username=username,
        issued_at=normalized_issued_at,
        nonce=normalized_nonce,
    )
    return f"{normalized_issued_at}.{normalized_nonce}.{signature}"


def get_or_create_admin_csrf_token(
    request: Request,
    *,
    current_user: AuthenticatedUser,
) -> str:
    cached_token = getattr(request.state, "admin_csrf_token", None)
    if isinstance(cached_token, str) and cached_token:
        return cached_token

    request.state.auth_user = current_user
    cookie_token = (request.cookies.get(ADMIN_CSRF_COOKIE_NAME) or "").strip()
    if cookie_token and _is_valid_admin_csrf_token(token=cookie_token, username=current_user.username):
        token = cookie_token
    else:
        token = build_admin_csrf_token(username=current_user.username)

    request.state.admin_csrf_token = token
    return token


def set_admin_csrf_cookie(*, response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=ADMIN_CSRF_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=ADMIN_CSRF_TTL_SECONDS,
        path=ADMIN_CSRF_COOKIE_PATH,
    )


def render_admin_template(
    *,
    templates: Jinja2Templates,
    request: Request,
    name: str,
    context: dict[str, Any],
    current_user: AuthenticatedUser,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    merged_context = dict(context)
    merged_context["request"] = request
    merged_context["csrf_token"] = get_or_create_admin_csrf_token(request, current_user=current_user)
    response = templates.TemplateResponse(
        name=name,
        context=merged_context,
        request=request,
        status_code=status_code,
    )
    set_admin_csrf_cookie(
        response=response,
        request=request,
        token=merged_context["csrf_token"],
    )
    return response


def build_admin_csrf_error_response(
    request: Request,
    *,
    message: str,
    status_code: int = status.HTTP_403_FORBIDDEN,
) -> HTMLResponse:
    back_url = request.headers.get("referer") or "/admin/home"
    escaped_message = html.escape(message)
    escaped_back_url = html.escape(back_url, quote=True)
    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CSRF 校验失败</title>
  <style>
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: linear-gradient(180deg, #fff7ed 0%, #fff 100%);
      color: #7c2d12;
    }}
    .wrap {{
      max-width: 720px;
      margin: 72px auto;
      padding: 0 16px;
    }}
    .card {{
      background: #fff;
      border: 1px solid #fed7aa;
      border-radius: 16px;
      box-shadow: 0 16px 40px rgba(124, 45, 18, 0.08);
      padding: 28px 24px;
    }}
    h1 {{ margin: 0 0 12px 0; font-size: 28px; }}
    p {{ margin: 0 0 10px 0; line-height: 1.7; }}
    a {{
      display: inline-block;
      margin-top: 12px;
      color: #fff;
      text-decoration: none;
      background: #c2410c;
      border-radius: 10px;
      padding: 10px 14px;
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>CSRF 校验失败</h1>
      <p>{escaped_message}</p>
      <p>请返回上一页刷新后重新提交；如果问题持续出现，请重新打开后台页面后再试。</p>
      <a href="{escaped_back_url}">返回后台</a>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=content, status_code=status_code)


async def require_admin_csrf(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> None:
    request.state.auth_user = current_user
    cookie_token = (request.cookies.get(ADMIN_CSRF_COOKIE_NAME) or "").strip()
    if not cookie_token:
        raise CsrfValidationError("缺少 CSRF Cookie，请刷新页面后重试。")

    submitted_token = (request.headers.get(ADMIN_CSRF_HEADER_NAME) or "").strip()
    if not submitted_token:
        body = await request.body()
        if body:
            form_data = parse_qs(body.decode("utf-8", errors="ignore"))
            submitted_token = (form_data.get(ADMIN_CSRF_FORM_FIELD) or [""])[0].strip()

    if not submitted_token:
        raise CsrfValidationError("缺少 CSRF Token，请刷新页面后重试。")
    if not secrets.compare_digest(cookie_token, submitted_token):
        raise CsrfValidationError("CSRF Token 不匹配，请刷新页面后重试。")
    if not _is_valid_admin_csrf_token(token=cookie_token, username=current_user.username):
        raise CsrfValidationError("CSRF Token 无效或已过期，请刷新页面后重试。")


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


def _admin_csrf_signing_secret() -> str:
    # HTTP Basic credentials come from AUTH_BASIC_USERS_JSON.
    # ADMIN_AUTH_SECRET is reserved for signing admin CSRF tokens.
    return settings.admin_auth_secret or DEV_ADMIN_CSRF_SIGNING_SECRET


def _sign_admin_csrf_token(*, username: str, issued_at: int, nonce: str) -> str:
    payload = f"{username}:{issued_at}:{nonce}".encode("utf-8")
    secret = _admin_csrf_signing_secret().encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _is_valid_admin_csrf_token(*, token: str, username: str) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False

    issued_at_raw, nonce, signature = parts
    if not nonce or not signature:
        return False

    try:
        issued_at = int(issued_at_raw)
    except ValueError:
        return False

    now = int(time.time())
    if issued_at > now + 60:
        return False
    if now - issued_at > ADMIN_CSRF_TTL_SECONDS:
        return False

    expected_signature = _sign_admin_csrf_token(
        username=username,
        issued_at=issued_at,
        nonce=nonce,
    )
    return secrets.compare_digest(signature, expected_signature)
