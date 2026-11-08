"""Tạo Flask app chuẩn cho mọi service: logging, request-id, xử lý lỗi, /health, /contract, đăng ký registry."""
import logging
import os
import time
import uuid

from flask import Flask, g, request

from common.contract import build_openapi
from common.errors import register_error_handlers
from common.utils import now_str, parse_bool

# Phân lớp dịch vụ theo mô hình SOA (Thomas Erl):
#   task    - service điều phối quy trình nghiệp vụ (vd: đặt hàng)
#   entity  - service quản lý một thực thể nghiệp vụ, tái sử dụng cho nhiều quy trình
#   utility - service hạ tầng dùng chung, không gắn nghiệp vụ cụ thể (vd: thông báo)
LAYERS = ("task", "entity", "utility", "integration", "infrastructure")


def setup_logging(service_name):
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format=f"%(asctime)s [{service_name}] %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def create_base_app(service_name, db=None, version="1.0.0", layer="entity", description=""):
    assert layer in LAYERS, layer
    setup_logging(service_name)
    app = Flask(service_name)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.config.update(SERVICE_NAME=service_name, SERVICE_VERSION=version, SERVICE_LAYER=layer,
                      SERVICE_DESCRIPTION=description, INSTANCE_ID=f"{service_name}-local")
    access_log = logging.getLogger("access")

    @app.before_request
    def _before():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        g.started_at = time.time()

    @app.after_request
    def _after(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["X-Service"] = service_name
        response.headers["X-Instance"] = app.config["INSTANCE_ID"]
        if request.path != "/health" and not request.path.startswith("/registry/instances"):
            elapsed = (time.time() - g.get("started_at", time.time())) * 1000
            access_log.info("%s %s -> %s (%.0f ms) rid=%s", request.method, request.full_path.rstrip("?"),
                            response.status_code, elapsed, g.get("request_id"))
        return response

    @app.get("/health")
    def _health():
        """Kiểm tra trạng thái service và kết nối CSDL"""
        body = {"service": service_name, "version": version, "layer": layer, "instance": app.config["INSTANCE_ID"],
                "status": "UP", "time": now_str()}
        if db is not None:
            ok = db.ping()
            body["database"] = {"type": db.kind, "status": "UP" if ok else "DOWN"}
            if not ok:
                body["status"] = "DEGRADED"
                return body, 503
        return body

    @app.get("/contract")
    def _contract():
        """Hợp đồng dịch vụ OpenAPI 3 (?public=1 để bỏ các API nội bộ)"""
        return build_openapi(app, service_name, version, layer, description,
                             include_internal=not parse_bool(request.args.get("public")))

    register_error_handlers(app)
    return app


def register_service(app, name, default_port):
    """Tự đăng ký instance vào Service Registry và gửi heartbeat nền."""
    from common.registry import ServiceRegistration

    reg = ServiceRegistration(app, name, default_port, app.config["SERVICE_LAYER"],
                              app.config["SERVICE_VERSION"], app.config["SERVICE_DESCRIPTION"])
    reg.start()
    return reg


def run_dev(app, default_port):
    port = int(os.environ.get("PORT", default_port))
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=port, threaded=True, debug=False, use_reloader=False)
