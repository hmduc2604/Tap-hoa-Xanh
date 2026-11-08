"""promotion-service: mã giảm giá (voucher) - tạo, kiểm tra điều kiện, áp dụng & hoàn lượt dùng."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from datetime import timedelta  # noqa: E402

from flask import request  # noqa: E402

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import current_user, internal_only, require_auth, require_staff  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import ApiError, bad_request, conflict, not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.utils import (clean_str, get_json, normalize_datetime, now, now_str, paged, pagination,  # noqa: E402
                          parse_bool, require_fields, to_int)

SERVICE = "promotion-service"
db = Database(default_sqlite="data/promotion.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="entity",
                      description="Mã giảm giá và lượt sử dụng")

SCHEMA = """
CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    discount_type TEXT NOT NULL,
    discount_value INTEGER NOT NULL,
    max_discount BIGINT,
    min_order_value BIGINT NOT NULL DEFAULT 0,
    usage_limit INTEGER,
    per_user_limit INTEGER NOT NULL DEFAULT 1,
    used_count INTEGER NOT NULL DEFAULT 0,
    start_at TEXT,
    end_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_public INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coupon_usages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id INTEGER NOT NULL REFERENCES coupons(id),
    code TEXT NOT NULL,
    user_id INTEGER,
    order_id INTEGER NOT NULL UNIQUE,
    discount_amount BIGINT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

TYPES = ("PERCENT", "FIXED")


def view(row):
    c = dict(row)
    c["is_active"] = bool(c["is_active"])
    c["is_public"] = bool(c["is_public"])
    c["remaining"] = None if c["usage_limit"] is None else max(0, c["usage_limit"] - c["used_count"])
    ts = now_str()
    if not c["is_active"]:
        c["state"] = "INACTIVE"
    elif c["start_at"] and ts < c["start_at"]:
        c["state"] = "UPCOMING"
    elif c["end_at"] and ts > c["end_at"]:
        c["state"] = "EXPIRED"
    elif c["remaining"] == 0:
        c["state"] = "USED_UP"
    else:
        c["state"] = "ACTIVE"
    if c["discount_type"] == "PERCENT":
        c["label"] = f"Giảm {c['discount_value']}%" + (f" (tối đa {c['max_discount']:,}đ)".replace(",", ".") if c["max_discount"] else "")
    else:
        c["label"] = f"Giảm {c['discount_value']:,}đ".replace(",", ".")
    return c


def evaluate(cur, code, user_id, subtotal):
    """Kiểm tra mã và tính số tiền giảm. Ném ApiError(400) với lý do cụ thể nếu không hợp lệ."""
    code = (code or "").strip().upper()
    if not code:
        raise bad_request("Vui lòng nhập mã giảm giá")
    row = cur.one("SELECT * FROM coupons WHERE code = ?", (code,))
    if not row:
        raise ApiError(400, "Mã giảm giá không tồn tại", code="COUPON_INVALID")
    c = view(row)
    messages = {
        "INACTIVE": "Mã giảm giá đã bị vô hiệu hóa",
        "UPCOMING": "Mã giảm giá chưa đến thời gian áp dụng",
        "EXPIRED": "Mã giảm giá đã hết hạn",
        "USED_UP": "Mã giảm giá đã hết lượt sử dụng",
    }
    if c["state"] != "ACTIVE":
        raise ApiError(400, messages[c["state"]], code="COUPON_" + c["state"])
    if subtotal < c["min_order_value"]:
        raise ApiError(400, f"Đơn hàng tối thiểu {c['min_order_value']:,}đ để dùng mã này".replace(",", "."),
                       code="COUPON_MIN_ORDER", details={"min_order_value": c["min_order_value"]})
    if user_id:
        used = cur.scalar("SELECT COUNT(*) AS n FROM coupon_usages WHERE coupon_id = ? AND user_id = ? AND status = 'USED'",
                          (c["id"], user_id))
        if used >= c["per_user_limit"]:
            raise ApiError(400, "Bạn đã dùng hết lượt cho mã giảm giá này", code="COUPON_USER_LIMIT")
    if c["discount_type"] == "PERCENT":
        discount = subtotal * c["discount_value"] // 100
        if c["max_discount"]:
            discount = min(discount, c["max_discount"])
    else:
        discount = c["discount_value"]
    discount = max(0, min(discount, subtotal))
    return c, discount


# =================================================================== KHÁCH HÀNG
@app.get("/api/coupons/available")
def available_coupons():
    """Mã giảm giá công khai đang hiệu lực"""
    rows = db.query("SELECT * FROM coupons WHERE is_active = 1 AND is_public = 1 ORDER BY min_order_value, id")
    items = [view(r) for r in rows]
    return {"items": [c for c in items if c["state"] == "ACTIVE"]}


@app.post("/api/coupons/validate")
@require_auth
def validate_coupon():
    """Kiểm tra mã và tính số tiền giảm"""
    data = get_json()
    subtotal = to_int(data.get("subtotal"), "subtotal", minimum=0, required=True)
    with db.tx(write=False) as cur:
        c, discount = evaluate(cur, data.get("code"), current_user()["id"], subtotal)
    return {"valid": True, "code": c["code"], "discount": discount, "coupon": c,
            "message": f"Áp dụng thành công: {c['label']}"}


# =================================================================== QUẢN TRỊ
def _payload(data, partial=False):
    if not partial:
        require_fields(data, ["code", "name", "discount_type", "discount_value"])
    p = {}
    if "code" in data:
        p["code"] = (clean_str(data["code"], 30) or "").upper().replace(" ", "")
        if not p["code"]:
            raise bad_request("Mã không được để trống")
    for k, n in (("name", 100), ("description", 500)):
        if k in data:
            p[k] = clean_str(data[k], n)
    if "discount_type" in data:
        if data["discount_type"] not in TYPES:
            raise bad_request("Loại giảm giá phải là PERCENT hoặc FIXED")
        p["discount_type"] = data["discount_type"]
    if "discount_value" in data:
        p["discount_value"] = to_int(data["discount_value"], "discount_value", minimum=1, required=True)
    for k in ("max_discount", "usage_limit"):
        if k in data:
            p[k] = to_int(data[k], k, minimum=1)
    if "min_order_value" in data:
        p["min_order_value"] = to_int(data["min_order_value"], "min_order_value", minimum=0, default=0)
    if "per_user_limit" in data:
        p["per_user_limit"] = to_int(data["per_user_limit"], "per_user_limit", minimum=1, default=1)
    if "start_at" in data:
        p["start_at"] = normalize_datetime(data["start_at"])
    if "end_at" in data:
        p["end_at"] = normalize_datetime(data["end_at"], end_of_day=True)
    for k in ("is_active", "is_public"):
        if k in data:
            p[k] = 1 if parse_bool(data[k]) else 0
    return p


def _validate_rules(c):
    if c.get("discount_type") == "PERCENT" and c.get("discount_value", 0) > 100:
        raise bad_request("Phần trăm giảm không được vượt quá 100")
    if c.get("start_at") and c.get("end_at") and c["start_at"] > c["end_at"]:
        raise bad_request("Ngày bắt đầu phải trước ngày kết thúc")


@app.get("/api/coupons")
@require_staff
def list_coupons():
    """Danh sách mã giảm giá"""
    page, size, offset = pagination(default_size=20)
    total = db.scalar("SELECT COUNT(*) AS n FROM coupons")
    rows = db.query("SELECT * FROM coupons ORDER BY id DESC LIMIT ? OFFSET ?", (size, offset))
    return paged([view(r) for r in rows], total, page, size)


@app.post("/api/coupons")
@require_staff
def create_coupon():
    """Tạo mã giảm giá"""
    p = _payload(get_json())
    _validate_rules(p)
    if db.query_one("SELECT id FROM coupons WHERE code = ?", (p["code"],)):
        raise conflict("Mã giảm giá đã tồn tại")
    ts = now_str()
    cols = ["code", "name", "description", "discount_type", "discount_value", "max_discount", "min_order_value",
            "usage_limit", "per_user_limit", "start_at", "end_at", "is_active", "is_public"]
    defaults = {"min_order_value": 0, "per_user_limit": 1, "is_active": 1, "is_public": 1}
    values = [p.get(c, defaults.get(c)) for c in cols]
    with db.tx() as cur:
        cid = cur.insert(f"INSERT INTO coupons ({', '.join(cols)}, created_at, updated_at) "
                         f"VALUES ({', '.join('?' * (len(cols) + 2))})", values + [ts, ts])
    return view(db.query_one("SELECT * FROM coupons WHERE id = ?", (cid,))), 201


@app.put("/api/coupons/<int:cid>")
@require_staff
def update_coupon(cid):
    """Sửa mã giảm giá"""
    row = db.query_one("SELECT * FROM coupons WHERE id = ?", (cid,))
    if not row:
        raise not_found("Không tìm thấy mã giảm giá")
    p = _payload(get_json(), partial=True)
    _validate_rules({**row, **p})
    if "code" in p and db.query_one("SELECT id FROM coupons WHERE code = ? AND id <> ?", (p["code"], cid)):
        raise conflict("Mã giảm giá đã tồn tại")
    if p:
        p["updated_at"] = now_str()
        db.execute(f"UPDATE coupons SET {', '.join(k + ' = ?' for k in p)} WHERE id = ?", list(p.values()) + [cid])
    return view(db.query_one("SELECT * FROM coupons WHERE id = ?", (cid,)))


@app.delete("/api/coupons/<int:cid>")
@require_staff
def delete_coupon(cid):
    """Xóa mã (mã đã dùng sẽ bị tắt)"""
    row = db.query_one("SELECT * FROM coupons WHERE id = ?", (cid,))
    if not row:
        raise not_found("Không tìm thấy mã giảm giá")
    if db.scalar("SELECT COUNT(*) AS n FROM coupon_usages WHERE coupon_id = ?", (cid,)):
        db.execute("UPDATE coupons SET is_active = 0, updated_at = ? WHERE id = ?", (now_str(), cid))
        return {"message": "Mã đã có lượt sử dụng nên được vô hiệu hóa thay vì xóa"}
    db.execute("DELETE FROM coupons WHERE id = ?", (cid,))
    return {"message": "Đã xóa mã giảm giá"}


@app.get("/api/coupons/<int:cid>/usages")
@require_staff
def coupon_usages(cid):
    """Lượt sử dụng của một mã"""
    page, size, offset = pagination(default_size=20)
    total = db.scalar("SELECT COUNT(*) AS n FROM coupon_usages WHERE coupon_id = ?", (cid,))
    rows = db.query("SELECT * FROM coupon_usages WHERE coupon_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (cid, size, offset))
    return paged(rows, total, page, size)


# =================================================================== NỘI BỘ (SAGA)
@app.post("/internal/coupons/validate")
@internal_only
def internal_validate():
    """Kiểm tra mã giảm giá cho đơn hàng"""
    data = get_json()
    subtotal = to_int(data.get("subtotal"), "subtotal", minimum=0, required=True)
    with db.tx(write=False) as cur:
        c, discount = evaluate(cur, data.get("code"), to_int(data.get("user_id"), "user_id"), subtotal)
    return {"code": c["code"], "discount": discount, "label": c["label"]}


@app.post("/internal/coupons/redeem")
@internal_only
def internal_redeem():
    """Ghi nhận lượt dùng mã cho đơn hàng (idempotent theo order_id)."""
    data = get_json()
    order_id = to_int(data.get("order_id"), "order_id", minimum=1, required=True)
    user_id = to_int(data.get("user_id"), "user_id")
    subtotal = to_int(data.get("subtotal"), "subtotal", minimum=0, required=True)
    with db.tx() as cur:
        existing = cur.one("SELECT * FROM coupon_usages WHERE order_id = ?", (order_id,))
        if existing and existing["status"] == "USED":
            return {"code": existing["code"], "discount": existing["discount_amount"], "status": "USED"}
        c, discount = evaluate(cur, data.get("code"), user_id, subtotal)
        changed = cur.execute(
            "UPDATE coupons SET used_count = used_count + 1, updated_at = ? "
            "WHERE id = ? AND (usage_limit IS NULL OR used_count < usage_limit)", (now_str(), c["id"])).rowcount
        if changed != 1:
            raise ApiError(400, "Mã giảm giá đã hết lượt sử dụng", code="COUPON_USED_UP")
        ts = now_str()
        if existing:
            cur.execute("UPDATE coupon_usages SET coupon_id = ?, code = ?, user_id = ?, discount_amount = ?, status = 'USED', "
                        "updated_at = ? WHERE id = ?", (c["id"], c["code"], user_id, discount, ts, existing["id"]))
        else:
            cur.insert("INSERT INTO coupon_usages (coupon_id, code, user_id, order_id, discount_amount, status, created_at, updated_at) "
                       "VALUES (?, ?, ?, ?, ?, 'USED', ?, ?)", (c["id"], c["code"], user_id, order_id, discount, ts, ts))
    return {"code": c["code"], "discount": discount, "status": "USED"}


@app.post("/internal/coupons/release")
@internal_only
def internal_release():
    """Compensation: hoàn lại lượt dùng mã khi đơn bị hủy."""
    order_id = to_int(get_json().get("order_id"), "order_id", minimum=1, required=True)
    with db.tx() as cur:
        usage = cur.one("SELECT * FROM coupon_usages WHERE order_id = ? AND status = 'USED'", (order_id,))
        if not usage:
            return {"status": "NOTHING_TO_RELEASE"}
        cur.execute("UPDATE coupon_usages SET status = 'RELEASED', updated_at = ? WHERE id = ?", (now_str(), usage["id"]))
        cur.execute("UPDATE coupons SET used_count = used_count - 1 WHERE id = ? AND used_count > 0", (usage["coupon_id"],))
    return {"status": "RELEASED", "code": usage["code"]}


# =================================================================== KHỞI TẠO
def seed():
    if not db.is_empty("coupons"):
        return
    ts = now_str()
    end = (now() + timedelta(days=180)).strftime("%Y-%m-%d 23:59:59")
    coupons = [
        ("WELCOME10", "Chào bạn mới", "Giảm 10% cho đơn đầu tiên, tối đa 30.000đ", "PERCENT", 10, 30000, 100000, None, 1, 1),
        ("GIAM20K", "Giảm 20K", "Giảm 20.000đ cho đơn từ 200.000đ", "FIXED", 20000, None, 200000, 500, 3, 1),
        ("SALE50K", "Siêu sale 50K", "Giảm 50.000đ cho đơn từ 500.000đ", "FIXED", 50000, None, 500000, 100, 1, 1),
        ("VIP15", "Khách hàng thân thiết", "Giảm 15% tối đa 100.000đ (mã riêng)", "PERCENT", 15, 100000, 300000, 50, 2, 0),
    ]
    with db.tx() as cur:
        cur.lock("seed")
        if cur.scalar("SELECT COUNT(*) AS n FROM coupons"):  # instance khác đã seed
            return
        for code, name, desc, typ, val, max_d, min_o, limit, per_user, public in coupons:
            cur.insert(
                "INSERT INTO coupons (code, name, description, discount_type, discount_value, max_discount, min_order_value, "
                "usage_limit, per_user_limit, start_at, end_at, is_active, is_public, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (code, name, desc, typ, val, max_d, min_o, limit, per_user, ts[:10] + " 00:00:00", end, public, ts, ts))
    app.logger.info("Đã tạo mã giảm giá mẫu")


def create_app():
    db.init_schema(SCHEMA)
    seed()
    bus.init_app(app)
    register_service(app, "promotion", 8007)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8007)
