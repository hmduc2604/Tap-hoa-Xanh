"""inventory-service: tồn kho, giữ hàng cho đơn (reserve/commit/release), nhập kho, nhà cung cấp, cảnh báo sắp hết.

Lưu bản sao (replica) tên/SKU sản phẩm, đồng bộ qua sự kiện product.created/updated
để không phải gọi ngược sang product-service khi hiển thị kho.
"""
import os
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import request  # noqa: E402

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import current_user, internal_only, require_admin, require_staff  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import ApiError, bad_request, conflict, not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.http_client import ServiceClient  # noqa: E402
from common.seed_data import PRODUCTS  # noqa: E402
from common.utils import (clean_str, get_json, id_list, now_str, paged, pagination, parse_bool,  # noqa: E402
                          random_code, require_fields, strip_accents, to_int)

SERVICE = "inventory-service"
db = Database(default_sqlite="data/inventory.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="entity",
                      description="Tồn kho, giữ hàng cho đơn, nhập kho và nhà cung cấp")
products_client = ServiceClient("product", timeout=5)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    product_id INTEGER PRIMARY KEY,
    sku TEXT,
    product_name TEXT,
    unit TEXT,
    search_text TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 0,
    reserved INTEGER NOT NULL DEFAULT 0,
    min_quantity INTEGER NOT NULL DEFAULT 10,
    is_active INTEGER NOT NULL DEFAULT 1,
    low_stock_alerted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    ref_type TEXT,
    ref_id TEXT,
    note TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_movements_product ON stock_movements(product_id);
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (order_id, product_id)
);
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_person TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    note TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    supplier_id INTEGER REFERENCES suppliers(id),
    supplier_name TEXT,
    total_quantity INTEGER NOT NULL,
    total_cost BIGINT NOT NULL,
    note TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_receipt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL REFERENCES stock_receipts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL,
    product_name TEXT,
    quantity INTEGER NOT NULL,
    unit_cost BIGINT NOT NULL,
    line_total BIGINT NOT NULL
)
"""

MOVEMENT_LABELS = {
    "IMPORT": "Nhập kho", "SALE": "Xuất bán", "ADJUST": "Điều chỉnh", "RETURN": "Hoàn kho", "INITIAL": "Tồn đầu kỳ",
}


def stock_view(row):
    s = dict(row)
    s.pop("search_text", None)
    s["available"] = s["quantity"] - s["reserved"]
    s["is_active"] = bool(s["is_active"])
    s.pop("low_stock_alerted", None)
    if s["available"] <= 0:
        s["status"] = "OUT_OF_STOCK"
    elif s["available"] <= s["min_quantity"]:
        s["status"] = "LOW_STOCK"
    else:
        s["status"] = "IN_STOCK"
    return s


def actor():
    user = current_user()
    return user["name"] if user else "system"


def record_movement(cur, product_id, mtype, qty, ref_type=None, ref_id=None, note=None, by=None):
    balance = cur.scalar("SELECT quantity FROM stocks WHERE product_id = ?", (product_id,))
    cur.insert(
        "INSERT INTO stock_movements (product_id, type, quantity, balance_after, ref_type, ref_id, note, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (product_id, mtype, qty, balance or 0, ref_type, None if ref_id is None else str(ref_id), note, by or "system", now_str()),
    )


def upsert_replica(cur, product_id, sku, name, unit, is_active=True, min_quantity=None):
    existing = cur.one("SELECT product_id FROM stocks WHERE product_id = ?", (product_id,))
    text = strip_accents(f"{name} {sku}")
    if existing:
        cur.execute("UPDATE stocks SET sku = ?, product_name = ?, unit = ?, search_text = ?, is_active = ? WHERE product_id = ?",
                    (sku, name, unit, text, 1 if is_active else 0, product_id))
        return False
    cur.execute(
        "INSERT INTO stocks (product_id, sku, product_name, unit, search_text, quantity, reserved, min_quantity, is_active, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?)",
        (product_id, sku, name, unit, text, 10 if min_quantity is None else min_quantity, 1 if is_active else 0, now_str()),
    )
    return True


def ensure_stock_rows(product_ids):
    """Đảm bảo có bản ghi tồn kho (phòng khi sự kiện product.created đến chậm)."""
    if not product_ids:
        return
    marks = ",".join("?" * len(product_ids))
    have = {r["product_id"] for r in db.query(f"SELECT product_id FROM stocks WHERE product_id IN ({marks})", product_ids)}
    missing = [pid for pid in product_ids if pid not in have]
    if not missing:
        return
    items = products_client.post("/internal/products/batch", json={"ids": missing})["items"]
    found = {p["id"]: p for p in items}
    not_exist = [pid for pid in missing if pid not in found]
    if not_exist:
        raise bad_request("Sản phẩm không tồn tại: " + ", ".join(map(str, not_exist)))
    with db.tx() as cur:
        for p in items:
            upsert_replica(cur, p["id"], p["sku"], p["name"], p["unit"], p["is_active"])


def low_stock_check(product_ids):
    """Phát sự kiện inventory.low_stock một lần khi tồn kho xuống dưới ngưỡng."""
    if not product_ids:
        return
    marks = ",".join("?" * len(product_ids))
    alerts = []
    with db.tx() as cur:
        rows = cur.all(f"SELECT * FROM stocks WHERE product_id IN ({marks})", list(product_ids))
        for r in rows:
            available = r["quantity"] - r["reserved"]
            if available <= r["min_quantity"] and not r["low_stock_alerted"] and r["is_active"]:
                cur.execute("UPDATE stocks SET low_stock_alerted = 1 WHERE product_id = ?", (r["product_id"],))
                alerts.append({"product_id": r["product_id"], "product_name": r["product_name"], "sku": r["sku"],
                               "available": available, "min_quantity": r["min_quantity"]})
            elif available > r["min_quantity"] and r["low_stock_alerted"]:
                cur.execute("UPDATE stocks SET low_stock_alerted = 0 WHERE product_id = ?", (r["product_id"],))
    for alert in alerts:
        bus.publish("inventory.low_stock", alert)


# =================================================================== TỒN KHO
@app.get("/api/inventory")
@require_staff
def list_stock():
    """Danh sách tồn kho (lọc sắp hết / hết hàng)"""
    page, size, offset = pagination(default_size=20)
    where, params = ["1 = 1"], []
    q = strip_accents(request.args.get("q"))
    if q:
        where.append("search_text LIKE ?")
        params.append(f"%{q}%")
    status = request.args.get("status")
    if status == "low":
        where.append("quantity - reserved <= min_quantity AND quantity - reserved > 0")
    elif status == "out":
        where.append("quantity - reserved <= 0")
    elif status == "alert":
        where.append("quantity - reserved <= min_quantity")
    if not parse_bool(request.args.get("include_inactive"), default=False):
        where.append("is_active = 1")
    cond = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) AS n FROM stocks WHERE {cond}", params)
    rows = db.query(f"SELECT * FROM stocks WHERE {cond} ORDER BY (quantity - reserved) - min_quantity ASC, product_id "
                    f"LIMIT ? OFFSET ?", params + [size, offset])
    return paged([stock_view(r) for r in rows], total, page, size)


@app.get("/api/inventory/summary")
@require_staff
def stock_summary():
    """Tổng quan kho hàng"""
    return _summary()


def _summary():
    row = db.query_one(
        """SELECT COUNT(*) AS products, COALESCE(SUM(quantity), 0) AS total_units, COALESCE(SUM(reserved), 0) AS reserved_units,
           COALESCE(SUM(CASE WHEN quantity - reserved <= 0 THEN 1 ELSE 0 END), 0) AS out_of_stock,
           COALESCE(SUM(CASE WHEN quantity - reserved > 0 AND quantity - reserved <= min_quantity THEN 1 ELSE 0 END), 0) AS low_stock
           FROM stocks WHERE is_active = 1"""
    )
    month = now_str()[:7]
    row["imports_this_month"] = db.scalar(
        "SELECT COALESCE(SUM(total_cost), 0) AS v FROM stock_receipts WHERE created_at >= ?", (month + "-01 00:00:00",))
    return row


@app.get("/api/inventory/movements")
@require_staff
def list_movements():
    """Lịch sử nhập, xuất, điều chỉnh kho"""
    page, size, offset = pagination(default_size=30)
    where, params = ["1 = 1"], []
    pid = to_int(request.args.get("product_id"), "product_id")
    if pid:
        where.append("m.product_id = ?")
        params.append(pid)
    mtype = request.args.get("type")
    if mtype:
        where.append("m.type = ?")
        params.append(mtype)
    cond = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) AS n FROM stock_movements m WHERE {cond}", params)
    rows = db.query(
        f"""SELECT m.*, s.product_name, s.sku, s.unit FROM stock_movements m LEFT JOIN stocks s ON s.product_id = m.product_id
            WHERE {cond} ORDER BY m.id DESC LIMIT ? OFFSET ?""", params + [size, offset])
    for r in rows:
        r["type_label"] = MOVEMENT_LABELS.get(r["type"], r["type"])
    return paged(rows, total, page, size)


@app.get("/api/inventory/<int:pid>")
@require_staff
def get_stock(pid):
    """Tồn kho một sản phẩm kèm biến động gần nhất"""
    row = db.query_one("SELECT * FROM stocks WHERE product_id = ?", (pid,))
    if not row:
        raise not_found("Sản phẩm chưa có trong kho")
    result = stock_view(row)
    result["movements"] = db.query("SELECT * FROM stock_movements WHERE product_id = ? ORDER BY id DESC LIMIT 50", (pid,))
    for m in result["movements"]:
        m["type_label"] = MOVEMENT_LABELS.get(m["type"], m["type"])
    result["reservations"] = db.query(
        "SELECT * FROM reservations WHERE product_id = ? AND status = 'RESERVED' ORDER BY id DESC", (pid,))
    return result


@app.put("/api/inventory/<int:pid>/settings")
@require_staff
def update_settings(pid):
    """Đặt ngưỡng cảnh báo sắp hết hàng"""
    data = get_json()
    min_q = to_int(data.get("min_quantity"), "min_quantity", minimum=0, required=True)
    if not db.execute("UPDATE stocks SET min_quantity = ?, updated_at = ? WHERE product_id = ?", (min_q, now_str(), pid)):
        raise not_found("Sản phẩm chưa có trong kho")
    low_stock_check([pid])
    return stock_view(db.query_one("SELECT * FROM stocks WHERE product_id = ?", (pid,)))


@app.post("/api/inventory/adjust")
@require_staff
def adjust_stock():
    """Kiểm kê / điều chỉnh tồn kho: đặt số lượng thực tế hoặc cộng/trừ."""
    data = get_json()
    pid = to_int(data.get("product_id"), "product_id", minimum=1, required=True)
    reason = clean_str(data.get("reason"), 255)
    if not reason:
        raise bad_request("Vui lòng nhập lý do điều chỉnh")
    ensure_stock_rows([pid])
    with db.tx() as cur:
        row = cur.one("SELECT * FROM stocks WHERE product_id = ?", (pid,))
        if "new_quantity" in data and data["new_quantity"] not in (None, ""):
            new_q = to_int(data["new_quantity"], "new_quantity", minimum=0)
        else:
            new_q = row["quantity"] + to_int(data.get("change"), "change", required=True)
        if new_q < row["reserved"]:
            raise bad_request(f"Số lượng mới không được nhỏ hơn số đang giữ cho đơn hàng ({row['reserved']})")
        delta = new_q - row["quantity"]
        if delta == 0:
            raise bad_request("Số lượng không thay đổi")
        cur.execute("UPDATE stocks SET quantity = ?, updated_at = ? WHERE product_id = ?", (new_q, now_str(), pid))
        record_movement(cur, pid, "ADJUST", delta, "ADJUSTMENT", None, reason, actor())
    low_stock_check([pid])
    return stock_view(db.query_one("SELECT * FROM stocks WHERE product_id = ?", (pid,)))


# =================================================================== NHÀ CUNG CẤP
SUPPLIER_FIELDS = (("name", 200), ("contact_person", 100), ("phone", 20), ("email", 100), ("address", 255), ("note", 500))


@app.get("/api/suppliers")
@require_staff
def list_suppliers():
    """Danh sách nhà cung cấp"""
    where = "" if parse_bool(request.args.get("all")) else "WHERE s.is_active = 1"
    rows = db.query(
        f"""SELECT s.*, (SELECT COUNT(*) FROM stock_receipts r WHERE r.supplier_id = s.id) AS receipt_count,
            (SELECT COALESCE(SUM(total_cost), 0) FROM stock_receipts r WHERE r.supplier_id = s.id) AS total_purchased
            FROM suppliers s {where} ORDER BY s.id DESC""")
    for r in rows:
        r["is_active"] = bool(r["is_active"])
    return {"items": rows}


@app.post("/api/suppliers")
@require_staff
def create_supplier():
    """Thêm nhà cung cấp"""
    data = get_json()
    require_fields(data, ["name"])
    vals = [clean_str(data.get(k), n) for k, n in SUPPLIER_FIELDS]
    with db.tx() as cur:
        sid = cur.insert(
            "INSERT INTO suppliers (name, contact_person, phone, email, address, note, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)", vals + [now_str()])
    return db.query_one("SELECT * FROM suppliers WHERE id = ?", (sid,)), 201


@app.put("/api/suppliers/<int:sid>")
@require_staff
def update_supplier(sid):
    """Sửa thông tin nhà cung cấp"""
    data = get_json()
    if not db.query_one("SELECT id FROM suppliers WHERE id = ?", (sid,)):
        raise not_found("Không tìm thấy nhà cung cấp")
    p = {k: clean_str(data.get(k), n) for k, n in SUPPLIER_FIELDS if k in data}
    if "name" in p and not p["name"]:
        raise bad_request("Tên nhà cung cấp không được để trống")
    if "is_active" in data:
        p["is_active"] = 1 if parse_bool(data["is_active"]) else 0
    if p:
        db.execute(f"UPDATE suppliers SET {', '.join(k + ' = ?' for k in p)} WHERE id = ?", list(p.values()) + [sid])
    return db.query_one("SELECT * FROM suppliers WHERE id = ?", (sid,))


@app.delete("/api/suppliers/<int:sid>")
@require_admin
def delete_supplier(sid):
    """Ngừng hợp tác nhà cung cấp"""
    if not db.execute("UPDATE suppliers SET is_active = 0 WHERE id = ?", (sid,)):
        raise not_found("Không tìm thấy nhà cung cấp")
    return {"message": "Đã ngừng hợp tác nhà cung cấp"}


# =================================================================== PHIẾU NHẬP KHO
@app.get("/api/stock-receipts")
@require_staff
def list_receipts():
    """Danh sách phiếu nhập kho"""
    page, size, offset = pagination(default_size=20)
    total = db.scalar("SELECT COUNT(*) AS n FROM stock_receipts")
    rows = db.query("SELECT * FROM stock_receipts ORDER BY id DESC LIMIT ? OFFSET ?", (size, offset))
    return paged(rows, total, page, size)


@app.get("/api/stock-receipts/<int:rid>")
@require_staff
def get_receipt(rid):
    """Chi tiết phiếu nhập kho"""
    row = db.query_one("SELECT * FROM stock_receipts WHERE id = ?", (rid,))
    if not row:
        raise not_found("Không tìm thấy phiếu nhập")
    row["items"] = db.query("SELECT * FROM stock_receipt_items WHERE receipt_id = ? ORDER BY id", (rid,))
    return row


@app.post("/api/stock-receipts")
@require_staff
def create_receipt():
    """Tạo phiếu nhập và cộng tồn kho"""
    data = get_json()
    raw_items = data.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        raise bad_request("Phiếu nhập phải có ít nhất một sản phẩm")
    items = {}
    for it in raw_items:
        pid = to_int(it.get("product_id"), "product_id", minimum=1, required=True)
        qty = to_int(it.get("quantity"), "quantity", minimum=1, maximum=100000, required=True)
        cost = to_int(it.get("unit_cost"), "unit_cost", minimum=0, default=0)
        if pid in items:
            items[pid]["quantity"] += qty
        else:
            items[pid] = {"product_id": pid, "quantity": qty, "unit_cost": cost}
    supplier = None
    supplier_id = to_int(data.get("supplier_id"), "supplier_id")
    if supplier_id:
        supplier = db.query_one("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
        if not supplier:
            raise bad_request("Nhà cung cấp không tồn tại")
    ensure_stock_rows(list(items))
    by = actor()
    total_qty = sum(i["quantity"] for i in items.values())
    total_cost = sum(i["quantity"] * i["unit_cost"] for i in items.values())
    with db.tx() as cur:
        code = random_code("PN")
        while cur.one("SELECT id FROM stock_receipts WHERE code = ?", (code,)):
            code = random_code("PN")
        rid = cur.insert(
            "INSERT INTO stock_receipts (code, supplier_id, supplier_name, total_quantity, total_cost, note, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (code, supplier_id, supplier["name"] if supplier else None, total_qty, total_cost,
             clean_str(data.get("note"), 500), by, now_str()))
        for it in items.values():
            name = cur.scalar("SELECT product_name FROM stocks WHERE product_id = ?", (it["product_id"],))
            cur.insert(
                "INSERT INTO stock_receipt_items (receipt_id, product_id, product_name, quantity, unit_cost, line_total) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rid, it["product_id"], name, it["quantity"], it["unit_cost"], it["quantity"] * it["unit_cost"]))
            cur.execute("UPDATE stocks SET quantity = quantity + ?, updated_at = ? WHERE product_id = ?",
                        (it["quantity"], now_str(), it["product_id"]))
            record_movement(cur, it["product_id"], "IMPORT", it["quantity"], "RECEIPT", code,
                            f"Nhập kho phiếu {code}", by)
    low_stock_check(list(items))
    bus.publish("inventory.restocked", {"receipt_code": code, "total_quantity": total_qty, "total_cost": total_cost,
                                        "product_ids": list(items)})
    return get_receipt(rid), 201


# =================================================================== NỘI BỘ (SAGA)
@app.post("/internal/inventory/availability")
@internal_only
def internal_availability():
    """Số lượng có thể bán của nhiều sản phẩm"""
    ids = id_list(get_json().get("product_ids") or [])
    if not ids:
        return {"items": {}}
    rows = db.query(f"SELECT product_id, quantity, reserved FROM stocks WHERE product_id IN ({','.join('?' * len(ids))})", ids)
    return {"items": {str(r["product_id"]): {"available": max(0, r["quantity"] - r["reserved"]), "quantity": r["quantity"]}
                      for r in rows}}


def _merge_items(raw):
    merged = {}
    for it in raw or []:
        pid = to_int(it.get("product_id"), "product_id", minimum=1, required=True)
        qty = to_int(it.get("quantity"), "quantity", minimum=1, required=True)
        merged[pid] = merged.get(pid, 0) + qty
    if not merged:
        raise bad_request("Danh sách sản phẩm trống")
    return merged


@app.post("/internal/inventory/reserve")
@internal_only
def internal_reserve():
    """Bước 1 của Saga đặt hàng: giữ hàng (all-or-nothing, idempotent theo order_id)."""
    data = get_json()
    order_id = to_int(data.get("order_id"), "order_id", minimum=1, required=True)
    items = _merge_items(data.get("items"))
    ts = now_str()
    with db.tx() as cur:
        existing = cur.all("SELECT * FROM reservations WHERE order_id = ?", (order_id,))
        if existing:
            return {"order_id": order_id, "status": "ALREADY_RESERVED", "items": existing}
        shortages = []
        for pid, qty in items.items():
            changed = cur.execute(
                "UPDATE stocks SET reserved = reserved + ?, updated_at = ? "
                "WHERE product_id = ? AND is_active = 1 AND quantity - reserved >= ?",
                (qty, ts, pid, qty)).rowcount
            if changed != 1:
                row = cur.one("SELECT product_name, quantity, reserved FROM stocks WHERE product_id = ?", (pid,))
                shortages.append({
                    "product_id": pid,
                    "product_name": row["product_name"] if row else None,
                    "requested": qty,
                    "available": max(0, row["quantity"] - row["reserved"]) if row else 0,
                })
        if shortages:
            names = ", ".join(f"{s['product_name'] or s['product_id']} (còn {s['available']})" for s in shortages)
            raise ApiError(409, f"Không đủ hàng: {names}", code="OUT_OF_STOCK", details=shortages)
        for pid, qty in items.items():
            cur.insert("INSERT INTO reservations (order_id, product_id, quantity, status, created_at, updated_at) "
                       "VALUES (?, ?, ?, 'RESERVED', ?, ?)", (order_id, pid, qty, ts, ts))
    low_stock_check(list(items))
    return {"order_id": order_id, "status": "RESERVED",
            "items": [{"product_id": k, "quantity": v} for k, v in items.items()]}


@app.post("/internal/inventory/commit")
@internal_only
def internal_commit():
    """Xuất kho thực tế cho đơn hàng (khi giao hàng / bán tại quầy)."""
    data = get_json()
    order_id = to_int(data.get("order_id"), "order_id", minimum=1, required=True)
    ref = clean_str(data.get("order_code"), 50) or str(order_id)
    by = clean_str(data.get("by"), 100) or "order-service"
    ts = now_str()
    with db.tx() as cur:
        rows = cur.all("SELECT * FROM reservations WHERE order_id = ?", (order_id,))
        if not rows:
            raise not_found("Đơn hàng chưa giữ hàng trong kho")
        for r in rows:
            if r["status"] != "RESERVED":
                continue
            cur.execute("UPDATE stocks SET quantity = quantity - ?, reserved = reserved - ?, updated_at = ? WHERE product_id = ?",
                        (r["quantity"], r["quantity"], ts, r["product_id"]))
            cur.execute("UPDATE reservations SET status = 'COMMITTED', updated_at = ? WHERE id = ?", (ts, r["id"]))
            record_movement(cur, r["product_id"], "SALE", -r["quantity"], "ORDER", ref, f"Xuất bán đơn {ref}", by)
    return {"order_id": order_id, "status": "COMMITTED"}


@app.post("/internal/inventory/release")
@internal_only
def internal_release():
    """Bù trừ (compensation) của Saga: trả lại hàng đã giữ khi đơn bị hủy/lỗi."""
    data = get_json()
    order_id = to_int(data.get("order_id"), "order_id", minimum=1, required=True)
    ref = clean_str(data.get("order_code"), 50) or str(order_id)
    ts = now_str()
    released = []
    with db.tx() as cur:
        for r in cur.all("SELECT * FROM reservations WHERE order_id = ?", (order_id,)):
            if r["status"] == "RESERVED":
                cur.execute("UPDATE stocks SET reserved = reserved - ?, updated_at = ? WHERE product_id = ?",
                            (r["quantity"], ts, r["product_id"]))
            elif r["status"] == "COMMITTED":
                cur.execute("UPDATE stocks SET quantity = quantity + ?, updated_at = ? WHERE product_id = ?",
                            (r["quantity"], ts, r["product_id"]))
                record_movement(cur, r["product_id"], "RETURN", r["quantity"], "ORDER", ref, f"Hoàn kho đơn {ref}",
                                "order-service")
            else:
                continue
            cur.execute("UPDATE reservations SET status = 'RELEASED', updated_at = ? WHERE id = ?", (ts, r["id"]))
            released.append(r["product_id"])
    low_stock_check(released)
    return {"order_id": order_id, "status": "RELEASED", "released_products": released}


@app.get("/internal/inventory/summary")
@internal_only
def internal_summary():
    """Tổng quan kho (cho dashboard)"""
    return _summary()


# =================================================================== SỰ KIỆN
@bus.on("product.created")
@bus.on("product.updated")
def on_product_changed(data, event):
    pid = int(data["product_id"])
    with db.tx() as cur:
        created = upsert_replica(cur, pid, data.get("sku"), data.get("name"), data.get("unit"),
                                 data.get("is_active", True), data.get("min_quantity"))
        initial = int(data.get("initial_stock") or 0)
        if created and initial > 0 and event.get("type") == "product.created":
            cur.execute("UPDATE stocks SET quantity = ? WHERE product_id = ?", (initial, pid))
            record_movement(cur, pid, "INITIAL", initial, "PRODUCT", pid, "Tồn đầu kỳ khi tạo sản phẩm",
                            data.get("created_by") or "system")
    low_stock_check([pid])


# =================================================================== KHỞI TẠO
def seed():
    if not db.is_empty("stocks"):
        return
    ts = now_str()
    with db.tx() as cur:
        cur.lock("seed")
        if cur.scalar("SELECT COUNT(*) AS n FROM stocks"):  # instance khác đã seed
            return
        for i, (_ci, sku, _bc, name, _brand, unit, _price, _sale, stock, min_q, _d) in enumerate(PRODUCTS, start=1):
            cur.execute(
                "INSERT INTO stocks (product_id, sku, product_name, unit, search_text, quantity, reserved, min_quantity, is_active, "
                "low_stock_alerted, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1, ?, ?)",
                (i, sku, name, unit, strip_accents(f"{name} {sku}"), stock, min_q, 1 if stock <= min_q else 0, ts))
            if stock:
                record_movement(cur, i, "INITIAL", stock, "SEED", None, "Tồn đầu kỳ", "system")
        suppliers = [
            ("Công ty TNHH Phân phối Hàng tiêu dùng Sài Gòn", "Anh Minh", "0281234567", "sales@pptd-sg.vn", "Q. Tân Bình, TP.HCM"),
            ("Nông trại Xanh Đà Lạt", "Chị Lan", "0263999888", "lan@nongtraixanh.vn", "Lâm Đồng"),
            ("Đại lý Sữa & Đồ uống Miền Nam", "Anh Tuấn", "0909777666", "tuan@daily-sua.vn", "Bình Dương"),
        ]
        for s in suppliers:
            cur.insert("INSERT INTO suppliers (name, contact_person, phone, email, address, is_active, created_at) "
                       "VALUES (?, ?, ?, ?, ?, 1, ?)", s + (ts,))
    app.logger.info("Đã tạo tồn kho đầu kỳ cho %s sản phẩm", len(PRODUCTS))


def reconcile_catalog(max_wait=900):
    """Đồng bộ kho với danh mục sản phẩm đang có (chạy nền một lần khi khởi động).

    Cơ sở dữ liệu cũ được product-service bổ sung sản phẩm mới theo seed_data (không có sự kiện product.created vì
    nạp trực tiếp). Hàm này hỏi product-service danh sách sản phẩm, rồi tạo bản ghi tồn kho còn thiếu: sản phẩm thuộc
    seed_data lấy tồn đầu kỳ trong seed_data, sản phẩm khác bắt đầu từ 0. Chạy lại bao nhiêu lần cũng không trùng."""
    seeded = {p[1]: p for p in PRODUCTS}
    deadline = time.time() + max_wait
    delay = 2
    while time.time() < deadline:
        try:
            added, page = 0, 1
            while True:
                data = products_client.get("/api/products", params={"page": page, "page_size": 100, "sort": "newest"})
                items = data["items"]
                have = {r["product_id"] for r in db.query(
                    f"SELECT product_id FROM stocks WHERE product_id IN ({','.join('?' * len(items))})",
                    [p["id"] for p in items])} if items else set()
                fresh = [p for p in items if p["id"] not in have]
                if fresh:
                    ts = now_str()
                    with db.tx() as cur:
                        cur.lock("reconcile")
                        for p in fresh:
                            if cur.scalar("SELECT COUNT(*) AS n FROM stocks WHERE product_id = ?", (p["id"],)):
                                continue
                            row = seeded.get(p["sku"])
                            stock, min_q = (row[8], row[9]) if row else (0, 10)
                            cur.execute(
                                "INSERT INTO stocks (product_id, sku, product_name, unit, search_text, quantity, reserved, "
                                "min_quantity, is_active, low_stock_alerted, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1, ?, ?)",
                                (p["id"], p["sku"], p["name"], p["unit"], strip_accents(f"{p['name']} {p['sku']}"), stock, min_q,
                                 1 if stock <= min_q else 0, ts))
                            if stock:
                                record_movement(cur, p["id"], "INITIAL", stock, "SEED", None, "Tồn đầu kỳ", "system")
                            added += 1
                if page * 100 >= data.get("total", 0):
                    break
                page += 1
            if added:
                app.logger.info("Đã tạo tồn kho cho %s sản phẩm mới trong danh mục", added)
            return added
        except Exception as exc:  # product-service chưa sẵn sàng: thử lại
            app.logger.debug("reconcile_catalog chờ product-service: %s", exc)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    app.logger.warning("Không đồng bộ được kho với danh mục sau %ss", max_wait)


def create_app():
    db.init_schema(SCHEMA)
    seed()
    threading.Thread(target=reconcile_catalog, daemon=True, name="reconcile-catalog").start()
    bus.init_app(app)
    register_service(app, "inventory", 8003)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8003)
