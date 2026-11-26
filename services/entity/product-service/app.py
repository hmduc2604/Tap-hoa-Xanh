"""product-service: danh mục, sản phẩm (tìm kiếm không dấu, lọc, sắp xếp), đánh giá sản phẩm."""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import request  # noqa: E402

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import current_user, internal_only, is_staff, require_auth, require_staff  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import ApiError, bad_request, conflict, not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.http_client import ServiceClient  # noqa: E402
from common.seed_data import CATEGORIES, PRODUCTS  # noqa: E402
from common.utils import (clean_str, get_json, id_list, now_str, paged, pagination, parse_bool,  # noqa: E402
                          require_fields, slugify, strip_accents, to_int)

SERVICE = "product-service"
db = Database(default_sqlite="data/product.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="entity",
                      description="Danh mục, sản phẩm, giá, tìm kiếm không dấu và đánh giá")
inventory = ServiceClient("inventory", timeout=4)
orders = ServiceClient("order", timeout=5)

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    icon TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    barcode TEXT UNIQUE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    brand TEXT,
    unit TEXT NOT NULL,
    price BIGINT NOT NULL,
    sale_price BIGINT,
    image_url TEXT,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    search_text TEXT NOT NULL DEFAULT '',
    sold_count INTEGER NOT NULL DEFAULT 0,
    rating_avg REAL NOT NULL DEFAULT 0,
    rating_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE TABLE IF NOT EXISTS catalog_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    user_name TEXT,
    rating INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (product_id, user_id)
)
"""

PRODUCT_SELECT = """
SELECT p.*, c.name AS category_name, c.icon AS category_icon, c.slug AS category_slug
FROM products p JOIN categories c ON c.id = p.category_id
"""
FINAL_PRICE = "COALESCE(p.sale_price, p.price)"
SORTS = {
    "newest": "p.id DESC",
    "price_asc": f"{FINAL_PRICE} ASC, p.id",
    "price_desc": f"{FINAL_PRICE} DESC, p.id",
    "name": "p.name ASC",
    "popular": "p.sold_count DESC, p.rating_count DESC, p.id",
    "rating": "p.rating_avg DESC, p.rating_count DESC, p.id",
    "discount": f"(p.price - {FINAL_PRICE}) DESC, p.id",
}


def search_text(name, brand=None, sku=None, barcode=None):
    return " ".join(strip_accents(x) for x in (name, brand, sku, barcode) if x)


def serialize(row, stock=None):
    p = dict(row)
    p.pop("search_text", None)
    p["is_active"] = bool(p["is_active"])
    p["final_price"] = p["sale_price"] if p.get("sale_price") else p["price"]
    p["discount_percent"] = round(100 - p["final_price"] * 100 / p["price"]) if p["price"] and p.get("sale_price") else 0
    p["rating_avg"] = round(float(p.get("rating_avg") or 0), 1)
    if stock is not None:
        info = stock.get(str(p["id"]))
        p["available"] = info["available"] if info else 0
        p["in_stock"] = p["available"] > 0
    return p


def fetch_stock(product_ids):
    """Lấy tồn kho từ inventory-service. Nếu kho lỗi -> trả None (degrade gracefully)."""
    if not product_ids:
        return {}
    try:
        return inventory.post("/internal/inventory/availability", json={"product_ids": product_ids})["items"]
    except ApiError as exc:
        app.logger.warning("Không lấy được tồn kho: %s", exc.message)
        return None


def get_product_row(product_id):
    return db.query_one(PRODUCT_SELECT + " WHERE p.id = ?", (product_id,))


def product_event_payload(row, **extra):
    data = {
        "product_id": row["id"], "sku": row["sku"], "barcode": row.get("barcode"), "name": row["name"],
        "unit": row["unit"], "price": row["price"], "sale_price": row.get("sale_price"),
        "category_id": row["category_id"], "is_active": bool(row["is_active"]),
    }
    data.update(extra)
    return data


# =================================================================== DANH MỤC
@app.get("/api/categories")
def list_categories():
    """Danh sách danh mục và số sản phẩm"""
    include_inactive = parse_bool(request.args.get("all")) and is_staff()
    where = "" if include_inactive else "WHERE c.is_active = 1"
    rows = db.query(
        f"""SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id AND p.is_active = 1) AS product_count
            FROM categories c {where} ORDER BY c.sort_order, c.id"""
    )
    for r in rows:
        r["is_active"] = bool(r["is_active"])
    return {"items": rows}


def _category_payload(data, partial=False):
    if not partial:
        require_fields(data, ["name"])
    payload = {}
    if "name" in data:
        payload["name"] = clean_str(data["name"], 100)
        if not payload["name"]:
            raise bad_request("Tên danh mục không được để trống")
    for key in ("description", "icon"):
        if key in data:
            payload[key] = clean_str(data[key], 255)
    if "sort_order" in data:
        payload["sort_order"] = to_int(data["sort_order"], "sort_order", default=0)
    if "is_active" in data:
        payload["is_active"] = 1 if parse_bool(data["is_active"]) else 0
    return payload


@app.post("/api/categories")
@require_staff
def create_category():
    """Tạo danh mục"""
    p = _category_payload(get_json())
    slug = slugify(p["name"])
    if db.query_one("SELECT id FROM categories WHERE slug = ?", (slug,)):
        raise conflict("Danh mục đã tồn tại")
    with db.tx() as cur:
        cid = cur.insert(
            "INSERT INTO categories (name, slug, description, icon, sort_order, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["name"], slug, p.get("description"), p.get("icon") or "🛒", p.get("sort_order", 0),
             p.get("is_active", 1), now_str()),
        )
    return db.query_one("SELECT * FROM categories WHERE id = ?", (cid,)), 201


@app.put("/api/categories/<int:cid>")
@require_staff
def update_category(cid):
    """Sửa danh mục"""
    p = _category_payload(get_json(), partial=True)
    if not db.query_one("SELECT id FROM categories WHERE id = ?", (cid,)):
        raise not_found("Không tìm thấy danh mục")
    if "name" in p:
        p["slug"] = slugify(p["name"])
        if db.query_one("SELECT id FROM categories WHERE slug = ? AND id <> ?", (p["slug"], cid)):
            raise conflict("Tên danh mục bị trùng")
    if p:
        db.execute(f"UPDATE categories SET {', '.join(k + ' = ?' for k in p)} WHERE id = ?", list(p.values()) + [cid])
    return db.query_one("SELECT * FROM categories WHERE id = ?", (cid,))


@app.delete("/api/categories/<int:cid>")
@require_staff
def delete_category(cid):
    """Xóa danh mục (khi không còn sản phẩm)"""
    if not db.query_one("SELECT id FROM categories WHERE id = ?", (cid,)):
        raise not_found("Không tìm thấy danh mục")
    if db.scalar("SELECT COUNT(*) AS n FROM products WHERE category_id = ?", (cid,)):
        raise conflict("Danh mục đang có sản phẩm, hãy chuyển sản phẩm sang danh mục khác trước")
    db.execute("DELETE FROM categories WHERE id = ?", (cid,))
    return {"message": "Đã xóa danh mục"}


# =================================================================== SẢN PHẨM
@app.get("/api/products")
def list_products():
    """Tìm kiếm, lọc, sắp xếp, phân trang sản phẩm

Tham số: q, category_id, min_price, max_price, on_sale, sort, ids, page, page_size"""
    page, size, offset = pagination(default_size=12)
    where, params = [], []
    if not (parse_bool(request.args.get("include_inactive")) and is_staff()):
        where.append("p.is_active = 1")
    q = strip_accents(request.args.get("q"))
    if q:
        for word in q.split()[:5]:
            where.append("p.search_text LIKE ?")
            params.append(f"%{word}%")
    category_id = to_int(request.args.get("category_id"), "category_id")
    if category_id:
        where.append("p.category_id = ?")
        params.append(category_id)
    min_price = to_int(request.args.get("min_price"), "min_price", minimum=0)
    if min_price is not None:
        where.append(f"{FINAL_PRICE} >= ?")
        params.append(min_price)
    max_price = to_int(request.args.get("max_price"), "max_price", minimum=0)
    if max_price is not None:
        where.append(f"{FINAL_PRICE} <= ?")
        params.append(max_price)
    if parse_bool(request.args.get("on_sale")):
        where.append("p.sale_price IS NOT NULL")
    ids = id_list(request.args.get("ids"))
    if ids:
        where.append(f"p.id IN ({','.join('?' * len(ids))})")
        params += ids
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    order = SORTS.get(request.args.get("sort") or "newest", SORTS["newest"])
    total = db.scalar(f"SELECT COUNT(*) AS n FROM products p {cond}", params)
    rows = db.query(f"{PRODUCT_SELECT} {cond} ORDER BY {order} LIMIT ? OFFSET ?", params + [size, offset])
    stock = fetch_stock([r["id"] for r in rows])
    result = paged([serialize(r, stock if stock is not None else None) for r in rows], total, page, size)
    result["stock_available"] = stock is not None
    return result


@app.get("/api/products/<int:pid>")
def get_product(pid):
    """Chi tiết sản phẩm, tồn kho và sản phẩm cùng danh mục"""
    row = get_product_row(pid)
    if not row or (not row["is_active"] and not is_staff()):
        raise not_found("Không tìm thấy sản phẩm")
    related_rows = db.query(
        PRODUCT_SELECT + " WHERE p.category_id = ? AND p.id <> ? AND p.is_active = 1 ORDER BY p.sold_count DESC, p.id LIMIT 4",
        (row["category_id"], pid),
    )
    stock = fetch_stock([pid] + [r["id"] for r in related_rows])
    product = serialize(row, stock)
    product["related"] = [serialize(r, stock) for r in related_rows]
    product["stock_available"] = stock is not None
    return product


@app.get("/api/products/barcode/<code>")
@require_staff
def get_by_barcode(code):
    """Tra cứu theo mã vạch hoặc SKU (dùng cho máy POS quét mã)."""
    code = code.strip()
    row = db.query_one(PRODUCT_SELECT + " WHERE (p.barcode = ? OR UPPER(p.sku) = ?) AND p.is_active = 1",
                       (code, code.upper()))
    if not row:
        raise not_found(f"Không tìm thấy sản phẩm có mã {code}")
    return serialize(row, fetch_stock([row["id"]]))


def _product_payload(data, partial=False):
    if not partial:
        require_fields(data, ["name", "sku", "category_id", "price", "unit"])
    p = {}
    for key, size in (("name", 200), ("sku", 50), ("brand", 100), ("unit", 50), ("image_url", 500), ("description", 2000)):
        if key in data:
            p[key] = clean_str(data[key], size)
    if "sku" in p:
        if not p["sku"]:
            raise bad_request("SKU không được để trống")
        p["sku"] = p["sku"].upper()
    if "name" in p and not p["name"]:
        raise bad_request("Tên sản phẩm không được để trống")
    if "barcode" in data:
        p["barcode"] = clean_str(data["barcode"], 50)
    if "category_id" in data:
        p["category_id"] = to_int(data["category_id"], "category_id", minimum=1, required=True)
        if not db.query_one("SELECT id FROM categories WHERE id = ?", (p["category_id"],)):
            raise bad_request("Danh mục không tồn tại")
    if "price" in data:
        p["price"] = to_int(data["price"], "price", minimum=0, required=True)
    if "sale_price" in data:
        p["sale_price"] = to_int(data["sale_price"], "sale_price", minimum=0) or None
    if "is_active" in data:
        p["is_active"] = 1 if parse_bool(data["is_active"]) else 0
    return p


def _check_unique(p, exclude_id=0):
    if p.get("sku") and db.query_one("SELECT id FROM products WHERE sku = ? AND id <> ?", (p["sku"], exclude_id)):
        raise conflict(f"SKU {p['sku']} đã tồn tại")
    if p.get("barcode") and db.query_one("SELECT id FROM products WHERE barcode = ? AND id <> ?", (p["barcode"], exclude_id)):
        raise conflict(f"Mã vạch {p['barcode']} đã tồn tại")


@app.post("/api/products")
@require_staff
def create_product():
    """Tạo sản phẩm (phát sự kiện product.created)"""
    data = get_json()
    p = _product_payload(data)
    if p.get("sale_price") and p["sale_price"] >= p["price"]:
        raise bad_request("Giá khuyến mãi phải nhỏ hơn giá gốc")
    initial_stock = to_int(data.get("initial_stock"), "initial_stock", minimum=0, default=0)
    min_quantity = to_int(data.get("min_quantity"), "min_quantity", minimum=0, default=10)
    _check_unique(p)
    ts = now_str()
    with db.tx() as cur:
        pid = cur.insert(
            """INSERT INTO products (sku, barcode, name, slug, category_id, brand, unit, price, sale_price, image_url,
               description, is_active, search_text, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["sku"], p.get("barcode"), p["name"], slugify(p["name"]), p["category_id"], p.get("brand"), p["unit"],
             p["price"], p.get("sale_price"), p.get("image_url"), p.get("description"), p.get("is_active", 1),
             search_text(p["name"], p.get("brand"), p["sku"], p.get("barcode")), ts, ts),
        )
    row = get_product_row(pid)
    # Sự kiện -> inventory-service tạo bản ghi tồn kho (kèm tồn đầu kỳ nếu có)
    bus.publish("product.created", product_event_payload(row, initial_stock=initial_stock, min_quantity=min_quantity,
                                                         created_by=current_user()["name"]))
    return serialize(row), 201


@app.put("/api/products/<int:pid>")
@require_staff
def update_product(pid):
    """Cập nhật sản phẩm (phát sự kiện product.updated)"""
    row = get_product_row(pid)
    if not row:
        raise not_found("Không tìm thấy sản phẩm")
    p = _product_payload(get_json(), partial=True)
    _check_unique(p, pid)
    merged = {**row, **p}
    if merged.get("sale_price") and merged["sale_price"] >= merged["price"]:
        raise bad_request("Giá khuyến mãi phải nhỏ hơn giá gốc")
    if p:
        if "name" in p:
            p["slug"] = slugify(p["name"])
        p["search_text"] = search_text(merged["name"], merged.get("brand"), merged["sku"], merged.get("barcode"))
        p["updated_at"] = now_str()
        db.execute(f"UPDATE products SET {', '.join(k + ' = ?' for k in p)} WHERE id = ?", list(p.values()) + [pid])
        row = get_product_row(pid)
        bus.publish("product.updated", product_event_payload(row))
    return serialize(row)


@app.delete("/api/products/<int:pid>")
@require_staff
def delete_product(pid):
    """Xóa mềm: ngừng kinh doanh (đơn hàng cũ vẫn giữ thông tin sản phẩm)."""
    row = get_product_row(pid)
    if not row:
        raise not_found("Không tìm thấy sản phẩm")
    db.execute("UPDATE products SET is_active = 0, updated_at = ? WHERE id = ?", (now_str(), pid))
    bus.publish("product.updated", product_event_payload(get_product_row(pid)))
    return {"message": "Đã ngừng kinh doanh sản phẩm"}


# =================================================================== ĐÁNH GIÁ
@app.get("/api/products/<int:pid>/reviews")
def list_reviews(pid):
    """Đánh giá của một sản phẩm"""
    page, size, offset = pagination(default_size=10)
    total = db.scalar("SELECT COUNT(*) AS n FROM reviews WHERE product_id = ?", (pid,))
    rows = db.query("SELECT * FROM reviews WHERE product_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (pid, size, offset))
    dist = {str(i): 0 for i in range(1, 6)}
    for r in db.query("SELECT rating, COUNT(*) AS n FROM reviews WHERE product_id = ? GROUP BY rating", (pid,)):
        dist[str(r["rating"])] = r["n"]
    result = paged(rows, total, page, size)
    result["distribution"] = dist
    return result


@app.post("/api/products/<int:pid>/reviews")
@require_auth
def add_review(pid):
    """Đánh giá sản phẩm đã mua và nhận hàng"""
    user = current_user()
    data = get_json()
    rating = to_int(data.get("rating"), "rating", minimum=1, maximum=5, required=True)
    comment = clean_str(data.get("comment"), 1000)
    if not get_product_row(pid):
        raise not_found("Không tìm thấy sản phẩm")
    # Gọi đồng bộ sang order-service: chỉ khách đã mua & nhận hàng mới được đánh giá
    bought = orders.get("/internal/orders/purchased", params={"user_id": user["id"], "product_id": pid})
    if not bought.get("purchased"):
        raise ApiError(403, "Bạn chỉ có thể đánh giá sản phẩm đã mua và nhận hàng", code="NOT_PURCHASED")
    ts = now_str()
    with db.tx() as cur:
        existing = cur.one("SELECT id FROM reviews WHERE product_id = ? AND user_id = ?", (pid, user["id"]))
        if existing:
            cur.execute("UPDATE reviews SET rating = ?, comment = ?, user_name = ?, updated_at = ? WHERE id = ?",
                        (rating, comment, user["name"], ts, existing["id"]))
        else:
            cur.insert("INSERT INTO reviews (product_id, user_id, user_name, rating, comment, created_at, updated_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)", (pid, user["id"], user["name"], rating, comment, ts, ts))
        stats = cur.one("SELECT AVG(rating) AS avg_rating, COUNT(*) AS n FROM reviews WHERE product_id = ?", (pid,))
        cur.execute("UPDATE products SET rating_avg = ?, rating_count = ? WHERE id = ?",
                    (round(float(stats["avg_rating"] or 0), 2), stats["n"], pid))
    return db.query_one("SELECT * FROM reviews WHERE product_id = ? AND user_id = ?", (pid, user["id"])), 201


# =================================================================== NỘI BỘ
@app.post("/internal/products/batch")
@internal_only
def internal_batch():
    """Lấy nhiều sản phẩm theo danh sách id"""
    ids = id_list((get_json().get("ids")) or [])
    if not ids:
        return {"items": []}
    rows = db.query(PRODUCT_SELECT + f" WHERE p.id IN ({','.join('?' * len(ids))})", ids)
    return {"items": [serialize(r) for r in rows]}


@app.get("/internal/products/stats")
@internal_only
def internal_stats():
    """Thống kê số sản phẩm"""
    return {
        "total": db.scalar("SELECT COUNT(*) AS n FROM products"),
        "active": db.scalar("SELECT COUNT(*) AS n FROM products WHERE is_active = 1"),
        "on_sale": db.scalar("SELECT COUNT(*) AS n FROM products WHERE is_active = 1 AND sale_price IS NOT NULL"),
        "categories": db.scalar("SELECT COUNT(*) AS n FROM categories"),
    }


# =================================================================== SỰ KIỆN
@bus.on("order.completed")
def on_order_completed(data, event):
    """Cập nhật số lượng đã bán (phục vụ sắp xếp 'bán chạy')."""
    with db.tx() as cur:
        for item in data.get("items", []):
            cur.execute("UPDATE products SET sold_count = sold_count + ? WHERE id = ?",
                        (int(item["quantity"]), int(item["product_id"])))


# =================================================================== KHỞI TẠO
def seed():
    """Nạp dữ liệu mẫu từ common/seed_data.py.

    - Cơ sở dữ liệu trống: tạo toàn bộ danh mục và sản phẩm (id 1..N đúng thứ tự trong seed_data).
    - Đã có dữ liệu từ phiên bản trước: chỉ BỔ SUNG sản phẩm (và danh mục) mới theo SKU, không sửa hay xóa gì đang có.
      Sản phẩm bị xóa trong trang quản trị chỉ bị ẩn (is_active = 0) nên SKU vẫn còn và không bị tạo lại.
      Tồn kho của sản phẩm mới do inventory-service tự đồng bộ (reconcile_catalog).
    """
    ts = now_str()
    with db.tx() as cur:
        cur.lock("seed")
        cat_ids = {r["slug"]: r["id"] for r in cur.all("SELECT id, slug FROM categories")}
        fresh = not cat_ids
        have_sku = {r["sku"] for r in cur.all("SELECT sku FROM products")}
        have_barcode = {r["barcode"] for r in cur.all("SELECT barcode FROM products WHERE barcode IS NOT NULL")}
        todo = [p for p in PRODUCTS if p[1] not in have_sku]
        if not todo and not fresh:
            return
        needed = {p[0] for p in todo}
        for i, (name, icon, desc) in enumerate(CATEGORIES):
            slug = slugify(name)
            if slug not in cat_ids and (fresh or i in needed):
                cat_ids[slug] = cur.insert(
                    "INSERT INTO categories (name, slug, description, icon, sort_order, is_active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                    (name, slug, desc, icon, i + 1, ts))
        for (ci, sku, barcode, name, brand, unit, price, sale, _stock, _min, desc) in todo:
            cur.insert(
                """INSERT INTO products (sku, barcode, name, slug, category_id, brand, unit, price, sale_price, image_url,
                   description, is_active, search_text, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?, ?)""",
                (sku, None if barcode in have_barcode else barcode, name, slugify(name),
                 cat_ids[slugify(CATEGORIES[ci][0])], brand, unit, price, sale, desc,
                 search_text(name, brand, sku, barcode), ts, ts))
    if fresh:
        app.logger.info("Đã tạo %s danh mục, %s sản phẩm mẫu", len(CATEGORIES), len(PRODUCTS))
    else:
        app.logger.info("Đã bổ sung %s sản phẩm mới vào cơ sở dữ liệu hiện có", len(todo))


def apply_images():
    """Gắn ảnh sản phẩm từ common/catalog/images.json (nguồn: Open Food Facts, Wikimedia Commons; xem README).

    Chỉ điền sản phẩm CHƯA có ảnh nên không ghi đè ảnh quản trị viên đã đặt, và chỉ chạy một lần cho mỗi phiên bản tệp ảnh
    (dấu vết lưu trong bảng catalog_meta), nhờ vậy quản trị viên xóa ảnh một sản phẩm thì ảnh không tự quay lại.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(sys.modules["common.seed_data"].__file__)), "catalog", "images.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    images, version = data.get("images") or {}, str(data.get("version", ""))
    if not images:
        return
    ts = now_str()
    with db.tx() as cur:
        cur.lock("seed_images")
        row = cur.one("SELECT value FROM catalog_meta WHERE key = ?", ("images_version",))
        if row and row["value"] == version:
            return
        for sku, url in images.items():
            cur.execute("UPDATE products SET image_url = ?, updated_at = ? WHERE sku = ? AND (image_url IS NULL OR image_url = '')",
                        (url, ts, sku))
        cur.execute("DELETE FROM catalog_meta WHERE key = ?", ("images_version",))
        cur.execute("INSERT INTO catalog_meta (key, value) VALUES (?, ?)", ("images_version", version))
    app.logger.info("Đã gắn ảnh cho sản phẩm chưa có ảnh (%s ảnh trong tệp, phiên bản %s)", len(images), version)


def create_app():
    db.init_schema(SCHEMA)
    seed()
    apply_images()
    bus.init_app(app)
    register_service(app, "product", 8002)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8002)
