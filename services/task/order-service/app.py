"""order-service: đặt hàng online (Saga điều phối), bán tại quầy (POS), quản lý trạng thái đơn, báo cáo doanh thu.

Saga đặt hàng (orchestration):
  1. Tạo đơn PENDING
  2. inventory-service  : giữ hàng (reserve)        <- bù trừ: release
  3. promotion-service  : ghi nhận mã giảm giá       <- bù trừ: release
  4. payment-service    : tạo giao dịch thanh toán   <- bù trừ: cancel / refund
  5. cart-service       : xóa giỏ hàng (best-effort)
  6. Phát sự kiện order.created (notification-service, ...)
Nếu một bước lỗi, các bước trước được bù trừ theo thứ tự ngược lại.
"""
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import request  # noqa: E402

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import current_user, internal_only, is_staff, require_auth, require_staff  # noqa: E402
from common.config import env_int  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import ApiError, bad_request, forbidden, not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.http_client import ServiceClient  # noqa: E402
from common.utils import (clean_str, get_json, now_str, paged, pagination, random_code, to_int,  # noqa: E402
                          today_str)

SERVICE = "order-service"
db = Database(default_sqlite="data/order.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="task",
                      description="Điều phối quy trình đặt hàng (Saga), bán tại quầy và báo cáo doanh thu")
auth_client = ServiceClient("auth", timeout=5)
product_client = ServiceClient("product", timeout=5)
inventory_client = ServiceClient("inventory", timeout=8)
promotion_client = ServiceClient("promotion", timeout=5)
payment_client = ServiceClient("payment", timeout=8)
cart_client = ServiceClient("cart", timeout=5)

SHIPPING_FEE = env_int("SHIPPING_FEE", 25000)
FREE_SHIP_THRESHOLD = env_int("FREE_SHIP_THRESHOLD", 300000)

STATUS_LABELS = {
    "PENDING": "Chờ xác nhận", "CONFIRMED": "Đã xác nhận", "SHIPPING": "Đang giao", "DELIVERED": "Đã giao",
    "COMPLETED": "Hoàn tất (tại quầy)", "CANCELLED": "Đã hủy",
}
PAYMENT_STATUS_LABELS = {"UNPAID": "Chưa thanh toán", "PAID": "Đã thanh toán", "REFUNDED": "Đã hoàn tiền"}
TRANSITIONS = {"PENDING": ("CONFIRMED", "CANCELLED"), "CONFIRMED": ("SHIPPING", "CANCELLED"), "SHIPPING": ("DELIVERED",)}
REVENUE_STATUSES = ("DELIVERED", "COMPLETED")
ONLINE_METHODS = ("COD", "BANK_TRANSFER", "EWALLET")
POS_METHODS = ("CASH", "CARD", "BANK_TRANSFER")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    user_id INTEGER,
    customer_name TEXT,
    customer_email TEXT,
    customer_phone TEXT,
    shipping_address TEXT,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    payment_status TEXT NOT NULL,
    subtotal BIGINT NOT NULL,
    discount BIGINT NOT NULL DEFAULT 0,
    shipping_fee BIGINT NOT NULL DEFAULT 0,
    total BIGINT NOT NULL,
    coupon_code TEXT,
    note TEXT,
    cash_received BIGINT,
    change_amount BIGINT,
    created_by TEXT,
    cancel_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL,
    sku TEXT,
    product_name TEXT NOT NULL,
    unit TEXT,
    category_icon TEXT,
    unit_price BIGINT NOT NULL,
    quantity INTEGER NOT NULL,
    line_total BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE TABLE IF NOT EXISTS order_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    note TEXT,
    changed_by TEXT,
    created_at TEXT NOT NULL
)
"""


# =================================================================== tiện ích
def order_view(row, full=False):
    o = dict(row)
    o["status_label"] = STATUS_LABELS.get(o["status"], o["status"])
    o["payment_status_label"] = PAYMENT_STATUS_LABELS.get(o["payment_status"], o["payment_status"])
    o["can_cancel"] = o["status"] == "PENDING"
    o["next_statuses"] = list(TRANSITIONS.get(o["status"], ()))
    if full:
        o["items"] = db.query("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (o["id"],))
        o["history"] = db.query("SELECT * FROM order_status_history WHERE order_id = ? ORDER BY id", (o["id"],))
        for h in o["history"]:
            h["status_label"] = STATUS_LABELS.get(h["status"], h["status"])
    else:
        o["item_count"] = db.scalar("SELECT COALESCE(SUM(quantity), 0) AS n FROM order_items WHERE order_id = ?", (o["id"],))
        o["preview_items"] = db.query(
            "SELECT product_name, quantity, category_icon FROM order_items WHERE order_id = ? ORDER BY id LIMIT 3", (o["id"],))
    return o


def get_order_row(order_id):
    row = db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not row:
        raise not_found("Không tìm thấy đơn hàng")
    return row


def items_payload(order_id):
    return [{"product_id": i["product_id"], "quantity": i["quantity"], "product_name": i["product_name"],
             "unit_price": i["unit_price"]}
            for i in db.query("SELECT * FROM order_items WHERE order_id = ?", (order_id,))]


def event_payload(row, **extra):
    data = {"order_id": row["id"], "code": row["code"], "user_id": row["user_id"], "channel": row["channel"],
            "status": row["status"], "total": row["total"], "payment_method": row["payment_method"],
            "customer_name": row["customer_name"], "customer_email": row["customer_email"]}
    data.update(extra)
    return data


def normalize_items(raw):
    if not isinstance(raw, list) or not raw:
        raise bad_request("Đơn hàng phải có ít nhất một sản phẩm")
    merged = {}
    for it in raw:
        if not isinstance(it, dict):
            raise bad_request("Danh sách sản phẩm không hợp lệ")
        pid = to_int(it.get("product_id"), "product_id", minimum=1, required=True)
        qty = to_int(it.get("quantity"), "quantity", minimum=1, maximum=999, required=True)
        merged[pid] = merged.get(pid, 0) + qty
    return merged


def price_lines(merged):
    """Lấy giá hiện hành từ product-service (không tin giá client gửi lên)."""
    products = {p["id"]: p for p in product_client.post("/internal/products/batch", json={"ids": list(merged)})["items"]}
    invalid = [pid for pid in merged if pid not in products or not products[pid]["is_active"]]
    if invalid:
        names = [products[p]["name"] if p in products else f"#{p}" for p in invalid]
        raise bad_request("Sản phẩm không tồn tại hoặc đã ngừng kinh doanh: " + ", ".join(names),
                          details={"product_ids": invalid})
    lines = []
    for pid, qty in merged.items():
        p = products[pid]
        lines.append({"product_id": pid, "sku": p["sku"], "product_name": p["name"], "unit": p["unit"],
                      "category_icon": p.get("category_icon"), "unit_price": p["final_price"], "quantity": qty,
                      "line_total": p["final_price"] * qty})
    return lines


def insert_order(order, lines, actor):
    ts = now_str()
    with db.tx() as cur:
        code = random_code("DH")
        while cur.one("SELECT id FROM orders WHERE code = ?", (code,)):
            code = random_code("DH")
        cols = ["code", "user_id", "customer_name", "customer_email", "customer_phone", "shipping_address", "channel",
                "status", "payment_method", "payment_status", "subtotal", "discount", "shipping_fee", "total",
                "coupon_code", "note", "cash_received", "change_amount", "created_by", "created_at", "updated_at"]
        order = {**order, "code": code, "status": "PENDING", "payment_status": "UNPAID", "created_at": ts, "updated_at": ts}
        oid = cur.insert(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                         [order.get(c) for c in cols])
        for ln in lines:
            cur.insert("INSERT INTO order_items (order_id, product_id, sku, product_name, unit, category_icon, unit_price, "
                       "quantity, line_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (oid, ln["product_id"], ln["sku"], ln["product_name"], ln["unit"], ln["category_icon"],
                        ln["unit_price"], ln["quantity"], ln["line_total"]))
        cur.insert("INSERT INTO order_status_history (order_id, status, note, changed_by, created_at) VALUES (?, ?, ?, ?, ?)",
                   (oid, "PENDING", "Tạo đơn hàng", actor, ts))
    return get_order_row(oid)


def discard_order(order_id):
    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))


def compensate(steps, order):
    """Chạy các bước bù trừ theo thứ tự ngược. Lỗi bù trừ chỉ ghi log (cần đối soát thủ công)."""
    for name in reversed(steps):
        try:
            if name == "inventory":
                inventory_client.post("/internal/inventory/release", json={"order_id": order["id"], "order_code": order["code"]})
            elif name == "coupon":
                promotion_client.post("/internal/coupons/release", json={"order_id": order["id"]})
            elif name == "payment":
                payment_client.post(f"/internal/payments/order/{order['id']}/cancel", json={"reason": "Saga rollback"})
        except ApiError as exc:
            app.logger.error("Bù trừ bước %s cho đơn %s thất bại: %s", name, order["code"], exc.message)


def run_saga(order, lines, coupon_code, method, payment_extra=None):
    """Thực thi saga; trả về thông tin thanh toán. Nếu lỗi: bù trừ + xóa đơn, rồi ném lại lỗi."""
    done = []
    try:
        inventory_client.post("/internal/inventory/reserve", json={
            "order_id": order["id"], "items": [{"product_id": ln["product_id"], "quantity": ln["quantity"]} for ln in lines]})
        done.append("inventory")
        if coupon_code:
            promotion_client.post("/internal/coupons/redeem", json={
                "code": coupon_code, "user_id": order["user_id"], "order_id": order["id"], "subtotal": order["subtotal"]})
            done.append("coupon")
        payment = payment_client.post("/internal/payments", json={
            "order_id": order["id"], "order_code": order["code"], "user_id": order["user_id"], "amount": order["total"],
            "method": method, **(payment_extra or {})})
        done.append("payment")
        return payment
    except ApiError:
        compensate(done, order)
        discard_order(order["id"])
        raise


def set_status(order_id, new_status, note, actor, expected=None, extra_sets=None):
    ts = now_str()
    sets = {"status": new_status, "updated_at": ts, **(extra_sets or {})}
    with db.tx() as cur:
        sql = f"UPDATE orders SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?"
        params = list(sets.values()) + [order_id]
        if expected:
            sql += " AND status = ?"
            params.append(expected)
        if cur.execute(sql, params).rowcount != 1:
            raise ApiError(409, "Trạng thái đơn hàng đã thay đổi, vui lòng tải lại", code="STATUS_CONFLICT")
        cur.insert("INSERT INTO order_status_history (order_id, status, note, changed_by, created_at) VALUES (?, ?, ?, ?, ?)",
                   (order_id, new_status, note, actor, ts))
    return get_order_row(order_id)


def fetch_payment(order_id):
    try:
        status, body = payment_client.request("GET", f"/internal/payments/order/{order_id}")
        return body if status == 200 else None
    except ApiError:
        return None


# =================================================================== ĐẶT HÀNG ONLINE
@app.post("/api/orders")
@require_auth
def checkout():
    """Đặt hàng online (Saga: giữ hàng, ghi nhận mã, tạo thanh toán)"""
    user = current_user()
    data = get_json()
    method = data.get("payment_method") or "COD"
    if method not in ONLINE_METHODS:
        raise bad_request("Phương thức thanh toán không hợp lệ (COD, BANK_TRANSFER, EWALLET)")
    from_cart = not data.get("items")
    if from_cart:
        cart_items = cart_client.get(f"/internal/carts/{user['id']}")["items"]
        if not cart_items:
            raise bad_request("Giỏ hàng đang trống")
        merged = normalize_items(cart_items)
    else:
        merged = normalize_items(data["items"])

    # Thông tin giao hàng: theo address_id trong sổ địa chỉ hoặc nhập trực tiếp
    if data.get("address_id"):
        addr = auth_client.get(f"/internal/users/{user['id']}/addresses/{to_int(data['address_id'], 'address_id')}")
    else:
        addr = data.get("shipping_address") or {}
        if not isinstance(addr, dict):
            raise bad_request("Địa chỉ giao hàng không hợp lệ")
        missing = [k for k in ("recipient_name", "phone", "address_line") if not clean_str(addr.get(k))]
        if missing:
            raise bad_request("Vui lòng nhập đầy đủ người nhận, số điện thoại và địa chỉ giao hàng", details={"missing": missing})
    full_address = ", ".join(x for x in (clean_str(addr.get("address_line")), clean_str(addr.get("ward")),
                                         clean_str(addr.get("district")), clean_str(addr.get("city"))) if x)

    lines = price_lines(merged)
    subtotal = sum(ln["line_total"] for ln in lines)
    coupon_code = (clean_str(data.get("coupon_code"), 30) or "").upper() or None
    discount = 0
    if coupon_code:
        discount = promotion_client.post("/internal/coupons/validate", json={
            "code": coupon_code, "user_id": user["id"], "subtotal": subtotal})["discount"]
    shipping_fee = 0 if subtotal - discount >= FREE_SHIP_THRESHOLD else SHIPPING_FEE
    total = subtotal - discount + shipping_fee

    order = insert_order({
        "user_id": user["id"], "customer_name": clean_str(addr.get("recipient_name"), 100) or user["name"],
        "customer_email": user["email"], "customer_phone": clean_str(addr.get("phone"), 20),
        "shipping_address": full_address, "channel": "ONLINE", "payment_method": method,
        "subtotal": subtotal, "discount": discount, "shipping_fee": shipping_fee, "total": total,
        "coupon_code": coupon_code, "note": clean_str(data.get("note"), 500), "created_by": user["name"],
    }, lines, user["name"])

    payment = run_saga(order, lines, coupon_code, method)

    if from_cart:
        try:
            cart_client.delete(f"/internal/carts/{user['id']}", params={"product_ids": ",".join(map(str, merged))})
        except ApiError as exc:
            app.logger.warning("Không xóa được giỏ hàng: %s", exc.message)
    order = get_order_row(order["id"])
    bus.publish("order.created", event_payload(order, items=items_payload(order["id"])))
    result = order_view(order, full=True)
    result["payment"] = payment
    return result, 201


@app.post("/api/orders/preview")
@require_auth
def checkout_preview():
    """Tính trước tạm tính / giảm giá / phí ship (không tạo đơn)."""
    user = current_user()
    data = get_json(required=False)
    if data.get("items"):
        merged = normalize_items(data["items"])
    else:
        cart_items = cart_client.get(f"/internal/carts/{user['id']}")["items"]
        if not cart_items:
            raise bad_request("Giỏ hàng đang trống")
        merged = normalize_items(cart_items)
    lines = price_lines(merged)
    subtotal = sum(ln["line_total"] for ln in lines)
    discount, coupon_message, coupon_ok = 0, None, None
    code = (clean_str(data.get("coupon_code"), 30) or "").upper()
    if code:
        try:
            res = promotion_client.post("/internal/coupons/validate", json={"code": code, "user_id": user["id"], "subtotal": subtotal})
            discount, coupon_message, coupon_ok = res["discount"], res["label"], True
        except ApiError as exc:
            if exc.status >= 500:
                raise
            coupon_message, coupon_ok = exc.message, False
    shipping_fee = 0 if subtotal - discount >= FREE_SHIP_THRESHOLD else SHIPPING_FEE
    return {"lines": lines, "subtotal": subtotal, "discount": discount, "shipping_fee": shipping_fee,
            "total": subtotal - discount + shipping_fee, "coupon_code": code or None, "coupon_valid": coupon_ok,
            "coupon_message": coupon_message, "free_ship_threshold": FREE_SHIP_THRESHOLD}


@app.get("/api/orders/my")
@require_auth
def my_orders():
    """Đơn hàng của tôi"""
    user = current_user()
    page, size, offset = pagination(default_size=10)
    where, params = ["user_id = ?"], [user["id"]]
    if request.args.get("status"):
        where.append("status = ?")
        params.append(request.args["status"])
    cond = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) AS n FROM orders WHERE {cond}", params)
    rows = db.query(f"SELECT * FROM orders WHERE {cond} ORDER BY id DESC LIMIT ? OFFSET ?", params + [size, offset])
    return paged([order_view(r) for r in rows], total, page, size)


@app.get("/api/orders/<int:order_id>")
@require_auth
def order_detail(order_id):
    """Chi tiết đơn hàng, lịch sử và thanh toán"""
    row = get_order_row(order_id)
    user = current_user()
    if not is_staff(user) and row["user_id"] != user["id"]:
        raise forbidden("Bạn không có quyền xem đơn hàng này")
    result = order_view(row, full=True)
    result["payment"] = fetch_payment(order_id)
    return result


def cancel_order(row, reason, actor):
    if row["status"] not in ("PENDING", "CONFIRMED"):
        raise bad_request(f"Không thể hủy đơn đang ở trạng thái '{STATUS_LABELS[row['status']]}'")
    # Các bước bù trừ đều idempotent -> có thể thử lại an toàn nếu lỗi giữa chừng
    inventory_client.post("/internal/inventory/release", json={"order_id": row["id"], "order_code": row["code"]})
    payment = payment_client.post(f"/internal/payments/order/{row['id']}/cancel", json={"reason": reason, "by": actor})
    if row["coupon_code"]:
        try:
            promotion_client.post("/internal/coupons/release", json={"order_id": row["id"]})
        except ApiError as exc:
            app.logger.warning("Không hoàn được lượt mã giảm giá: %s", exc.message)
    extra = {"cancel_reason": reason}
    if payment.get("status") == "REFUNDED":
        extra["payment_status"] = "REFUNDED"
    updated = set_status(row["id"], "CANCELLED", reason, actor, expected=row["status"], extra_sets=extra)
    bus.publish("order.cancelled", event_payload(updated, reason=reason, cancelled_by=actor,
                                                 refunded=payment.get("status") == "REFUNDED"))
    return updated


@app.post("/api/orders/<int:order_id>/cancel")
@require_auth
def customer_cancel(order_id):
    """Hủy đơn (trả hàng, hủy / hoàn tiền, hoàn lượt mã)"""
    user = current_user()
    row = get_order_row(order_id)
    if row["user_id"] != user["id"] and not is_staff(user):
        raise forbidden("Bạn không có quyền hủy đơn hàng này")
    if not is_staff(user) and row["status"] != "PENDING":
        raise bad_request("Đơn hàng đã được xác nhận, vui lòng liên hệ cửa hàng để hủy")
    reason = clean_str(get_json(required=False).get("reason"), 255) or "Khách hàng hủy đơn"
    return order_view(cancel_order(row, reason, user["name"]), full=True)


# =================================================================== QUẢN LÝ (NHÂN VIÊN)
@app.get("/api/orders")
@require_staff
def list_orders():
    """Quản lý đơn hàng (lọc trạng thái, kênh, ngày)"""
    page, size, offset = pagination(default_size=20)
    where, params = ["1 = 1"], []
    for key in ("status", "channel", "payment_status", "payment_method"):
        if request.args.get(key):
            where.append(f"{key} = ?")
            params.append(request.args[key])
    q = clean_str(request.args.get("q"))
    if q:
        where.append("(UPPER(code) LIKE ? OR customer_phone LIKE ? OR LOWER(COALESCE(customer_name, '')) LIKE ?)")
        params += [f"%{q.upper()}%", f"%{q}%", f"%{q.lower()}%"]
    if request.args.get("date_from"):
        where.append("created_at >= ?")
        params.append(request.args["date_from"][:10] + " 00:00:00")
    if request.args.get("date_to"):
        where.append("created_at <= ?")
        params.append(request.args["date_to"][:10] + " 23:59:59")
    cond = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) AS n FROM orders WHERE {cond}", params)
    rows = db.query(f"SELECT * FROM orders WHERE {cond} ORDER BY id DESC LIMIT ? OFFSET ?", params + [size, offset])
    counts = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) AS n FROM orders GROUP BY status")}
    result = paged([order_view(r) for r in rows], total, page, size)
    result["status_counts"] = counts
    return result


@app.put("/api/orders/<int:order_id>/status")
@require_staff
def update_status(order_id):
    """Chuyển trạng thái đơn: xác nhận, giao, đã giao, hủy"""
    data = get_json()
    new_status = data.get("status")
    note = clean_str(data.get("note"), 255)
    actor = current_user()["name"]
    row = get_order_row(order_id)
    if new_status not in TRANSITIONS.get(row["status"], ()):
        raise bad_request(f"Không thể chuyển từ '{STATUS_LABELS.get(row['status'])}' sang '{STATUS_LABELS.get(new_status, new_status)}'")

    if new_status == "CANCELLED":
        return order_view(cancel_order(row, note or "Cửa hàng hủy đơn", actor), full=True)

    extra = {}
    if new_status == "SHIPPING":
        # Xuất kho khi giao cho đơn vị vận chuyển
        inventory_client.post("/internal/inventory/commit", json={"order_id": order_id, "order_code": row["code"], "by": actor})
    if new_status == "DELIVERED":
        extra["completed_at"] = now_str()
        if row["payment_method"] == "COD" and row["payment_status"] == "UNPAID":
            payment_client.post(f"/internal/payments/order/{order_id}/mark-paid", json={"by": actor})
            extra["payment_status"] = "PAID"
    default_notes = {"CONFIRMED": "Cửa hàng đã xác nhận đơn", "SHIPPING": "Đơn hàng đang được giao",
                     "DELIVERED": "Giao hàng thành công"}
    updated = set_status(order_id, new_status, note or default_notes[new_status], actor, expected=row["status"],
                         extra_sets=extra)
    bus.publish("order.status_changed", event_payload(updated, old_status=row["status"], new_status=new_status,
                                                      status_label=STATUS_LABELS[new_status], note=note))
    if new_status == "DELIVERED":
        bus.publish("order.completed", event_payload(updated, items=items_payload(order_id)))
    return order_view(updated, full=True)


# =================================================================== BÁN TẠI QUẦY (POS)
@app.post("/api/pos/orders")
@require_staff
def pos_checkout():
    """Bán tại quầy: thanh toán và xuất kho ngay"""
    staff = current_user()
    data = get_json()
    method = data.get("payment_method") or "CASH"
    if method not in POS_METHODS:
        raise bad_request("Phương thức thanh toán tại quầy: CASH, CARD hoặc BANK_TRANSFER")
    merged = normalize_items(data.get("items"))
    lines = price_lines(merged)
    subtotal = sum(ln["line_total"] for ln in lines)
    coupon_code = (clean_str(data.get("coupon_code"), 30) or "").upper() or None
    discount = 0
    if coupon_code:
        discount = promotion_client.post("/internal/coupons/validate", json={"code": coupon_code, "subtotal": subtotal})["discount"]
    total = subtotal - discount
    cash_received, change = None, None
    if method == "CASH":
        cash_received = to_int(data.get("cash_received"), "cash_received", minimum=0, default=total)
        if cash_received < total:
            raise bad_request(f"Tiền khách đưa chưa đủ (cần {total:,}đ)".replace(",", "."))
        change = cash_received - total

    order = insert_order({
        "user_id": None, "customer_name": clean_str(data.get("customer_name"), 100) or "Khách lẻ",
        "customer_phone": clean_str(data.get("customer_phone"), 20), "channel": "POS", "payment_method": method,
        "subtotal": subtotal, "discount": discount, "shipping_fee": 0, "total": total, "coupon_code": coupon_code,
        "note": clean_str(data.get("note"), 500), "cash_received": cash_received, "change_amount": change,
        "created_by": staff["name"],
    }, lines, staff["name"])

    payment = run_saga(order, lines, coupon_code, method,
                       {"paid_now": True, "cash_received": cash_received, "change": change, "by": staff["name"]})
    try:
        inventory_client.post("/internal/inventory/commit", json={"order_id": order["id"], "order_code": order["code"],
                                                                  "by": staff["name"]})
    except ApiError:
        compensate(["inventory", "coupon", "payment"], order)
        discard_order(order["id"])
        raise
    updated = set_status(order["id"], "COMPLETED", "Bán tại quầy", staff["name"],
                         extra_sets={"payment_status": "PAID", "completed_at": now_str()})
    items = items_payload(order["id"])
    bus.publish("order.created", event_payload(updated, items=items))
    bus.publish("order.completed", event_payload(updated, items=items))
    result = order_view(updated, full=True)
    result["payment"] = payment
    return result, 201


# =================================================================== BÁO CÁO
def _date_range():
    date_to = (request.args.get("date_to") or today_str())[:10]
    date_from = (request.args.get("date_from") or
                 (datetime.strptime(date_to, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d"))[:10]
    try:
        d1 = datetime.strptime(date_from, "%Y-%m-%d")
        d2 = datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        raise bad_request("Ngày không hợp lệ (định dạng YYYY-MM-DD)")
    if d1 > d2:
        raise bad_request("Ngày bắt đầu phải trước ngày kết thúc")
    if (d2 - d1).days > 366:
        raise bad_request("Khoảng thời gian tối đa 1 năm")
    return d1, d2


def build_report(d1, d2):
    start, end = d1.strftime("%Y-%m-%d 00:00:00"), d2.strftime("%Y-%m-%d 23:59:59")
    rng, rs = (start, end), REVENUE_STATUSES
    totals = db.query_one(
        f"""SELECT COUNT(*) AS orders,
                   COALESCE(SUM(CASE WHEN status IN (?, ?) THEN total ELSE 0 END), 0) AS revenue,
                   COALESCE(SUM(CASE WHEN status IN (?, ?) THEN 1 ELSE 0 END), 0) AS completed_orders,
                   COALESCE(SUM(CASE WHEN status IN ('PENDING', 'CONFIRMED', 'SHIPPING') THEN total ELSE 0 END), 0) AS pending_revenue,
                   COALESCE(SUM(CASE WHEN status IN ('PENDING', 'CONFIRMED', 'SHIPPING') THEN 1 ELSE 0 END), 0) AS processing_orders,
                   COALESCE(SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END), 0) AS cancelled_orders,
                   COALESCE(SUM(CASE WHEN status IN (?, ?) THEN discount ELSE 0 END), 0) AS discount_total
            FROM orders WHERE created_at BETWEEN ? AND ?""", rs + rs + rs + rng)
    totals["avg_order_value"] = totals["revenue"] // totals["completed_orders"] if totals["completed_orders"] else 0
    totals["items_sold"] = db.scalar(
        f"""SELECT COALESCE(SUM(oi.quantity), 0) AS n FROM order_items oi JOIN orders o ON o.id = oi.order_id
            WHERE o.status IN (?, ?) AND o.created_at BETWEEN ? AND ?""", rs + rng)

    daily = {r["day"]: r for r in db.query(
        """SELECT SUBSTR(created_at, 1, 10) AS day, COUNT(*) AS orders, COALESCE(SUM(total), 0) AS revenue
           FROM orders WHERE status IN (?, ?) AND created_at BETWEEN ? AND ? GROUP BY SUBSTR(created_at, 1, 10)""", rs + rng)}
    by_day, cursor = [], d1
    while cursor <= d2:
        key = cursor.strftime("%Y-%m-%d")
        by_day.append({"date": key, "orders": daily.get(key, {}).get("orders", 0), "revenue": daily.get(key, {}).get("revenue", 0)})
        cursor += timedelta(days=1)

    top_products = db.query(
        """SELECT oi.product_id, oi.product_name, MAX(oi.category_icon) AS category_icon,
                  SUM(oi.quantity) AS quantity, SUM(oi.line_total) AS revenue
           FROM order_items oi JOIN orders o ON o.id = oi.order_id
           WHERE o.status IN (?, ?) AND o.created_at BETWEEN ? AND ?
           GROUP BY oi.product_id, oi.product_name ORDER BY SUM(oi.quantity) DESC, oi.product_id LIMIT 10""", rs + rng)
    by_channel = db.query(
        """SELECT channel, COUNT(*) AS orders, COALESCE(SUM(total), 0) AS revenue FROM orders
           WHERE status IN (?, ?) AND created_at BETWEEN ? AND ? GROUP BY channel""", rs + rng)
    by_payment = db.query(
        """SELECT payment_method, COUNT(*) AS orders, COALESCE(SUM(total), 0) AS revenue FROM orders
           WHERE status IN (?, ?) AND created_at BETWEEN ? AND ? GROUP BY payment_method""", rs + rng)
    by_status = db.query("SELECT status, COUNT(*) AS orders FROM orders WHERE created_at BETWEEN ? AND ? GROUP BY status", rng)
    for r in by_status:
        r["label"] = STATUS_LABELS.get(r["status"], r["status"])
    return {"date_from": d1.strftime("%Y-%m-%d"), "date_to": d2.strftime("%Y-%m-%d"), "totals": totals,
            "revenue_by_day": by_day, "top_products": top_products, "by_channel": by_channel,
            "by_payment_method": by_payment, "by_status": by_status}


@app.get("/api/reports/summary")
@require_staff
def report_summary():
    """Báo cáo doanh thu theo khoảng ngày"""
    d1, d2 = _date_range()
    return build_report(d1, d2)


# =================================================================== NỘI BỘ
@app.get("/internal/orders/purchased")
@internal_only
def internal_purchased():
    """Khách đã mua và nhận sản phẩm này chưa"""
    uid = to_int(request.args.get("user_id"), "user_id", required=True)
    pid = to_int(request.args.get("product_id"), "product_id", required=True)
    n = db.scalar("""SELECT COUNT(*) AS n FROM orders o JOIN order_items oi ON oi.order_id = o.id
                     WHERE o.user_id = ? AND oi.product_id = ? AND o.status = 'DELIVERED'""", (uid, pid))
    return {"purchased": n > 0}


@app.get("/internal/orders/report")
@internal_only
def internal_report():
    """Báo cáo doanh thu (cho dashboard)"""
    d1, d2 = _date_range()
    return build_report(d1, d2)


@app.get("/internal/orders/recent")
@internal_only
def internal_recent():
    """Các đơn hàng gần nhất"""
    limit = to_int(request.args.get("limit"), "limit", minimum=1, maximum=50, default=8)
    return {"items": [order_view(r) for r in db.query("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))]}


# =================================================================== SỰ KIỆN
@bus.on("payment.completed")
def on_payment_completed(data, event):
    """Thanh toán online thành công -> đánh dấu đã thanh toán và tự động xác nhận đơn."""
    order_id = int(data["order_id"])
    row = db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not row or row["payment_status"] == "PAID" and row["status"] != "PENDING":
        return
    db.execute("UPDATE orders SET payment_status = 'PAID', updated_at = ? WHERE id = ? AND payment_status = 'UNPAID'",
               (now_str(), order_id))
    if row["channel"] == "ONLINE" and row["status"] == "PENDING" and row["payment_method"] in ("BANK_TRANSFER", "EWALLET"):
        try:
            updated = set_status(order_id, "CONFIRMED", "Tự động xác nhận sau khi thanh toán thành công", "payment-service",
                                 expected="PENDING")
        except ApiError:
            return
        bus.publish("order.status_changed", event_payload(updated, old_status="PENDING", new_status="CONFIRMED",
                                                          status_label=STATUS_LABELS["CONFIRMED"],
                                                          note="Tự động xác nhận sau khi thanh toán"))


@bus.on("payment.refunded")
def on_payment_refunded(data, event):
    db.execute("UPDATE orders SET payment_status = 'REFUNDED', updated_at = ? WHERE id = ?", (now_str(), int(data["order_id"])))


def create_app():
    db.init_schema(SCHEMA)
    bus.init_app(app)
    register_service(app, "order", 8005)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8005)
