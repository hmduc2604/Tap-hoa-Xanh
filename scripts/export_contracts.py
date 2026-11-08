"""Xuất hợp đồng dịch vụ ra thư mục contracts/ (OpenAPI JSON cho từng service + WSDL của CatalogService).

    python scripts/export_contracts.py          # ghi file
    python scripts/export_contracts.py --check  # chỉ kiểm tra file đã khớp với code chưa (dùng trong CI)

Hợp đồng được sinh từ chính code nên file trong contracts/ luôn có thể tạo lại; --check báo lỗi
nếu ai đó sửa API mà quên cập nhật hợp đồng.
"""
import argparse
import glob
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ["SERVICE_DISCOVERY"] = "0"
os.environ.pop("FRONTEND_DIR", None)
os.environ["LOG_LEVEL"] = "ERROR"
OUT = os.path.join(ROOT, "contracts")


def load(path, name):
    os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/contract.db"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(path))
    spec.loader.exec_module(module)
    return module


def build_all():
    from common.contract import build_openapi

    files = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "services", "*", "*", "app.py"))):
        folder = os.path.basename(os.path.dirname(path))
        module = load(path, folder.replace("-", "_"))
        app = module.app
        doc = build_openapi(app, app.config["SERVICE_NAME"], app.config["SERVICE_VERSION"], app.config["SERVICE_LAYER"],
                            app.config["SERVICE_DESCRIPTION"], include_internal=True)
        files[f"openapi/{folder}.json"] = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    gw = load(os.path.join(ROOT, "integration", "gateway", "app.py"), "gateway_app")
    with gw.app.test_request_context(base_url="http://localhost:8080"):
        files["openapi/api-gateway.json"] = json.dumps(gw.gateway_contract(), ensure_ascii=False, indent=2) + "\n"
    files["wsdl/catalog.wsdl"] = gw.soap.wsdl("http://localhost:8080/api/soap/catalog")
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = build_all()
    stale = []
    for rel, content in files.items():
        path = os.path.join(OUT, rel)
        current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if args.check:
            if current != content:
                stale.append(rel)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        print("ghi", os.path.relpath(path, ROOT))
    if args.check:
        if stale:
            print("Hợp đồng chưa khớp code, chạy lại scripts/export_contracts.py:", ", ".join(stale))
            sys.exit(1)
        print(f"{len(files)} hợp đồng khớp với code")


if __name__ == "__main__":
    main()
