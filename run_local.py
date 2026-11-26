"""Chạy toàn bộ hệ thống trên máy cá nhân KHÔNG cần Docker.

- Service Registry cổng 8500, mỗi service là một tiến trình Python riêng (cổng 8001-8008),
  tự đăng ký vào registry; API Gateway cổng 8000 tìm service qua registry
- CSDL: SQLite riêng cho từng service trong thư mục ./data
- Event bus: chế độ "http" (thay cho RabbitMQ)

Cách dùng:
    pip install -r requirements-local.txt
    python run_local.py            # chạy
    python run_local.py --reset    # xóa dữ liệu cũ rồi chạy lại từ đầu
    python run_local.py --scale product=2   # chạy 2 instance product-service (cân bằng tải qua registry)
Mở trình duyệt: http://localhost:8000
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")

# (thư mục theo lớp SOA, cổng)
SERVICES = [
    ("entity/auth-service", 8001),
    ("entity/product-service", 8002),
    ("entity/inventory-service", 8003),
    ("entity/cart-service", 8004),
    ("task/order-service", 8005),
    ("entity/payment-service", 8006),
    ("entity/promotion-service", 8007),
    ("utility/notification-service", 8008),
    ("utility/ai-service", 8009),
]
REGISTRY_PORT = 8500


def short_name(path):
    return path.split("/")[-1].replace("-service", "")


def wait_healthy(url, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main():
    parser = argparse.ArgumentParser(description="Chạy hệ thống Tạp Hóa Xanh ở chế độ local")
    parser.add_argument("--reset", action="store_true", help="Xóa dữ liệu SQLite cũ trước khi chạy")
    parser.add_argument("--quiet", action="store_true", help="Ẩn log truy cập của các service")
    parser.add_argument("--scale", action="append", default=[], metavar="TÊN=SỐ",
                        help="Số instance cho một service, ví dụ --scale product=2")
    args = parser.parse_args()
    scale = {}
    for item in args.scale:
        name, _, count = item.partition("=")
        scale[name.strip().replace("-service", "")] = max(1, int(count or 1))

    if args.reset and os.path.isdir(DATA):
        shutil.rmtree(DATA)
    os.makedirs(DATA, exist_ok=True)

    base_env = dict(os.environ)
    base_env.update({
        "PYTHONPATH": ROOT + os.pathsep + base_env.get("PYTHONPATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "EVENT_BUS": "http",
        "EVENT_HTTP_SUBSCRIBERS": ",".join(f"http://127.0.0.1:{port}" for _, port in SERVICES),
        "REGISTRY_URL": f"http://127.0.0.1:{REGISTRY_PORT}",
        "HOST": "127.0.0.1",
        "LOG_LEVEL": "WARNING" if args.quiet else "INFO",
    })
    for name, port in SERVICES:
        base_env[f"{short_name(name).upper()}_SERVICE_URL"] = f"http://127.0.0.1:{port}"

    procs = []

    def shutdown(*_):
        print("\nĐang dừng các service...")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    # Mặc định SQLite. Muốn dùng PostgreSQL có sẵn trên máy, đặt biến môi trường, ví dụ:
    #   DATABASE_URL_TEMPLATE=postgresql://grocery:grocery@localhost:5432/{name}_db
    template = os.environ.get("DATABASE_URL_TEMPLATE")

    reg_env = dict(base_env, PORT=str(REGISTRY_PORT), SERVICE_ADVERTISE_URL=f"http://127.0.0.1:{REGISTRY_PORT}")
    procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "integration", "registry", "app.py")], env=reg_env, cwd=ROOT))
    print(f"  -> {'registry':<22} http://127.0.0.1:{REGISTRY_PORT}  (Service Registry)")
    if not wait_healthy(f"http://127.0.0.1:{REGISTRY_PORT}/health"):
        print("[LỖI] Service Registry không khởi động được.")
        shutdown()

    started = []
    for name, port in SERVICES:
        short = short_name(name)
        db_url = template.format(name=short) if template else f"sqlite:///{os.path.join(DATA, short + '.db')}"
        for k in range(scale.get(short, 1)):
            p = port + 1000 * k  # instance thứ 2 của product chạy cổng 9002, thứ 3 cổng 10002...
            env = dict(base_env, PORT=str(p), DATABASE_URL=db_url, SERVICE_ADVERTISE_URL=f"http://127.0.0.1:{p}")
            procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "services", *name.split("/"), "app.py")],
                                          env=env, cwd=ROOT))
            started.append((name, p))
            print(f"  -> {name:<30} http://127.0.0.1:{p}")

    for name, port in started:
        if not wait_healthy(f"http://127.0.0.1:{port}/health"):
            print(f"[LỖI] {name} không khởi động được, xem log phía trên.")
            shutdown()

    gw_env = dict(base_env, PORT="8000", HOST=os.environ.get("GATEWAY_HOST", "127.0.0.1"), FRONTEND_DIR=os.path.join(ROOT, "frontend"))
    procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "integration", "gateway", "app.py")], env=gw_env, cwd=ROOT))
    if not wait_healthy("http://127.0.0.1:8000/"):
        print("[LỖI] API Gateway không khởi động được.")
        shutdown()

    print("\n" + "=" * 62)
    print("  Tạp Hóa Xanh đã sẵn sàng!")
    print("  Cửa hàng : http://localhost:8000")
    print("  Quản trị : http://localhost:8000/admin/")
    print("  Health   : http://localhost:8000/api/health")
    print("  Hợp đồng : http://localhost:8000/api-docs.html  (OpenAPI + WSDL)")
    print("  Tài khoản: admin@taphoa.vn / Admin@123  |  staff@taphoa.vn / Staff@123")
    print("             khach@taphoa.vn / Khach@123")
    print("  Nhấn Ctrl+C để dừng.")
    print("=" * 62 + "\n")

    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    print(f"[CẢNH BÁO] Một tiến trình đã dừng (mã {p.returncode}).")
                    procs.remove(p)
                    break
            time.sleep(2)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
