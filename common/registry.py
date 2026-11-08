"""Client cho Service Registry: tự đăng ký (self-registration) và tra cứu dịch vụ (client-side discovery).

- ServiceRegistration: chạy nền trong mỗi service, đăng ký rồi gửi heartbeat định kỳ.
- discovery.resolve(name): trả về địa chỉ một instance đang UP (xoay vòng round-robin
  nếu có nhiều instance). Nếu registry không liên lạc được hoặc chưa có instance nào,
  dùng địa chỉ cấu hình tĩnh (*_SERVICE_URL) làm phương án dự phòng.
"""
import atexit
import itertools
import logging
import os
import socket
import threading
import time

import requests

from common.config import INTERNAL_API_KEY, env, env_bool, service_url

log = logging.getLogger(__name__)
HEADERS = {"X-Internal-Token": INTERNAL_API_KEY}


def registry_url():
    return env("REGISTRY_URL", service_url("registry")).rstrip("/")


def discovery_enabled():
    return env_bool("SERVICE_DISCOVERY", True)


def advertise_url(port):
    url = env("SERVICE_ADVERTISE_URL")
    if url:
        return url.rstrip("/")
    try:
        host = socket.gethostbyname(socket.gethostname())
    except OSError:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


class ServiceRegistration:
    def __init__(self, app, name, default_port, layer, version="1.0.0", description=""):
        self.name = name
        self.port = int(os.environ.get("PORT", default_port))
        self.layer = layer
        self.version = version
        self.description = description
        self.url = advertise_url(self.port)
        self.instance_id = f"{name}-{socket.gethostname()[:12]}-{self.port}"
        self.registered = False
        app.config["INSTANCE_ID"] = self.instance_id
        self._started = False

    def payload(self):
        return {
            "service": self.name, "instance_id": self.instance_id, "url": self.url, "version": self.version,
            "layer": self.layer, "description": self.description,
            "health_url": self.url + "/health", "contract_url": self.url + "/contract",
            "metadata": {"pid": os.getpid(), "host": socket.gethostname()},
        }

    def start(self):
        if self._started or not discovery_enabled():
            return
        self._started = True
        threading.Thread(target=self._loop, daemon=True, name=f"{self.name}-registration").start()
        atexit.register(self.deregister)

    def _loop(self):
        interval = 10
        while True:
            base = registry_url()
            try:
                if not self.registered:
                    resp = requests.post(base + "/registry/instances", json=self.payload(), headers=HEADERS, timeout=3)
                    if resp.status_code in (200, 201):
                        self.registered = True
                        interval = int(resp.json().get("heartbeat_interval", 10))
                        log.info("Đã đăng ký vào registry: %s -> %s", self.instance_id, self.url)
                else:
                    resp = requests.put(f"{base}/registry/instances/{self.name}/{self.instance_id}/heartbeat",
                                        headers=HEADERS, timeout=3)
                    if resp.status_code == 404:  # registry khởi động lại -> đăng ký lại ngay
                        self.registered = False
                        continue
            except requests.RequestException as exc:
                if self.registered:
                    log.warning("Mất kết nối registry (%s), sẽ đăng ký lại", exc)
                self.registered = False
            time.sleep(interval if self.registered else 3)

    def deregister(self):
        if not self.registered:
            return
        try:
            requests.delete(f"{registry_url()}/registry/instances/{self.name}/{self.instance_id}", headers=HEADERS, timeout=1)
        except requests.RequestException:
            pass


class Discovery:
    def __init__(self, cache_seconds=5):
        self.cache_seconds = cache_seconds
        self._cache = {}
        self._counters = {}
        self._lock = threading.Lock()

    def instances(self, name):
        """Danh sách URL các instance đang UP (có cache ngắn để giảm tải registry)."""
        if not discovery_enabled() or name == "registry":
            return []
        now = time.time()
        cached = self._cache.get(name)
        if cached and cached[0] > now:
            return cached[1]
        urls = []
        try:
            resp = requests.get(f"{registry_url()}/registry/services/{name}", headers=HEADERS, timeout=(1, 2))
            if resp.status_code == 200:
                urls = [i["url"] for i in resp.json().get("instances", [])]
        except requests.RequestException:
            urls = []
        self._cache[name] = (now + self.cache_seconds, urls)
        return urls

    def resolve(self, name):
        """(url, nguồn) — nguồn là 'registry' hoặc 'static' (dự phòng khi registry lỗi)."""
        urls = self.instances(name)
        if not urls:
            return service_url(name), "static"
        with self._lock:
            counter = self._counters.setdefault(name, itertools.count())
            index = next(counter) % len(urls)
        return urls[index], "registry"

    def invalidate(self, name):
        self._cache.pop(name, None)

    def all_services(self):
        """{tên service: [url...]} của mọi service đang UP, dùng cho event bus chế độ HTTP."""
        if not discovery_enabled():
            return {}
        try:
            resp = requests.get(f"{registry_url()}/registry/services", headers=HEADERS, timeout=(1, 2))
            if resp.status_code != 200:
                return {}
            return {name: [i["url"] for i in info["instances"] if i["status"] == "UP"]
                    for name, info in resp.json()["services"].items() if name != "registry"}
        except requests.RequestException:
            return {}


discovery = Discovery()
