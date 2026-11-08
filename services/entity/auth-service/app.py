"""auth-service: đăng ký, đăng nhập (JWT), hồ sơ, sổ địa chỉ, quản lý người dùng & phân quyền."""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if os.path.isdir(os.path.join(ROOT, "common")) and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import request  # noqa: E402
from werkzeug.security import check_password_hash, generate_password_hash  # noqa: E402

from common.app_factory import create_base_app, register_service, run_dev  # noqa: E402
from common.auth import ROLES, create_token, current_user, internal_only, require_admin, require_auth, require_staff  # noqa: E402
from common.db import Database  # noqa: E402
from common.errors import ApiError, bad_request, conflict, not_found  # noqa: E402
from common.events import EventBus  # noqa: E402
from common.utils import clean_str, get_json, id_list, now_str, paged, pagination, parse_bool, require_fields  # noqa: E402

SERVICE = "auth-service"
db = Database(default_sqlite="data/auth.db")
bus = EventBus(SERVICE, db)
app = create_base_app(SERVICE, db, layer="entity",
                      description="Quản lý người dùng, xác thực JWT, sổ địa chỉ và phân quyền")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    phone TEXT,
    role TEXT NOT NULL DEFAULT 'customer',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    address_line TEXT NOT NULL,
    ward TEXT,
    district TEXT,
    city TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_addresses_user ON addresses(user_id)
"""

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^(0|\+84)\d{9,10}$")
PUBLIC_FIELDS = "id, email, full_name, phone, role, is_active, created_at, updated_at, last_login_at"


def public_user(row):
    if not row:
        return None
    row = dict(row)
    row.pop("password_hash", None)
    row["is_active"] = bool(row.get("is_active"))
    return row


def validate_email(email):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise bad_request("Email không hợp lệ")
    return email


def validate_phone(phone, required=False):
    phone = clean_str(phone, 20)
    if not phone:
        if required:
            raise bad_request("Thiếu số điện thoại")
        return None
    phone = phone.replace(" ", "").replace(".", "")
    if not PHONE_RE.match(phone):
        raise bad_request("Số điện thoại không hợp lệ (VD: 0912345678)")
    return phone


def validate_password(password):
    if not password or len(password) < 6:
        raise bad_request("Mật khẩu phải có ít nhất 6 ký tự")
    return password


def get_user(user_id):
    return db.query_one(f"SELECT {PUBLIC_FIELDS} FROM users WHERE id = ?", (user_id,))


def create_user(email, password, full_name, phone=None, role="customer"):
    ts = now_str()
    with db.tx() as cur:
        if cur.one("SELECT id FROM users WHERE email = ?", (email,)):
            raise conflict("Email đã được sử dụng")
        user_id = cur.insert(
            "INSERT INTO users (email, password_hash, full_name, phone, role, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (email, generate_password_hash(password), full_name, phone, role, ts, ts),
        )
    return get_user(user_id)


# =================================================================== AUTH
@app.post("/api/auth/register")
def register():
    """Đăng ký tài khoản khách hàng, trả về JWT"""
    data = get_json()
    require_fields(data, ["email", "password", "full_name"])
    email = validate_email(data["email"])
    password = validate_password(data["password"])
    full_name = clean_str(data["full_name"], 100)
    phone = validate_phone(data.get("phone"))
    user = create_user(email, password, full_name, phone, "customer")
    bus.publish("user.registered", {"user_id": user["id"], "email": email, "full_name": full_name})
    token = create_token(user)
    return {"token": token, "user": public_user(user)}, 201


@app.post("/api/auth/login")
def login():
    """Đăng nhập bằng email và mật khẩu, trả về JWT"""
    data = get_json()
    require_fields(data, ["email", "password"])
    email = (data["email"] or "").strip().lower()
    row = db.query_one("SELECT * FROM users WHERE email = ?", (email,))
    if not row or not check_password_hash(row["password_hash"], data["password"]):
        raise ApiError(401, "Email hoặc mật khẩu không đúng", code="INVALID_CREDENTIALS")
    if not row["is_active"]:
        raise ApiError(403, "Tài khoản đã bị khóa, vui lòng liên hệ cửa hàng", code="ACCOUNT_LOCKED")
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_str(), row["id"]))
    user = get_user(row["id"])
    return {"token": create_token(user), "user": public_user(user)}


@app.get("/api/auth/me")
@require_auth
def me():
    """Xem hồ sơ người dùng hiện tại"""
    user = get_user(current_user()["id"])
    if not user:
        raise not_found("Không tìm thấy tài khoản")
    return public_user(user)


@app.put("/api/auth/me")
@require_auth
def update_me():
    """Cập nhật họ tên, số điện thoại (trả về token mới)"""
    data = get_json()
    uid = current_user()["id"]
    fields, params = [], []
    if "full_name" in data:
        name = clean_str(data["full_name"], 100)
        if not name:
            raise bad_request("Họ tên không được để trống")
        fields.append("full_name = ?")
        params.append(name)
    if "phone" in data:
        fields.append("phone = ?")
        params.append(validate_phone(data["phone"]))
    if fields:
        fields.append("updated_at = ?")
        params += [now_str(), uid]
        db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
    user = get_user(uid)
    # trả token mới vì tên người dùng nằm trong token
    return {"user": public_user(user), "token": create_token(user)}


@app.put("/api/auth/change-password")
@require_auth
def change_password():
    """Đổi mật khẩu"""
    data = get_json()
    require_fields(data, ["old_password", "new_password"])
    uid = current_user()["id"]
    row = db.query_one("SELECT password_hash FROM users WHERE id = ?", (uid,))
    if not row or not check_password_hash(row["password_hash"], data["old_password"]):
        raise bad_request("Mật khẩu hiện tại không đúng")
    validate_password(data["new_password"])
    db.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
               (generate_password_hash(data["new_password"]), now_str(), uid))
    return {"message": "Đổi mật khẩu thành công"}


# =================================================================== ĐỊA CHỈ
def _address_payload(data, partial=False):
    if not partial:
        require_fields(data, ["recipient_name", "phone", "address_line"])
    payload = {}
    for key, size in (("recipient_name", 100), ("address_line", 255), ("ward", 100), ("district", 100), ("city", 100)):
        if key in data:
            payload[key] = clean_str(data[key], size)
    if "phone" in data:
        payload["phone"] = validate_phone(data["phone"], required=True)
    if "is_default" in data:
        payload["is_default"] = 1 if parse_bool(data["is_default"]) else 0
    return payload


@app.get("/api/users/me/addresses")
@require_auth
def list_addresses():
    """Danh sách địa chỉ giao hàng của tôi"""
    return {"items": db.query("SELECT * FROM addresses WHERE user_id = ? ORDER BY is_default DESC, id DESC",
                              (current_user()["id"],))}


@app.post("/api/users/me/addresses")
@require_auth
def add_address():
    """Thêm địa chỉ giao hàng"""
    uid = current_user()["id"]
    p = _address_payload(get_json())
    with db.tx() as cur:
        count = cur.scalar("SELECT COUNT(*) AS n FROM addresses WHERE user_id = ?", (uid,))
        is_default = 1 if (p.get("is_default") or count == 0) else 0
        if is_default:
            cur.execute("UPDATE addresses SET is_default = 0 WHERE user_id = ?", (uid,))
        addr_id = cur.insert(
            "INSERT INTO addresses (user_id, recipient_name, phone, address_line, ward, district, city, is_default, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, p["recipient_name"], p["phone"], p["address_line"], p.get("ward"), p.get("district"),
             p.get("city"), is_default, now_str()),
        )
    return db.query_one("SELECT * FROM addresses WHERE id = ?", (addr_id,)), 201


@app.put("/api/users/me/addresses/<int:addr_id>")
@require_auth
def update_address(addr_id):
    """Sửa địa chỉ giao hàng"""
    uid = current_user()["id"]
    p = _address_payload(get_json(), partial=True)
    with db.tx() as cur:
        if not cur.one("SELECT id FROM addresses WHERE id = ? AND user_id = ?", (addr_id, uid)):
            raise not_found("Không tìm thấy địa chỉ")
        if p.get("is_default"):
            cur.execute("UPDATE addresses SET is_default = 0 WHERE user_id = ?", (uid,))
        if p:
            sets = ", ".join(f"{k} = ?" for k in p)
            cur.execute(f"UPDATE addresses SET {sets} WHERE id = ?", list(p.values()) + [addr_id])
    return db.query_one("SELECT * FROM addresses WHERE id = ?", (addr_id,))


@app.delete("/api/users/me/addresses/<int:addr_id>")
@require_auth
def delete_address(addr_id):
    """Xóa địa chỉ giao hàng"""
    uid = current_user()["id"]
    with db.tx() as cur:
        row = cur.one("SELECT * FROM addresses WHERE id = ? AND user_id = ?", (addr_id, uid))
        if not row:
            raise not_found("Không tìm thấy địa chỉ")
        cur.execute("DELETE FROM addresses WHERE id = ?", (addr_id,))
        if row["is_default"]:
            nxt = cur.one("SELECT id FROM addresses WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
            if nxt:
                cur.execute("UPDATE addresses SET is_default = 1 WHERE id = ?", (nxt["id"],))
    return {"message": "Đã xóa địa chỉ"}


# =================================================================== QUẢN TRỊ
@app.get("/api/users")
@require_staff
def list_users():
    """Danh sách người dùng (tìm kiếm, lọc vai trò)"""
    page, size, offset = pagination()
    where, params = ["1 = 1"], []
    q = clean_str(request.args.get("q"))
    if q:
        where.append("(LOWER(email) LIKE ? OR LOWER(full_name) LIKE ? OR phone LIKE ?)")
        like = f"%{q.lower()}%"
        params += [like, like, like]
    role = request.args.get("role")
    if role:
        where.append("role = ?")
        params.append(role)
    cond = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) AS n FROM users WHERE {cond}", params)
    rows = db.query(f"SELECT {PUBLIC_FIELDS} FROM users WHERE {cond} ORDER BY id DESC LIMIT ? OFFSET ?",
                    params + [size, offset])
    return paged([public_user(r) for r in rows], total, page, size)


@app.post("/api/users")
@require_admin
def admin_create_user():
    """Tạo tài khoản nhân viên / quản trị"""
    data = get_json()
    require_fields(data, ["email", "password", "full_name"])
    role = data.get("role", "staff")
    if role not in ROLES:
        raise bad_request("Vai trò không hợp lệ")
    user = create_user(validate_email(data["email"]), validate_password(data["password"]),
                       clean_str(data["full_name"], 100), validate_phone(data.get("phone")), role)
    return public_user(user), 201


@app.get("/api/users/<int:user_id>")
@require_staff
def admin_get_user(user_id):
    """Chi tiết người dùng kèm địa chỉ"""
    user = get_user(user_id)
    if not user:
        raise not_found("Không tìm thấy người dùng")
    result = public_user(user)
    result["addresses"] = db.query("SELECT * FROM addresses WHERE user_id = ? ORDER BY is_default DESC", (user_id,))
    return result


@app.put("/api/users/<int:user_id>")
@require_admin
def admin_update_user(user_id):
    """Đổi vai trò, khóa tài khoản, đặt lại mật khẩu"""
    data = get_json()
    me_ = current_user()
    if not get_user(user_id):
        raise not_found("Không tìm thấy người dùng")
    fields, params = [], []
    if "role" in data:
        if data["role"] not in ROLES:
            raise bad_request("Vai trò không hợp lệ")
        if user_id == me_["id"] and data["role"] != "admin":
            raise bad_request("Không thể tự hạ quyền admin của chính mình")
        fields.append("role = ?")
        params.append(data["role"])
    if "is_active" in data:
        active = 1 if parse_bool(data["is_active"]) else 0
        if user_id == me_["id"] and not active:
            raise bad_request("Không thể tự khóa tài khoản của chính mình")
        fields.append("is_active = ?")
        params.append(active)
    if "full_name" in data:
        fields.append("full_name = ?")
        params.append(clean_str(data["full_name"], 100))
    if "phone" in data:
        fields.append("phone = ?")
        params.append(validate_phone(data["phone"]))
    if data.get("password"):
        fields.append("password_hash = ?")
        params.append(generate_password_hash(validate_password(data["password"])))
    if fields:
        fields.append("updated_at = ?")
        params += [now_str(), user_id]
        db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params)
    return public_user(get_user(user_id))


# =================================================================== NỘI BỘ
@app.get("/internal/users/<int:user_id>")
@internal_only
def internal_get_user(user_id):
    """Lấy thông tin người dùng theo id"""
    user = get_user(user_id)
    if not user:
        raise not_found("Không tìm thấy người dùng")
    return public_user(user)


@app.get("/internal/users/<int:user_id>/addresses/<int:addr_id>")
@internal_only
def internal_get_address(user_id, addr_id):
    """Lấy một địa chỉ giao hàng của người dùng"""
    row = db.query_one("SELECT * FROM addresses WHERE id = ? AND user_id = ?", (addr_id, user_id))
    if not row:
        raise not_found("Không tìm thấy địa chỉ giao hàng")
    return row


@app.get("/internal/users")
@internal_only
def internal_users():
    """Lấy nhiều người dùng theo danh sách id"""
    ids = id_list(request.args.get("ids"))
    if not ids:
        return {"items": []}
    marks = ",".join("?" * len(ids))
    return {"items": [public_user(r) for r in db.query(f"SELECT {PUBLIC_FIELDS} FROM users WHERE id IN ({marks})", ids)]}


@app.get("/internal/users/stats")
@internal_only
def internal_stats():
    """Thống kê số người dùng theo vai trò"""
    rows = db.query("SELECT role, COUNT(*) AS n FROM users GROUP BY role")
    by_role = {r["role"]: r["n"] for r in rows}
    today = now_str()[:10]
    new_today = db.scalar("SELECT COUNT(*) AS n FROM users WHERE created_at >= ?", (today + " 00:00:00",))
    return {"total": sum(by_role.values()), "by_role": by_role, "new_today": new_today}


# =================================================================== KHỞI TẠO
def seed():
    if not db.is_empty("users"):
        return
    demo = [
        ("admin@taphoa.vn", "Admin@123", "Quản trị viên", "0900000001", "admin"),
        ("staff@taphoa.vn", "Staff@123", "Nhân viên bán hàng", "0900000002", "staff"),
        ("khach@taphoa.vn", "Khach@123", "Nguyễn Văn Khách", "0912345678", "customer"),
    ]
    hashed = [(e, generate_password_hash(pw), n, ph, r) for e, pw, n, ph, r in demo]
    ts = now_str()
    with db.tx() as cur:
        cur.lock("seed")
        if cur.scalar("SELECT COUNT(*) AS n FROM users"):  # instance khác đã seed
            return
        ids = {}
        for email, pw_hash, name, phone, role in hashed:
            ids[email] = cur.insert(
                "INSERT INTO users (email, password_hash, full_name, phone, role, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)", (email, pw_hash, name, phone, role, ts, ts))
        cur.insert(
            "INSERT INTO addresses (user_id, recipient_name, phone, address_line, ward, district, city, is_default, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (ids["khach@taphoa.vn"], "Nguyễn Văn Khách", "0912345678", "97 Man Thiện", "Phường Hiệp Phú", "TP. Thủ Đức",
             "TP. Hồ Chí Minh", ts))
    app.logger.info("Đã tạo tài khoản demo")


def create_app():
    db.init_schema(SCHEMA)
    seed()
    bus.init_app(app)
    register_service(app, "auth", 8001)
    return app


if __name__ == "__main__":
    run_dev(create_app(), 8001)
