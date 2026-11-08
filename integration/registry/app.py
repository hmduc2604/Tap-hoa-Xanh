"""registry-service: Service Registry (danh bạ dịch vụ) của hệ thống SOA.

- Mỗi instance service tự đăng ký (self-registration) khi khởi động: tên, địa chỉ,
  phiên bản, lớp dịch vụ (task / entity / utility), địa chỉ hợp đồng OpenAPI.
- Instance gửi heartbeat định kỳ; quá TTL không gửi sẽ bị đánh dấu DOWN và bị loại
  khỏi kết quả tra cứu, quá 5 lần TTL sẽ bị xóa khỏi danh bạ.
- Bên gọi (gateway, service khác) tra cứu địa chỉ theo tên dịch vụ (client-side discovery),
  nên có thể chạy nhiều instance của một service mà không phải sửa cấu hình.
Dữ liệu lưu trong bộ nhớ: nếu registry khởi động lại, các instance tự đăng ký lại ở
lần heartbeat kế tiếp (heartbeat nhận 404 -> đăng ký lại).
"""
import os
import sys
import threading
import time
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.app_factory import create_base_app, run_dev  # noqa: E402
from common.auth import internal_only  # noqa: E402
from common.config import env_int  # noqa: E402
from common.errors import ApiError, bad_request  # noqa: E402
from common.utils import clean_str, get_json, now_str  # noqa: E402

SERVICE = "registry-service"
TTL = env_int("REGISTRY_TTL_SECONDS", 30)
LAYERS = ("task", "entity", "utility", "integration", "infrastructure")

app = create_base_app(SERVICE, layer="infrastructure",
                      description="Danh bạ dịch vụ: đăng ký, heartbeat và tra cứu địa chỉ các service")
_lock = threading.Lock()
_instances = {}  # {service_name: {instance_id: record}}


def _view(rec, now):
    age = now - rec["last_heartbeat"]
    return {
        "instance_id": rec["instance_id"], "url": rec["url"], "status": "UP" if age <= TTL else "DOWN",
        "last_seen_seconds": round(age, 1), "registered_at": rec["registered_at"],
        "health_url": rec["health_url"], "contract_url": rec["contract_url"], "metadata": rec["metadata"],
    }


def _touch_self():
    me = _instances.get("registry", {}).get("registry-self")
    if me:
        me["last_heartbeat"] = time.time()


def _purge(now):
    for name in list(_instances):
        for iid, rec in list(_instances[name].items()):
            if now - rec["last_heartbeat"] > 5 * TTL:
                del _instances[name][iid]
        if not _instances[name]:
            del _instances[name]


@app.post("/registry/instances")
@internal_only
def register():
    """Đăng ký một instance service vào danh bạ"""
    data = get_json()
    name = clean_str(data.get("service"), 50)
    url = clean_str(data.get("url"), 200)
    if not name or not url:
        raise bad_request("Cần có 'service' và 'url'")
    layer = data.get("layer") or "entity"
    if layer not in LAYERS:
        raise bad_request("Lớp dịch vụ phải là một trong: " + ", ".join(LAYERS))
    iid = clean_str(data.get("instance_id"), 80) or f"{name}-{uuid.uuid4().hex[:6]}"
    url = url.rstrip("/")
    rec = {
        "instance_id": iid, "service": name, "url": url, "layer": layer,
        "version": clean_str(data.get("version"), 20) or "1.0.0",
        "description": clean_str(data.get("description"), 300) or "",
        "health_url": clean_str(data.get("health_url"), 200) or url + "/health",
        "contract_url": clean_str(data.get("contract_url"), 200) or url + "/contract",
        "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        "registered_at": now_str(), "last_heartbeat": time.time(),
    }
    with _lock:
        _instances.setdefault(name, {})[iid] = rec
    app.logger.info("Đăng ký %s (%s) tại %s", name, iid, url)
    return {"instance_id": iid, "ttl": TTL, "heartbeat_interval": max(3, TTL // 3)}, 201


@app.put("/registry/instances/<name>/<iid>/heartbeat")
@internal_only
def heartbeat(name, iid):
    """Gia hạn trạng thái sống của một instance (gọi định kỳ)"""
    with _lock:
        rec = _instances.get(name, {}).get(iid)
        if not rec:
            raise ApiError(404, "Instance chưa đăng ký", code="NOT_REGISTERED")
        rec["last_heartbeat"] = time.time()
    return {"status": "UP", "ttl": TTL}


@app.delete("/registry/instances/<name>/<iid>")
@internal_only
def deregister(name, iid):
    """Hủy đăng ký instance (khi service tắt có kiểm soát)"""
    with _lock:
        removed = _instances.get(name, {}).pop(iid, None)
    return {"removed": bool(removed)}


@app.get("/registry/services")
@internal_only
def list_services():
    """Toàn bộ danh bạ: mọi service, lớp dịch vụ, phiên bản và các instance"""
    with _lock:
        _touch_self()
        now = time.time()
        _purge(now)
        result = {}
        for name, items in sorted(_instances.items()):
            views = [_view(r, now) for r in items.values()]
            newest = max(items.values(), key=lambda r: r["last_heartbeat"])
            result[name] = {
                "layer": newest["layer"], "version": newest["version"], "description": newest["description"],
                "up": sum(1 for v in views if v["status"] == "UP"), "instances": views,
            }
    return {"ttl": TTL, "time": now_str(), "services": result}


@app.get("/registry/services/<name>")
@internal_only
def lookup(name):
    """Tra cứu các instance đang hoạt động của một service theo tên"""
    now = time.time()
    with _lock:
        items = list(_instances.get(name, {}).values())
    up = [_view(r, now) for r in items if now - r["last_heartbeat"] <= TTL]
    return {"service": name, "instances": up}


def create_app():
    # registry tự đăng ký chính nó để hiển thị chung trong danh bạ
    port = int(os.environ.get("PORT", 8500))
    url = (os.environ.get("SERVICE_ADVERTISE_URL") or f"http://127.0.0.1:{port}").rstrip("/")
    _instances["registry"] = {"registry-self": {
        "instance_id": "registry-self", "service": "registry", "url": url, "layer": "infrastructure", "version": "1.0.0",
        "description": "Danh bạ dịch vụ", "health_url": url + "/health", "contract_url": url + "/contract",
        "metadata": {"self": True}, "registered_at": now_str(), "last_heartbeat": time.time(),
    }}
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8500)
