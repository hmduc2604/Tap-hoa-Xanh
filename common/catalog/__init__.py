"""Danh mục mở rộng của Tạp Hóa Xanh: ~500 sản phẩm thật-giống-thật bổ sung cho 55 sản phẩm gốc trong seed_data.py.

Dữ liệu viết theo "nhóm hàng" (kind): mỗi nhóm có tên gọi, cách khách gọi, danh mục và danh sách sản phẩm. Từ đó sinh ra
  * EXTRA_PRODUCTS  - tuple cùng dạng với seed_data.PRODUCTS (mã vạch EAN-13 hợp lệ, SKU duy nhất, tồn kho xác định);
  * KIND_OF          - sku -> nhóm hàng (cả 55 sản phẩm gốc), dùng để sinh dữ liệu huấn luyện AI;
  * KINDS            - nhóm hàng -> {label, aliases}.
Nhóm hàng chỉ nằm ở phía huấn luyện/AI; cơ sở dữ liệu cửa hàng không có cột này.
"""
import re

from common.utils import strip_accents

EXTRA_CATEGORIES = [
    ("Đông lạnh & Ăn liền", "🧊", "Cá viên, xúc xích, chả giò, há cảo, kem và đồ ăn nhanh"),
    ("Mẹ & Bé", "👶", "Sữa bột, tã bỉm, bột ăn dặm và đồ dùng cho bé"),
    ("Gia dụng & Nhà bếp", "🍳", "Túi rác, màng bọc, pin, đồ dùng tiện ích trong nhà"),
]

# ---------------------------------------------------------------- tồn kho theo nhóm: (tối thiểu, tối đa, tồn tối thiểu cảnh báo)
TIERS = {"fast": (80, 260, 40), "mid": (25, 90, 10), "slow": (10, 40, 5), "fresh": (12, 45, 6)}

_STOP = {"va", "de", "cua", "co", "khong", "cho", "tui", "hop", "chai", "goi", "lon", "thung", "loc", "khay", "bo", "kg", "g", "ml"}


def _ean13(body12):
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body12))
    return body12 + str((10 - s % 10) % 10)


_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|m|w)\b")
_COUNT = re.compile(r"(?:loc|thung|hop|vi|bich|goi|bo|khay)\s+(\d+)")


def _size_code(unit, name):
    """'túi 10kg' -> '10KG'; 'lốc 4 hộp' -> 'L4'. Giúp SKU dễ đọc và không trùng giữa các quy cách."""
    for text in (unit, name):
        t = strip_accents(text).lower()
        m = _SIZE.search(t)
        if m:
            return m.group(1).replace(".", "").replace(",", "") + m.group(2).upper()
    m = _COUNT.search(strip_accents(unit).lower())
    return "X" + m.group(1) if m else ""


def _pseudo(sku, lo, hi):
    """Số 'ngẫu nhiên' nhưng xác định theo SKU (cùng SKU luôn cho cùng tồn kho, mọi máy đều như nhau)."""
    h = 0
    for ch in sku:
        h = (h * 131 + ord(ch)) % 1000003
    return lo + h % (hi - lo + 1)


def build(blocks, first_category_index, start_seq):
    """blocks: list dict {kind, cat, label, aliases, desc, tier, prefix, rows:[(tên, thương hiệu, đơn vị, giá[, giá KM[, mô tả]])]}"""
    products, kind_of, kinds, used = [], {}, {}, set()
    seq = start_seq
    for b in blocks:
        kinds[b["kind"]] = {"label": b["label"], "aliases": list(b.get("aliases", []))}
        lo, hi, minq = TIERS[b.get("tier", "mid")]
        for row in b["rows"]:
            name, brand, unit, price = row[:4]
            sale = row[4] if len(row) > 4 else None
            desc = row[5] if len(row) > 5 else b["desc"].format(name=name, brand=brand, unit=unit)
            words = [w for w in strip_accents(name).upper().replace("/", " ").replace("'", "").replace("-", " ").replace("&", " ").split()
                     if w.lower() not in _STOP and not w.isdigit() and not _SIZE.fullmatch(w.lower())]
            if words and words[0] == b["prefix"]:
                words = words[1:]
            sku = "-".join([b["prefix"]] + words[:3] + [c for c in (_size_code(unit, name),) if c])[:44]
            base, n = sku, 2
            while sku in used:
                sku = f"{base}-{n}"
                n += 1
            used.add(sku)
            seq += 1
            barcode = _ean13("8931" + f"{seq:08d}")
            stock = _pseudo(sku, lo, hi)
            if _pseudo(sku + "!", 0, 99) < 4:  # vài mặt hàng sắp hết để màn hình tồn kho thấp có dữ liệu thật
                stock = _pseudo(sku + "?", 0, minq - 1)
            products.append((b["cat"], sku, barcode, name, brand, unit, price, sale, stock, minq, desc))
            kind_of[sku] = b["kind"]
    return products, kind_of, kinds


def all_blocks():
    from . import dry, drinks_snacks, fresh, home
    return dry.BLOCKS + drinks_snacks.BLOCKS + fresh.BLOCKS + home.BLOCKS
