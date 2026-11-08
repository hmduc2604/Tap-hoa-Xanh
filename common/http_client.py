"""HTTP client cho giao tiếp đồng bộ giữa các service.

Có timeout, retry (chỉ với GET) và Circuit Breaker: khi một service lỗi liên tiếp
nhiều lần, mạch "mở" trong một khoảng thời gian và các lời gọi trả lỗi 503 ngay
thay vì chờ timeout, tránh lỗi dây chuyền (cascading failure).
"""
import logging
import threading
import time

import requests
from urllib3.exceptions import NewConnectionError
from flask import g, has_request_context

from common.config import INTERNAL_API_KEY
from common.errors import ApiError
from common.registry import discovery

log = logging.getLogger(__name__)

SERVICE_LABELS = {
    "auth": "Người dùng",
    "product": "Sản phẩm",
    "inventory": "Kho hàng",
    "cart": "Giỏ hàng",
    "order": "Đơn hàng",
    "payment": "Thanh toán",
    "promotion": "Khuyến mãi",
    "notification": "Thông báo",
}


def never_connected(exc):
    """True nếu lỗi xảy ra trước khi kết nối được (request chắc chắn chưa tới server)."""
    reason = getattr(exc.args[0], "reason", None) if exc.args else None
    return isinstance(exc, requests.ConnectionError) and isinstance(reason, NewConnectionError)


class CircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=15):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.opened_at = None
        self._lock = threading.Lock()

    @property
    def state(self):
        with self._lock:
            if self.opened_at is None:
                return "CLOSED"
            if time.time() - self.opened_at >= self.reset_timeout:
                return "HALF_OPEN"
            return "OPEN"

    def allow(self):
        return self.state != "OPEN"

    def success(self):
        with self._lock:
            self.failures = 0
            self.opened_at = None

    def failure(self):
        with self._lock:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = time.time()


class ServiceClient:
    """Gọi một service theo TÊN: địa chỉ được tra cứu qua Service Registry mỗi lần gọi
    (có cache ngắn, xoay vòng nếu có nhiều instance), dự phòng bằng cấu hình tĩnh."""

    def __init__(self, name, base_url=None, timeout=10):
        self.name = name
        self.fixed_url = base_url.rstrip("/") if base_url else None
        self.timeout = timeout
        self.breaker = CircuitBreaker()

    def resolve(self):
        if self.fixed_url:
            return self.fixed_url, "static"
        return discovery.resolve(self.name)

    @property
    def base_url(self):
        return self.resolve()[0]

    @property
    def label(self):
        return SERVICE_LABELS.get(self.name, self.name)

    def _headers(self, extra=None):
        headers = {"X-Internal-Token": INTERNAL_API_KEY, "Accept": "application/json"}
        if has_request_context() and "request_id" in g:
            headers["X-Request-ID"] = g.request_id
        if extra:
            headers.update(extra)
        return headers

    def request(self, method, path, json=None, params=None, headers=None, retries=None):
        """Trả về (status_code, body). Ném ApiError(503) khi service không liên lạc được."""
        if not self.breaker.allow():
            raise ApiError(503, f"Dịch vụ {self.label} tạm thời không khả dụng", code="CIRCUIT_OPEN")
        attempts = 1 + (retries if retries is not None else (2 if method.upper() == "GET" else 0))
        last_exc = None
        attempt = 0
        while attempt < attempts:
            url = self.resolve()[0] + path
            try:
                resp = requests.request(
                    method, url, json=json, params=params, headers=self._headers(headers),
                    timeout=(3, self.timeout),
                )
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Gọi %s %s thất bại (lần %s): %s", method, url, attempt + 1, exc)
                discovery.invalidate(self.name)
                if never_connected(exc) and attempts == 1 and attempt == 0:
                    attempts = 2  # chưa gửi được request -> an toàn để thử instance khác
                attempt += 1
                if attempt < attempts:
                    time.sleep(0.3 * attempt)
                continue
            if resp.status_code >= 500:
                self.breaker.failure()
            else:
                self.breaker.success()
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:500]}
            return resp.status_code, body
        self.breaker.failure()
        log.error("Dịch vụ %s không phản hồi: %s", self.name, last_exc)
        raise ApiError(503, f"Không kết nối được dịch vụ {self.label}", code="SERVICE_UNAVAILABLE",
                       details={"service": self.name})

    def call(self, method, path, json=None, params=None, headers=None, expect=(200, 201), retries=None):
        """Như request() nhưng ném ApiError nếu mã trả về không nằm trong `expect`.

        Lỗi 4xx của service đích được giữ nguyên (thông điệp + mã), lỗi 5xx -> 502.
        """
        status, body = self.request(method, path, json=json, params=params, headers=headers, retries=retries)
        if status in expect:
            return body
        error = body.get("error") if isinstance(body, dict) else None
        message = (error or {}).get("message") or f"Dịch vụ {self.label} trả về lỗi {status}"
        code = (error or {}).get("code")
        details = (error or {}).get("details")
        if status >= 500:
            raise ApiError(502, message, code=code or "UPSTREAM_ERROR", details=details)
        raise ApiError(status, message, code=code, details=details)

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, json=None, **kw):
        return self.call("POST", path, json=json, **kw)

    def put(self, path, json=None, **kw):
        return self.call("PUT", path, json=json, **kw)

    def delete(self, path, **kw):
        return self.call("DELETE", path, **kw)
