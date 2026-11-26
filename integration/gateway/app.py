"""API Gateway — tầng tích hợp (Integration layer / ESB nhẹ) của hệ thống SOA.

Chức năng:
- Định tuyến /api/* tới service theo TÊN, địa chỉ tra cứu từ Service Registry
  (xoay vòng giữa các instance, tự chuyển instance khi một instance chết)
- Xác thực JWT tập trung, chuyển danh tính xuống service qua header nội bộ
- Dàn xếp giao thức: CatalogService SOAP/WSDL <-> REST (xem soap.py)
- Công bố hợp đồng dịch vụ OpenAPI của mọi service: /api/contracts
- Rate limiting theo IP, X-Request-ID để truy vết, alias phiên bản /api/v1/*
- Health check tổng hợp & API Composition cho dashboard quản trị
- (Chế độ local) phục vụ luôn giao diện web tĩnh
"""
import logging
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import requests  # noqa: E402
from flask import Flask, Response, g, jsonify, request, send_from_directory  # noqa: E402

import soap  # noqa: E402
from common.app_factory import setup_logging  # noqa: E402
from common.auth import STAFF_ROLES, decode_token, identity_headers  # noqa: E402
from common.config import INTERNAL_API_KEY, SERVICE_DEFAULTS, env, env_int  # noqa: E402
from common.contract import build_openapi  # noqa: E402
from common.errors import ApiError, register_error_handlers  # noqa: E402
from common.http_client import SERVICE_LABELS, ServiceClient, never_connected  # noqa: E402
from common.registry import discovery  # noqa: E402
from common.utils import now_str, today_str  # noqa: E402

setup_logging("api-gateway")
log = logging.getLogger("gateway")

# (tiền tố đường dẫn, tên service)
ROUTES = [
    ("/api/auth", "auth"), ("/api/users", "auth"),
    ("/api/categories", "product"), ("/api/products", "product"),
    ("/api/inventory", "inventory"), ("/api/suppliers", "inventory"), ("/api/stock-receipts", "inventory"),
    ("/api/cart", "cart"),
    ("/api/orders", "order"), ("/api/pos", "order"), ("/api/reports", "order"),
    ("/api/payments", "payment"),
    ("/api/coupons", "promotion"),
    ("/api/notifications", "notification"),
    ("/api/ai", "ai"),
]
# Các route không bắt buộc đăng nhập (method, tiền tố)
PUBLIC_ROUTES = [
    ("POST", "/api/auth/register"), ("POST", "/api/auth/login"),
    ("GET", "/api/categories"), ("GET", "/api/products"),
    ("GET", "/api/coupons/available"), ("GET", "/api/payments/methods"),
    ("GET", "/api/ai/recommendations"), ("GET", "/api/ai/status"),
]
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length", "content-encoding"}
STRIP_INBOUND = {"x-user-id", "x-user-role", "x-user-name", "x-user-email", "x-internal-token"}

RATE_LIMIT = env_int("RATE_LIMIT_PER_MINUTE", 600)
LOGIN_RATE_LIMIT = env_int("LOGIN_RATE_LIMIT_PER_MINUTE", 20)
FRONTEND_DIR = env("FRONTEND_DIR")
CORS_ORIGIN = env("CORS_ORIGIN", "*")
UPSTREAM_TIMEOUT = env_int("UPSTREAM_TIMEOUT", 30)

app = Flask("api-gateway", static_folder=None)
app.json.ensure_ascii = False
app.json.sort_keys = False
register_error_handlers(app)
http = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=50)
http.mount("http://", adapter)


# =================================================================== Rate limit
class RateLimiter:
    """Token bucket theo khóa (IP / IP+route), lưu trong bộ nhớ."""

    def __init__(self):
        self.buckets = {}
        self.lock = threading.Lock()

    def allow(self, key, per_minute):
        now = time.time()
        rate = per_minute / 60.0
        with self.lock:
            tokens, last = self.buckets.get(key, (per_minute, now))
            tokens = min(per_minute, tokens + (now - last) * rate)
            if tokens < 1:
                self.buckets[key] = (tokens, now)
                return False, int((1 - tokens) / rate) + 1
            self.buckets[key] = (tokens - 1, now)
            if len(self.buckets) > 50000:
                self.buckets.clear()
            return True, 0


limiter = RateLimiter()


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "unknown")


# =================================================================== Middleware
@app.before_request
def before():
    g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    g.started = time.time()
    if request.method == "OPTIONS":
        return Response(status=204)
    if request.path.startswith("/api/"):
        ip = client_ip()
        ok, retry = limiter.allow(ip, RATE_LIMIT)
        if ok and request.path == "/api/auth/login":
            ok, retry = limiter.allow(f"login:{ip}", LOGIN_RATE_LIMIT)
        if not ok:
            resp = jsonify(ApiError(429, "Bạn thao tác quá nhanh, vui lòng thử lại sau ít phút").to_dict())
            resp.status_code = 429
            resp.headers["Retry-After"] = str(retry)
            return resp


@app.after_request
def after(resp):
    resp.headers["X-Request-ID"] = g.get("request_id", "")
    resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Request-ID"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Expose-Headers"] = "X-Request-ID, X-Service, X-Instance"
    if request.path.startswith("/api/"):
        log.info("%s %s -> %s (%.0f ms) rid=%s", request.method, request.full_path.rstrip("?"), resp.status_code,
                 (time.time() - g.get("started", time.time())) * 1000, g.get("request_id"))
    return resp


def authenticate(required):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return decode_token(header[7:].strip())  # token sai/hết hạn -> 401 kể cả route công khai
    if required:
        raise ApiError(401, "Bạn cần đăng nhập để thực hiện thao tác này")
    return None


def resolve(path):
    for prefix, name in ROUTES:
        if path == prefix or path.startswith(prefix + "/"):
            return name
    return None


def is_public(method, path):
    return any(method == m and (path == p or path.startswith(p + "/")) for m, p in PUBLIC_ROUTES)


# =================================================================== Endpoint riêng của gateway
CLIENTS = {name: ServiceClient(name, timeout=5) for name in SERVICE_DEFAULTS}
executor = ThreadPoolExecutor(max_workers=16)


BUSINESS_SERVICES = [n for n in SERVICE_DEFAULTS if n != "registry"]
SERVICE_LABELS = {**SERVICE_LABELS, "registry": "Danh bạ dịch vụ"}


def _check(name):
    started = time.time()
    base, source = CLIENTS[name].resolve()
    instances = len(discovery.instances(name)) if name != "registry" else 1
    try:
        resp = http.get(base + "/health", timeout=3)
        body = resp.json()
        status = body.get("status", "UP") if resp.status_code == 200 else body.get("status", "DOWN")
        return name, {"status": status, "latency_ms": round((time.time() - started) * 1000), "layer": body.get("layer"),
                      "database": (body.get("database") or {}).get("type"), "url": base, "discovery": source,
                      "instances": instances}
    except Exception as exc:
        return name, {"status": "DOWN", "error": str(exc)[:150], "url": base, "discovery": source, "instances": instances}


@app.get("/api/health")
def health():
    """Trạng thái gateway và từng service (độ trễ, lớp dịch vụ, nguồn địa chỉ, circuit breaker)"""
    results = dict(executor.map(_check, SERVICE_DEFAULTS))
    for name, info in results.items():
        info["label"] = SERVICE_LABELS.get(name, name)
        info["circuit"] = CLIENTS[name].breaker.state
    all_up = all(r["status"] == "UP" for r in results.values())
    return jsonify({"gateway": "UP", "status": "UP" if all_up else "DEGRADED", "time": now_str(),
                    "event_bus": env("EVENT_BUS", "none"), "services": results}), 200 if all_up else 207


def require_staff_token():
    user = authenticate(required=True)
    if user["role"] not in STAFF_ROLES:
        raise ApiError(403, "Chỉ nhân viên / quản trị viên được truy cập")
    return user


@app.get("/api/registry")
def registry_view():
    """Danh bạ dịch vụ: các service, lớp dịch vụ, phiên bản và instance đang chạy"""
    require_staff_token()
    try:
        data = CLIENTS["registry"].get("/registry/services")
    except ApiError as exc:
        raise ApiError(503, "Không liên lạc được Service Registry, hệ thống đang dùng địa chỉ cấu hình dự phòng",
                       code="REGISTRY_UNAVAILABLE", details={"reason": exc.message})
    return jsonify(data)


registry_view._auth = {"type": "roles", "roles": list(STAFF_ROLES)}


def gateway_contract():
    doc = build_openapi(app, "api-gateway", "1.0.0", "integration",
                        "Tầng tích hợp: định tuyến, xác thực, hợp đồng dịch vụ, dàn xếp SOAP/REST", include_internal=False)
    doc["paths"] = {p: v for p, v in doc["paths"].items() if not p.startswith("/api/{") and "{filename}" not in p and p != "/"}
    doc["servers"] = [{"url": request.host_url.rstrip("/")}]
    return doc


@app.get("/api/contracts")
def contracts_index():
    """Danh mục dịch vụ (service inventory) và đường dẫn tới hợp đồng của từng service"""
    try:
        services = CLIENTS["registry"].get("/registry/services")["services"]
    except ApiError:
        services = {}
    items = []
    for name in BUSINESS_SERVICES:
        info = services.get(name, {})
        items.append({"service": name, "label": SERVICE_LABELS.get(name, name), "layer": info.get("layer"),
                      "version": info.get("version"), "description": info.get("description"),
                      "instances_up": info.get("up", 0), "openapi": f"/api/contracts/{name}"})
    items.append({"service": "api-gateway", "label": "API Gateway / ESB", "layer": "integration", "version": "1.0.0",
                  "description": "Định tuyến, xác thực, hợp đồng dịch vụ, dàn xếp SOAP/REST", "instances_up": 1,
                  "openapi": "/api/contracts/gateway", "wsdl": "/api/soap/catalog?wsdl"})
    return jsonify({"items": items, "registry_available": bool(services)})


@app.get("/api/contracts/<name>")
def contract_detail(name):
    """Hợp đồng OpenAPI công khai của một service (đã bỏ API nội bộ)"""
    if name == "gateway":
        return jsonify(gateway_contract())
    if name not in BUSINESS_SERVICES:
        raise ApiError(404, "Không có service này")
    doc = CLIENTS[name].get("/contract", params={"public": 1})
    doc["servers"] = [{"url": request.host_url.rstrip("/"), "description": "Qua API Gateway"}]
    return jsonify(doc)


@app.get("/api/soap/catalog")
def soap_wsdl():
    """WSDL của CatalogService (thêm ?wsdl)"""
    endpoint = request.host_url.rstrip("/") + "/api/soap/catalog"
    if "wsdl" not in request.args:
        return jsonify({"service": "CatalogService", "protocol": "SOAP 1.1 document/literal", "endpoint": endpoint,
                        "wsdl": endpoint + "?wsdl", "operations": list(soap.OPERATIONS)})
    return Response(soap.wsdl(endpoint), mimetype="text/xml")


@app.post("/api/soap/catalog")
def soap_endpoint():
    """CatalogService SOAP: GetCategories, SearchProducts, GetProduct (ESB chuyển sang REST product-service)"""
    status, xml = soap.handle(request.get_data(cache=False), CLIENTS["product"])
    return Response(xml, status=status, mimetype="text/xml")


@app.get("/api/dashboard")
def dashboard():
    """API Composition: gộp dữ liệu từ nhiều service cho trang tổng quan quản trị"""
    require_staff_token()
    date_from, date_to = request.args.get("date_from"), request.args.get("date_to")
    today = today_str()
    calls = {
        "report": ("order", "/internal/orders/report", {"date_from": date_from, "date_to": date_to}),
        "today": ("order", "/internal/orders/report", {"date_from": today, "date_to": today}),
        "recent_orders": ("order", "/internal/orders/recent", {"limit": 8}),
        "inventory": ("inventory", "/internal/inventory/summary", None),
        "products": ("product", "/internal/products/stats", None),
        "users": ("auth", "/internal/users/stats", None),
    }

    def fetch(item):
        key, (svc, path, params) = item
        try:
            return key, CLIENTS[svc].get(path, params={k: v for k, v in (params or {}).items() if v}), None
        except ApiError as exc:
            return key, None, {"service": svc, "message": exc.message}

    data, errors = {}, []
    for key, value, err in executor.map(fetch, calls.items()):
        data[key] = value
        if err:
            errors.append(err)
    data["errors"] = errors
    data["partial"] = bool(errors)
    return jsonify(data)


dashboard._auth = {"type": "roles", "roles": list(STAFF_ROLES)}


# =================================================================== Reverse proxy
@app.route("/api/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def proxy(subpath):
    if subpath.startswith("v1/"):  # phiên bản hợp đồng: /api/v1/... tương đương /api/...
        subpath = subpath[3:]
    path = "/api/" + subpath
    service = resolve(path)
    if not service:
        raise ApiError(404, "Không tìm thấy API")
    user = authenticate(required=not is_public(request.method, path))

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP | STRIP_INBOUND}
    headers.pop("Authorization", None)
    headers.update({"X-Internal-Token": INTERNAL_API_KEY, "X-Request-ID": g.request_id,
                    "X-Forwarded-For": client_ip()})
    if user:
        headers.update(identity_headers(user))
    query = ("?" + request.query_string.decode("utf-8", "ignore")) if request.query_string else ""
    body = request.get_data()
    for attempt in range(2):
        base, source = CLIENTS[service].resolve()
        try:
            upstream = http.request(request.method, base + path + query, data=body, headers=headers,
                                    timeout=(3, UPSTREAM_TIMEOUT), allow_redirects=False)
            break
        except requests.RequestException as exc:
            discovery.invalidate(service)
            if attempt == 0 and never_connected(exc) and source == "registry":
                log.warning("Instance %s của %s không phản hồi, thử instance khác", base, service)
                continue  # chưa kết nối được -> request chưa tới service, an toàn để thử instance khác
            log.error("Upstream %s lỗi: %s", service, exc)
            raise ApiError(503, f"Dịch vụ {SERVICE_LABELS.get(service, service)} hiện không khả dụng, vui lòng thử lại sau",
                           code="SERVICE_UNAVAILABLE", details={"service": service})
    out_headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP]
    return Response(upstream.content, status=upstream.status_code, headers=out_headers)


# =================================================================== Frontend (chế độ local)
if FRONTEND_DIR:
    frontend_root = os.path.abspath(FRONTEND_DIR)

    @app.get("/")
    @app.get("/<path:filename>")
    def frontend(filename="index.html"):
        full = os.path.join(frontend_root, filename)
        if os.path.isdir(full):
            filename = filename.rstrip("/") + "/index.html"
        return send_from_directory(frontend_root, filename)
else:
    @app.get("/")
    def index():
        return jsonify({"service": "api-gateway", "status": "UP", "docs": "/api/health"})


def create_app():
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    log.info("API Gateway chạy tại http://localhost:%s", port)
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=port, threaded=True, debug=False, use_reloader=False)
