"""Cấu hình đọc từ biến môi trường (12-factor app)."""
import os

# Địa chỉ mặc định khi chạy local (không Docker). Trong Docker Compose các
# biến *_SERVICE_URL được đặt thành tên service trong mạng nội bộ.
SERVICE_DEFAULTS = {
    "auth": "http://localhost:8001",
    "product": "http://localhost:8002",
    "inventory": "http://localhost:8003",
    "cart": "http://localhost:8004",
    "order": "http://localhost:8005",
    "payment": "http://localhost:8006",
    "promotion": "http://localhost:8007",
    "notification": "http://localhost:8008",
    "ai": "http://localhost:8009",
    "registry": "http://localhost:8500",
}


def env(name, default=None):
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def env_int(name, default):
    try:
        return int(env(name, default))
    except (TypeError, ValueError):
        return default


def env_bool(name, default=False):
    value = env(name)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def service_url(name):
    default = SERVICE_DEFAULTS[name]
    if name == "registry":  # registry dùng chung biến REGISTRY_URL với client đăng ký
        default = env("REGISTRY_URL", default)
    return env(f"{name.upper()}_SERVICE_URL", default).rstrip("/")


JWT_SECRET = env("JWT_SECRET", "dev-jwt-secret-change-me")
JWT_EXPIRES_HOURS = env_int("JWT_EXPIRES_HOURS", 24)
INTERNAL_API_KEY = env("INTERNAL_API_KEY", "dev-internal-key-change-me")
TZ_OFFSET_HOURS = env_int("APP_TZ_OFFSET_HOURS", 7)  # Asia/Ho_Chi_Minh
