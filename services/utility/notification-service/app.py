"""notification-service: lắng nghe sự kiện từ các service khác để tạo thông báo trong app và email (mô phỏng).

Đây là consumer thuần túy của Event Bus - không service nào gọi đồng bộ tới nó,
nên nếu notification-service tạm dừng, việc đặt hàng vẫn hoạt động bình thường
và thông báo sẽ được xử lý bù khi service chạy lại (message nằm chờ trong queue).
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import request  # noqa: E402

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import current_user, is_staff, require_admin, require_auth  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.utils import now_str, paged, pagination, parse_bool  # noqa: E402

SERVICE = "notification-service"
db = Database(default_sqlite="data/notification.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="utility",
                      description="Thông báo trong ứng dụng và email, chỉ lắng nghe sự kiện")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    target_role TEXT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE TABLE IF NOT EXISTS notification_reads (
    notification_id INTEGER NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    read_at TEXT NOT NULL,
    PRIMARY KEY (notification_id, user_id)
);
CREATE TABLE IF NOT EXISTS email_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    event_type TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

READ_FLAG = "CASE WHEN n.user_id IS NOT NULL THEN n.is_read WHEN r.user_id IS NOT NULL THEN 1 ELSE 0 END"


def money(v):
    return f"{int(v or 0):,}đ".replace(",", ".")


def notify_user(user_id, ntype, title, message, link=None):
    if not user_id:
        return
    db.execute("INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
               (int(user_id), ntype, title, message, link, now_str()))


def notify_staff(ntype, title, message, link=None):
    db.execute("INSERT INTO notifications (target_role, type, title, message, link, is_read, created_at) "
               "VALUES ('staff', ?, ?, ?, ?, 0, ?)", (ntype, title, message, link, now_str()))


def send_email(to, subject, body, event_type):
    """Mô phỏng gửi email: ghi vào email_logs (thay bằng SMTP/SendGrid khi triển khai thật)."""
    if not to:
        return
    db.execute("INSERT INTO email_logs (to_email, subject, body, event_type, status, created_at) VALUES (?, ?, ?, ?, 'SENT', ?)",
               (to, subject, body, event_type, now_str()))
    app.logger.info("[EMAIL] to=%s subject=%s", to, subject)


# =================================================================== XỬ LÝ SỰ KIỆN
@bus.on("user.registered")
def on_user_registered(d, e):
    notify_user(d["user_id"], "WELCOME", "Chào mừng bạn đến Tạp Hóa Xanh!",
                "Nhập mã WELCOME10 để được giảm 10% cho đơn hàng đầu tiên.", "/")
    send_email(d.get("email"), "Chào mừng bạn đến với Tạp Hóa Xanh",
               f"Xin chào {d.get('full_name')},\n\nCảm ơn bạn đã đăng ký tài khoản. Tặng bạn mã WELCOME10 giảm 10% cho đơn đầu tiên.",
               e["type"])


@bus.on("order.created")
def on_order_created(d, e):
    if d.get("channel") == "POS":
        return
    link = f"/orders.html?id={d['order_id']}"
    notify_user(d.get("user_id"), "ORDER", f"Đặt hàng thành công #{d['code']}",
                f"Đơn hàng {money(d['total'])} đã được ghi nhận và đang chờ xác nhận.", link)
    lines = "\n".join(f"- {i['product_name']} x{i['quantity']}" for i in d.get("items", []))
    send_email(d.get("customer_email"), f"[Tạp Hóa Xanh] Xác nhận đơn hàng #{d['code']}",
               f"Xin chào {d.get('customer_name')},\n\nĐơn hàng #{d['code']} của bạn:\n{lines}\n\nTổng thanh toán: {money(d['total'])}",
               e["type"])
    notify_staff("NEW_ORDER", f"Đơn hàng mới #{d['code']}",
                 f"{d.get('customer_name')} vừa đặt đơn {money(d['total'])} ({d.get('payment_method')}).", "/admin/#orders")


@bus.on("order.status_changed")
def on_order_status(d, e):
    if d.get("channel") == "POS":
        return
    label = d.get("status_label") or d.get("new_status")
    notify_user(d.get("user_id"), "ORDER", f"Đơn hàng #{d['code']}: {label}",
                d.get("note") or f"Đơn hàng của bạn đã chuyển sang trạng thái '{label}'.", f"/orders.html?id={d['order_id']}")
    if d.get("new_status") in ("SHIPPING", "DELIVERED"):
        send_email(d.get("customer_email"), f"[Tạp Hóa Xanh] Đơn hàng #{d['code']} {label.lower()}",
                   f"Đơn hàng #{d['code']} đã chuyển sang trạng thái: {label}.", e["type"])


@bus.on("order.cancelled")
def on_order_cancelled(d, e):
    refund = " Tiền đã thanh toán sẽ được hoàn lại." if d.get("refunded") else ""
    notify_user(d.get("user_id"), "ORDER", f"Đơn hàng #{d['code']} đã bị hủy",
                f"Lý do: {d.get('reason')}.{refund}", f"/orders.html?id={d['order_id']}")
    send_email(d.get("customer_email"), f"[Tạp Hóa Xanh] Đơn hàng #{d['code']} đã bị hủy",
               f"Đơn hàng #{d['code']} đã bị hủy. Lý do: {d.get('reason')}.{refund}", e["type"])
    notify_staff("ORDER_CANCELLED", f"Đơn #{d['code']} đã hủy", f"Hủy bởi {d.get('cancelled_by')}: {d.get('reason')}",
                 "/admin/#orders")


@bus.on("payment.completed")
def on_payment_completed(d, e):
    if d.get("method") in ("CASH", "CARD") or not d.get("user_id"):
        return
    notify_user(d["user_id"], "PAYMENT", f"Thanh toán thành công #{d['order_code']}",
                f"Đã nhận {money(d['amount'])}. Mã giao dịch {d.get('transaction_ref')}.", f"/orders.html?id={d['order_id']}")
    if d.get("method") in ("BANK_TRANSFER", "EWALLET"):
        notify_staff("PAYMENT", f"Đã nhận thanh toán #{d['order_code']}", f"{money(d['amount'])} qua {d['method']}",
                     "/admin/#payments")


@bus.on("payment.failed")
def on_payment_failed(d, e):
    notify_user(d.get("user_id"), "PAYMENT", f"Thanh toán chưa thành công #{d['order_code']}",
                "Giao dịch không thành công. Bạn có thể thử thanh toán lại trong mục Đơn hàng.", f"/orders.html?id={d['order_id']}")


@bus.on("payment.refunded")
def on_payment_refunded(d, e):
    notify_user(d.get("user_id"), "PAYMENT", f"Hoàn tiền đơn #{d['order_code']}",
                f"Đã hoàn {money(d['amount'])} về phương thức thanh toán ban đầu.", f"/orders.html?id={d['order_id']}")


@bus.on("inventory.low_stock")
def on_low_stock(d, e):
    status = "đã HẾT HÀNG" if d.get("available", 0) <= 0 else f"chỉ còn {d.get('available')}"
    notify_staff("LOW_STOCK", f"Cảnh báo tồn kho: {d.get('product_name')}",
                 f"{d.get('product_name')} ({d.get('sku')}) {status} (ngưỡng {d.get('min_quantity')}). Cần nhập thêm hàng.",
                 "/admin/#inventory")


# =================================================================== API
def _scope(user):
    return "(n.user_id = ? OR (n.target_role = 'staff' AND ? = 1))", [user["id"], 1 if is_staff(user) else 0]


@app.get("/api/notifications")
@require_auth
def list_notifications():
    """Thông báo của tôi (nhân viên thấy thêm thông báo chung)"""
    user = current_user()
    page, size, offset = pagination(default_size=15)
    scope, params = _scope(user)
    where = scope
    if parse_bool(request.args.get("unread")):
        where += f" AND {READ_FLAG} = 0"
    base = f"FROM notifications n LEFT JOIN notification_reads r ON r.notification_id = n.id AND r.user_id = ? WHERE {where}"
    all_params = [user["id"]] + params
    total = db.scalar(f"SELECT COUNT(*) AS n {base}", all_params)
    rows = db.query(f"SELECT n.*, {READ_FLAG} AS read_flag {base} ORDER BY n.id DESC LIMIT ? OFFSET ?",
                    all_params + [size, offset])
    for r in rows:
        r["is_read"] = bool(r.pop("read_flag"))
    result = paged(rows, total, page, size)
    result["unread"] = _unread_count(user)
    return result


def _unread_count(user):
    scope, params = _scope(user)
    return db.scalar(
        f"SELECT COUNT(*) AS n FROM notifications n LEFT JOIN notification_reads r ON r.notification_id = n.id AND r.user_id = ? "
        f"WHERE {scope} AND {READ_FLAG} = 0", [user["id"]] + params)


@app.get("/api/notifications/unread-count")
@require_auth
def unread_count():
    """Số thông báo chưa đọc"""
    return {"unread": _unread_count(current_user())}


def _mark_read(cur, user, row):
    if row["user_id"] is not None:
        cur.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (row["id"],))
    elif not cur.one("SELECT notification_id FROM notification_reads WHERE notification_id = ? AND user_id = ?",
                     (row["id"], user["id"])):
        cur.execute("INSERT INTO notification_reads (notification_id, user_id, read_at) VALUES (?, ?, ?)",
                    (row["id"], user["id"], now_str()))


@app.put("/api/notifications/<int:nid>/read")
@require_auth
def mark_read(nid):
    """Đánh dấu một thông báo đã đọc"""
    user = current_user()
    scope, params = _scope(user)
    with db.tx() as cur:
        row = cur.one(f"SELECT n.* FROM notifications n WHERE n.id = ? AND {scope}", [nid] + params)
        if not row:
            raise not_found("Không tìm thấy thông báo")
        _mark_read(cur, user, row)
    return {"unread": _unread_count(user)}


@app.put("/api/notifications/read-all")
@require_auth
def mark_all_read():
    """Đánh dấu đã đọc tất cả"""
    user = current_user()
    scope, params = _scope(user)
    with db.tx() as cur:
        rows = cur.all(
            f"SELECT n.* FROM notifications n LEFT JOIN notification_reads r ON r.notification_id = n.id AND r.user_id = ? "
            f"WHERE {scope} AND {READ_FLAG} = 0", [user["id"]] + params)
        for row in rows:
            _mark_read(cur, user, row)
    return {"unread": 0, "marked": len(rows)}


@app.get("/api/notifications/emails")
@require_admin
def email_logs():
    """Nhật ký email đã gửi (mô phỏng)"""
    page, size, offset = pagination(default_size=20)
    total = db.scalar("SELECT COUNT(*) AS n FROM email_logs")
    rows = db.query("SELECT * FROM email_logs ORDER BY id DESC LIMIT ? OFFSET ?", (size, offset))
    return paged(rows, total, page, size)


def create_app():
    db.init_schema(SCHEMA)
    bus.init_app(app)
    register_service(app, "notification", 8008)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8008)
