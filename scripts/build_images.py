"""Gộp danh sách ảnh sản phẩm (đã thu thập từ nguồn mở) thành common/catalog/images.json.

Đầu vào: các file TSV `sku<TAB>mã-nén` (do bước tìm ảnh tạo ra):
  W<đường dẫn>  -> ảnh Wikimedia Commons thu nhỏ 500px
  O<đường dẫn>  -> ảnh Open Food Facts
  F<đường dẫn>  -> ảnh Commons gốc (đổi sang bản thu nhỏ 500px)
  http...       -> URL đầy đủ
Thứ tự ưu tiên khi trùng SKU: Open Food Facts > Wikipedia/Commons.
Chỉ giữ SKU có trong danh mục seed.
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common import seed_data  # noqa: E402

COMMONS = "https://upload.wikimedia.org/wikipedia/commons/thumb/"
OFF = "https://images.openfoodfacts.org/images/products/"


def expand(code):
    if code[0] in "WF" and not code.startswith("http"):
        path = code[1:]
        name = path.rsplit("/", 1)[-1]
        return f"{COMMONS}{path}/500px-{name}"
    if code[0] == "O" and not code.startswith("http"):
        return OFF + code[1:]
    return code


def load(path):
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if "\t" in line:
            sku, code = line.split("\t", 1)
            out[sku] = expand(code)
    return out


def main(argv):
    srcdir, version = argv[1], int(argv[2])
    skus = {p[1] for p in seed_data.PRODUCTS}
    merged, origin = {}, {}
    for name in ("wa", "wb", "wc", "wd", "off"):  # sau ghi đè trước
        for sku, url in load(os.path.join(srcdir, name + ".tsv")).items():
            if sku in skus:
                merged[sku] = url
                origin[sku] = name
            else:
                print("bỏ qua SKU không có:", sku)
    drop = set(open(os.path.join(srcdir, "drop.txt")).read().split()) if os.path.exists(os.path.join(srcdir, "drop.txt")) else set()
    for sku in drop:
        merged.pop(sku, None)
    out = {"version": version, "images": dict(sorted(merged.items()))}
    dest = os.path.join(ROOT, "common", "catalog", "images.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=0, separators=(",", ":"))
        fh.write("\n")
    from collections import Counter
    print(len(merged), "ảnh /", len(skus), "sản phẩm;", dict(Counter(origin[s] for s in merged)))


if __name__ == "__main__":
    main(sys.argv)
