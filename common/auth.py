"""Xác thực & phân quyền.

- auth-service phát hành JWT (HS256).
- API Gateway kiểm tra JWT rồi chuyển danh tính xuống service qua header
  X-User-Id / X-User-Role / X-User-Name / X-User-Email, kèm X-Internal-Token.
- Service CHỈ tin các header X-User-* khi có X-Internal-Token hợp lệ, nên
  gọi thẳng vào service (bỏ qua gateway) không thể giả mạo người dùng.
"""
import hmac
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import quote, unquote

import jwt
from flask import g, request

from common.config import INTERNAL_API_KEY, JWT_EXPIRES_HOURS, JWT_SECRET
from common.errors import ApiError

ROLES = ("admin", "staff", "customer")
STAFF_ROLES = ("admin", "staff")


# ---------------------------------------------------------------- JWT
def create_token(user):
    issued = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "role": user["role"],
        "name": user.get("full_name") or "",
        "email": user.get("email") or "",
        "iat": issued,
        "exp": issued + timedelta(hours=JWT_EXPIRES_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại", code="TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise ApiError(401, "Token không hợp lệ", code="INVALID_TOKEN")
    return {
        "id": int(payload["sub"]),
        "role": payload.get("role", "customer"),
        "name": payload.get("name", ""),
        "email": payload.get("email", ""),
    }


def identity_headers(user):
    """Header gateway gắn vào request gửi xuống service (tên được URL-encode vì có dấu)."""
    return {
        "X-User-Id": str(user["id"]),
        "X-User-Role": user["role"],
        "X-User-Name": quote(user.get("name") or ""),
        "X-User-Email": quote(user.get("email") or ""),
    }


# ---------------------------------------------------------------- nội bộ
def is_internal_request():
    token = request.headers.get("X-Internal-Token", "")
    return bool(token) and hmac.compare_digest(token, INTERNAL_API_KEY)


def current_user():
    """Người dùng hiện tại (dict) do gateway chuyển xuống, hoặc None."""
    if "current_user" in g:
        return g.current_user
    user = None
    if is_internal_request() and request.headers.get("X-User-Id"):
        try:
            user = {
                "id": int(request.headers["X-User-Id"]),
                "role": request.headers.get("X-User-Role", "customer"),
                "name": unquote(request.headers.get("X-User-Name", "")),
                "email": unquote(request.headers.get("X-User-Email", "")),
            }
        except ValueError:
            user = None
    g.current_user = user
    return user


def is_staff(user=None):
    user = user if user is not None else current_user()
    return bool(user) and user["role"] in STAFF_ROLES


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            raise ApiError(401, "Bạn cần đăng nhập để thực hiện thao tác này")
        return fn(*args, **kwargs)

    wrapper._auth = {"type": "user"}  # dùng để sinh hợp đồng OpenAPI
    return wrapper


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                raise ApiError(401, "Bạn cần đăng nhập để thực hiện thao tác này")
            if user["role"] not in roles:
                raise ApiError(403, "Bạn không có quyền thực hiện thao tác này")
            return fn(*args, **kwargs)

        wrapper._auth = {"type": "roles", "roles": list(roles)}
        return wrapper

    return decorator


require_staff = require_roles(*STAFF_ROLES)
require_admin = require_roles("admin")


def internal_only(fn):
    """Endpoint chỉ dành cho service-to-service (không đi qua gateway)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_internal_request():
            raise ApiError(403, "Endpoint nội bộ", code="INTERNAL_ONLY")
        return fn(*args, **kwargs)

    wrapper._auth = {"type": "internal"}
    return wrapper
