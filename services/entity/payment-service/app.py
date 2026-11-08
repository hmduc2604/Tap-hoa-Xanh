"""payment-service: thanh toán đơn hàng (COD, chuyển khoản, ví điện tử mô phỏng, tiền mặt tại quầy), hoàn tiền."""
import os
import sys
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import json  # noqa: E402

from flask import request  # noqa: E402

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import current_user, internal_only, is_staff, require_auth, require_staff  # noqa: E402
from common.config import env  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import ApiError, bad_request, forbidden, not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.utils import clean_str, get_json, now_str, paged, pagination, parse_bool, to_int  # noqa: E402

SERVICE = "payment-service"
db = Database(default_sqlite="data/payment.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="entity",
                      description="Giao dịch thanh toán và hoàn tiền")

METHODS = {
    "COD": "Thanh toán khi nhận hàng",
    "BANK_TRANSFER": "Chuyển khoản ngân hàng",
    "EWALLET": "Ví điện tử (mô phỏng)",
    "CASH": "Tiền mặt tại quầy",
    "CARD": "Thẻ ngân hàng tại quầy",
}
STATUS_LABELS = {"PENDING": "Chờ thanh toán", "PAID": "Đã thanh toán", "REFUNDED": "Đã hoàn tiền",
                 "CANCELLED": "Đã hủy", "FAILED": "Thất bại"}
BANK = {
    "bank_name": env("BANK_NAME", "Vietcombank"),
    "account_number": env("BANK_ACCOUNT_NUMBER", "0123456789"),
    "account_name": env("BANK_ACCOUNT_NAME", "CUA HANG TAP HOA XANH"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE,
    order_code TEXT NOT NULL,
    user_id INTEGER,
    amount BIGINT NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    transaction_ref TEXT,
    provider_data TEXT,
    paid_at TEXT,
    refunded_at TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    message TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL
)
"""


def view(row, with_logs=False):
    p = dict(row)
    p["method_label"] = METHODS.get(p["method"], p["method"])
    p["status_label"] = STATUS_LABELS.get(p["status"], p["status"])
    p["provider_data"] = json.loads(p["provider_data"]) if p.get("provider_data") else None
    if p["method"] == "BANK_TRANSFER" and p["status"] == "PENDING":
        p["instructions"] = {**BANK, "amount": p["amount"], "content": p["order_code"]}
    if p["method"] == "EWALLET" and p["status"] == "PENDING":
        p["payment_url"] = f"/pay.html?payment_id={p['id']}"
    if with_logs:
        p["logs"] = db.query("SELECT * FROM payment_logs WHERE payment_id = ? ORDER BY id", (p["id"],))
    return p


def log_action(cur, payment_id, action, message, by="system"):
    cur.insert("INSERT INTO payment_logs (payment_id, action, message, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
               (payment_id, action, message, by, now_str()))


def get_payment(pid):
    row = db.query_one("SELECT * FROM payments WHERE id = ?", (pid,))
    if not row:
        raise not_found("Không tìm thấy giao dịch thanh toán")
    return row


def check_access(row):
    user = current_user()
    if not is_staff(user) and row["user_id"] != user["id"]:
        raise forbidden("Bạn không có quyền xem giao dịch này")


def mark_paid(payment_id, by, message, txn_ref=None):
    """Chuyển PENDING -> PAID (idempotent) và phát sự kiện payment.completed."""
    ts = now_str()
    with db.tx() as cur:
        row = cur.one("SELECT * FROM payments WHERE id = ?", (payment_id,))
        if row["status"] == "PAID":
            return row
        if row["status"] != "PENDING":
            raise bad_request(f"Không thể xác nhận giao dịch đang ở trạng thái {STATUS_LABELS.get(row['status'])}")
        ref = txn_ref or f"TXN{uuid.uuid4().hex[:10].upper()}"
        cur.execute("UPDATE payments SET status = 'PAID', paid_at = ?, transaction_ref = ?, updated_at = ? WHERE id = ?",
                    (ts, ref, ts, payment_id))
        log_action(cur, payment_id, "PAID", message, by)
        row = cur.one("SELECT * FROM payments WHERE id = ?", (payment_id,))
    bus.publish("payment.completed", {"payment_id": row["id"], "order_id": row["order_id"], "order_code": row["order_code"],
                                      "user_id": row["user_id"], "amount": row["amount"], "method": row["method"],
                                      "transaction_ref": row["transaction_ref"]})
    return row


# =================================================================== API
@app.get("/api/payments/methods")
def payment_methods():
    """Các phương thức thanh toán và thông tin chuyển khoản"""
    return {"items": [{"code": k, "label": v} for k, v in METHODS.items() if k not in ("CASH", "CARD")],
            "bank": BANK}


@app.get("/api/payments/<int:pid>")
@require_auth
def payment_detail(pid):
    """Chi tiết một giao dịch"""
    row = get_payment(pid)
    check_access(row)
    return view(row, with_logs=is_staff())


@app.get("/api/payments/order/<int:order_id>")
@require_auth
def payment_by_order(order_id):
    """Giao dịch của một đơn hàng"""
    row = db.query_one("SELECT * FROM payments WHERE order_id = ?", (order_id,))
    if not row:
        raise not_found("Đơn hàng chưa có giao dịch thanh toán")
    check_access(row)
    return view(row, with_logs=is_staff())


@app.post("/api/payments/<int:pid>/pay")
@require_auth
def simulate_pay(pid):
    """Mô phỏng cổng thanh toán ví điện tử / ngân hàng: khách bấm thanh toán thành công hoặc thất bại."""
    row = get_payment(pid)
    user = current_user()
    if row["user_id"] != user["id"]:
        raise forbidden("Bạn không có quyền thanh toán giao dịch này")
    if row["method"] not in ("EWALLET", "BANK_TRANSFER"):
        raise bad_request("Phương thức này không hỗ trợ thanh toán trực tuyến")
    if row["status"] != "PENDING":
        raise bad_request(f"Giao dịch đang ở trạng thái: {STATUS_LABELS.get(row['status'])}")
    success = parse_bool(get_json(required=False).get("success"), default=True)
    if not success:
        with db.tx() as cur:
            log_action(cur, pid, "FAILED", "Khách hủy / thanh toán thất bại (mô phỏng)", user["name"])
        bus.publish("payment.failed", {"payment_id": pid, "order_id": row["order_id"], "order_code": row["order_code"],
                                       "user_id": row["user_id"], "amount": row["amount"]})
        raise ApiError(402, "Thanh toán không thành công, bạn có thể thử lại", code="PAYMENT_FAILED")
    row = mark_paid(pid, user["name"], f"Thanh toán trực tuyến qua {METHODS[row['method']]} (mô phỏng)")
    return view(row)


@app.post("/api/payments/<int:pid>/confirm")
@require_staff
def staff_confirm(pid):
    """Nhân viên xác nhận đã nhận tiền (chuyển khoản / COD)."""
    row = get_payment(pid)
    if row["method"] not in ("BANK_TRANSFER", "COD"):
        raise bad_request("Chỉ xác nhận thủ công cho chuyển khoản hoặc COD")
    note = clean_str(get_json(required=False).get("note"), 255) or "Nhân viên xác nhận đã nhận tiền"
    return view(mark_paid(pid, current_user()["name"], note))


@app.get("/api/payments")
@require_staff
def list_payments():
    """Danh sách giao dịch kèm tổng hợp tiền"""
    page, size, offset = pagination(default_size=20)
    where, params = ["1 = 1"], []
    for key in ("status", "method"):
        if request.args.get(key):
            where.append(f"{key} = ?")
            params.append(request.args[key])
    q = clean_str(request.args.get("q"))
    if q:
        where.append("(UPPER(order_code) LIKE ? OR UPPER(COALESCE(transaction_ref, '')) LIKE ?)")
        params += [f"%{q.upper()}%"] * 2
    cond = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) AS n FROM payments WHERE {cond}", params)
    rows = db.query(f"SELECT * FROM payments WHERE {cond} ORDER BY id DESC LIMIT ? OFFSET ?", params + [size, offset])
    summary = db.query_one(
        f"""SELECT COALESCE(SUM(CASE WHEN status = 'PAID' THEN amount ELSE 0 END), 0) AS paid_amount,
                   COALESCE(SUM(CASE WHEN status = 'PENDING' THEN amount ELSE 0 END), 0) AS pending_amount,
                   COALESCE(SUM(CASE WHEN status = 'REFUNDED' THEN amount ELSE 0 END), 0) AS refunded_amount
            FROM payments WHERE {cond}""", params)
    result = paged([view(r) for r in rows], total, page, size)
    result["summary"] = summary
    return result


# =================================================================== NỘI BỘ (SAGA)
@app.post("/internal/payments")
@internal_only
def internal_create():
    """Tạo giao dịch cho đơn hàng (idempotent theo order_id)."""
    data = get_json()
    order_id = to_int(data.get("order_id"), "order_id", minimum=1, required=True)
    amount = to_int(data.get("amount"), "amount", minimum=0, required=True)
    method = data.get("method")
    if method not in METHODS:
        raise bad_request("Phương thức thanh toán không hợp lệ")
    existing = db.query_one("SELECT * FROM payments WHERE order_id = ?", (order_id,))
    if existing:
        return view(existing)
    paid_now = parse_bool(data.get("paid_now")) or method == "CASH"
    ts = now_str()
    provider = {}
    if method == "CASH":
        provider = {"cash_received": data.get("cash_received"), "change": data.get("change")}
    with db.tx() as cur:
        pid = cur.insert(
            "INSERT INTO payments (order_id, order_code, user_id, amount, method, status, provider_data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)",
            (order_id, data.get("order_code") or str(order_id), data.get("user_id"), amount, method,
             json.dumps(provider, ensure_ascii=False) if provider else None, ts, ts))
        log_action(cur, pid, "CREATED", f"Tạo giao dịch {METHODS[method]}", data.get("by") or "order-service")
    if paid_now:
        mark_paid(pid, data.get("by") or "POS", f"Thanh toán tại quầy: {METHODS[method]}")
    return view(get_payment(pid)), 201


@app.post("/internal/payments/order/<int:order_id>/mark-paid")
@internal_only
def internal_mark_paid(order_id):
    """Đánh dấu đã thu tiền (COD khi giao hàng)"""
    row = db.query_one("SELECT * FROM payments WHERE order_id = ?", (order_id,))
    if not row:
        raise not_found("Không tìm thấy giao dịch của đơn hàng")
    data = get_json(required=False)
    return view(mark_paid(row["id"], data.get("by") or "order-service", data.get("note") or "Thu tiền khi giao hàng (COD)"))


@app.post("/internal/payments/order/<int:order_id>/cancel")
@internal_only
def internal_cancel(order_id):
    """Compensation: hủy giao dịch đang chờ, hoặc hoàn tiền nếu đã thanh toán."""
    data = get_json(required=False)
    reason = clean_str(data.get("reason"), 255) or "Đơn hàng bị hủy"
    ts = now_str()
    event = None
    with db.tx() as cur:
        row = cur.one("SELECT * FROM payments WHERE order_id = ?", (order_id,))
        if not row:
            return {"status": "NO_PAYMENT"}
        if row["status"] == "PENDING":
            cur.execute("UPDATE payments SET status = 'CANCELLED', note = ?, updated_at = ? WHERE id = ?", (reason, ts, row["id"]))
            log_action(cur, row["id"], "CANCELLED", reason, data.get("by") or "order-service")
        elif row["status"] == "PAID":
            cur.execute("UPDATE payments SET status = 'REFUNDED', refunded_at = ?, note = ?, updated_at = ? WHERE id = ?",
                        (ts, reason, ts, row["id"]))
            log_action(cur, row["id"], "REFUNDED", f"Hoàn tiền: {reason}", data.get("by") or "order-service")
            event = {"payment_id": row["id"], "order_id": order_id, "order_code": row["order_code"],
                     "user_id": row["user_id"], "amount": row["amount"], "method": row["method"]}
        row = cur.one("SELECT * FROM payments WHERE id = ?", (row["id"],))
    if event:
        bus.publish("payment.refunded", event)
    return view(row)


@app.get("/internal/payments/order/<int:order_id>")
@internal_only
def internal_get_by_order(order_id):
    """Lấy giao dịch theo đơn hàng"""
    row = db.query_one("SELECT * FROM payments WHERE order_id = ?", (order_id,))
    if not row:
        raise not_found("Không tìm thấy giao dịch")
    return view(row)


def create_app():
    db.init_schema(SCHEMA)
    bus.init_app(app)
    register_service(app, "payment", 8006)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8006)
