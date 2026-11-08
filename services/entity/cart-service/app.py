"""cart-service: giỏ hàng của khách. Giá & tồn kho luôn lấy mới từ product/inventory-service."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import current_user, internal_only, require_auth  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import ApiError, bad_request, conflict, not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.http_client import ServiceClient  # noqa: E402
from common.utils import get_json, now_str, to_int  # noqa: E402

SERVICE = "cart-service"
MAX_QTY = 99
db = Database(default_sqlite="data/cart.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="entity",
                      description="Giỏ hàng của khách")
products_client = ServiceClient("product", timeout=5)
inventory_client = ServiceClient("inventory", timeout=5)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items(user_id)
"""


def raw_items(user_id):
    return db.query("SELECT product_id, quantity, created_at FROM cart_items WHERE user_id = ? ORDER BY id", (user_id,))


def product_info(product_id):
    items = products_client.post("/internal/products/batch", json={"ids": [product_id]})["items"]
    if not items or not items[0]["is_active"]:
        raise not_found("Sản phẩm không tồn tại hoặc đã ngừng kinh doanh")
    return items[0]


def available_of(product_id):
    stock = inventory_client.post("/internal/inventory/availability", json={"product_ids": [product_id]})["items"]
    return (stock.get(str(product_id)) or {}).get("available", 0)


def build_cart(user_id):
    rows = raw_items(user_id)
    result = {"items": [], "item_count": 0, "subtotal": 0, "has_issues": False, "degraded": False}
    if not rows:
        return result
    ids = [r["product_id"] for r in rows]
    try:
        products = {p["id"]: p for p in products_client.post("/internal/products/batch", json={"ids": ids})["items"]}
    except ApiError:
        products, result["degraded"] = {}, True
    try:
        stock = inventory_client.post("/internal/inventory/availability", json={"product_ids": ids})["items"]
    except ApiError:
        stock, result["degraded"] = None, True
    for r in rows:
        p = products.get(r["product_id"])
        item = {"product_id": r["product_id"], "quantity": r["quantity"], "product": None, "unit_price": 0,
                "line_total": 0, "issue": None}
        if p:
            item["product"] = {k: p.get(k) for k in ("id", "name", "sku", "unit", "price", "sale_price", "final_price",
                                                       "image_url", "category_icon", "category_name", "is_active")}
            item["unit_price"] = p["final_price"]
            item["line_total"] = p["final_price"] * r["quantity"]
            if stock is not None:
                available = (stock.get(str(r["product_id"])) or {}).get("available", 0)
                item["available"] = available
                if available < r["quantity"]:
                    item["issue"] = "Hết hàng" if available == 0 else f"Chỉ còn {available} sản phẩm"
            if not p["is_active"]:
                item["issue"] = "Sản phẩm đã ngừng kinh doanh"
        elif not result["degraded"]:
            item["issue"] = "Sản phẩm không còn tồn tại"
        if item["issue"]:
            result["has_issues"] = True
        else:
            result["subtotal"] += item["line_total"]
        result["item_count"] += r["quantity"]
        result["items"].append(item)
    return result


@app.get("/api/cart")
@require_auth
def get_cart():
    """Xem giỏ hàng với giá và tồn kho mới nhất"""
    return build_cart(current_user()["id"])


@app.get("/api/cart/count")
@require_auth
def cart_count():
    """Tổng số lượng sản phẩm trong giỏ"""
    n = db.scalar("SELECT COALESCE(SUM(quantity), 0) AS n FROM cart_items WHERE user_id = ?", (current_user()["id"],))
    return {"count": n}


@app.post("/api/cart/items")
@require_auth
def add_item():
    """Thêm sản phẩm vào giỏ (kiểm tra tồn kho)"""
    uid = current_user()["id"]
    data = get_json()
    pid = to_int(data.get("product_id"), "product_id", minimum=1, required=True)
    qty = to_int(data.get("quantity"), "quantity", minimum=1, maximum=MAX_QTY, default=1)
    product_info(pid)
    current = db.scalar("SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?", (uid, pid)) or 0
    new_qty = current + qty
    if new_qty > MAX_QTY:
        raise bad_request(f"Mỗi sản phẩm tối đa {MAX_QTY} đơn vị trong giỏ")
    available = available_of(pid)
    if new_qty > available:
        raise conflict(f"Chỉ còn {available} sản phẩm trong kho" if available else "Sản phẩm đã hết hàng",
                       details={"available": available, "in_cart": current})
    ts = now_str()
    db.execute(
        "INSERT INTO cart_items (user_id, product_id, quantity, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id, product_id) DO UPDATE SET quantity = excluded.quantity, updated_at = excluded.updated_at",
        (uid, pid, new_qty, ts, ts))
    return build_cart(uid), 201


@app.put("/api/cart/items/<int:pid>")
@require_auth
def update_item(pid):
    """Đổi số lượng một sản phẩm (0 = xóa)"""
    uid = current_user()["id"]
    qty = to_int(get_json().get("quantity"), "quantity", minimum=0, maximum=MAX_QTY, required=True)
    if not db.query_one("SELECT id FROM cart_items WHERE user_id = ? AND product_id = ?", (uid, pid)):
        raise not_found("Sản phẩm không có trong giỏ")
    if qty == 0:
        db.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (uid, pid))
    else:
        available = available_of(pid)
        if qty > available:
            raise conflict(f"Chỉ còn {available} sản phẩm trong kho" if available else "Sản phẩm đã hết hàng",
                           details={"available": available})
        db.execute("UPDATE cart_items SET quantity = ?, updated_at = ? WHERE user_id = ? AND product_id = ?",
                   (qty, now_str(), uid, pid))
    return build_cart(uid)


@app.delete("/api/cart/items/<int:pid>")
@require_auth
def remove_item(pid):
    """Bỏ một sản phẩm khỏi giỏ"""
    uid = current_user()["id"]
    db.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (uid, pid))
    return build_cart(uid)


@app.delete("/api/cart")
@require_auth
def clear_cart():
    """Xóa toàn bộ giỏ hàng"""
    db.execute("DELETE FROM cart_items WHERE user_id = ?", (current_user()["id"],))
    return {"items": [], "item_count": 0, "subtotal": 0, "has_issues": False, "degraded": False}


# =================================================================== NỘI BỘ
@app.get("/internal/carts/<int:user_id>")
@internal_only
def internal_get(user_id):
    """Lấy giỏ hàng thô của một khách"""
    return {"user_id": user_id, "items": raw_items(user_id)}


@app.delete("/internal/carts/<int:user_id>")
@internal_only
def internal_clear(user_id):
    """Xóa các sản phẩm đã đặt khỏi giỏ (nếu truyền product_ids) hoặc xóa toàn bộ."""
    from flask import request

    ids = [int(x) for x in (request.args.get("product_ids") or "").split(",") if x.strip().isdigit()]
    if ids:
        db.execute(f"DELETE FROM cart_items WHERE user_id = ? AND product_id IN ({','.join('?' * len(ids))})",
                   [user_id] + ids)
    else:
        db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    return {"message": "Đã xóa giỏ hàng"}


def create_app():
    db.init_schema(SCHEMA)
    bus.init_app(app)
    register_service(app, "cart", 8004)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8004)
