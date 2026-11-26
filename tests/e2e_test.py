"""Kiểm thử end-to-end toàn hệ thống qua API Gateway.

Chạy sau khi hệ thống đã khởi động (Docker hoặc run_local.py) trên CSDL MỚI (run_local.py --reset hoặc docker compose down -v):
bộ test đặt hàng, nhập kho, hủy đơn... làm thay đổi tồn kho và lượt dùng mã, nên chạy lần hai trên cùng dữ liệu có thể sai vài kiểm tra.
    python tests/e2e_test.py                       # mặc định http://localhost:8000
    GATEWAY_URL=http://localhost:8000 python tests/e2e_test.py
"""
import os
import sys
import time
import traceback

import requests

BASE = os.environ.get("GATEWAY_URL", "http://localhost:8000").rstrip("/")
RESULTS = []
S = requests.Session()


class Client:
    def __init__(self, token=None):
        self.token = token

    def req(self, method, path, **kw):
        headers = kw.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        r = S.request(method, BASE + path, headers=headers, timeout=30, **kw)
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text}
        return r.status_code, body

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, json=None, **kw):
        return self.req("POST", path, json=json, **kw)

    def put(self, path, json=None, **kw):
        return self.req("PUT", path, json=json, **kw)

    def delete(self, path, **kw):
        return self.req("DELETE", path, **kw)


def check(cond, name, info=None):
    RESULTS.append((bool(cond), name))
    mark = "\033[32mPASS\033[0m" if cond else "\033[31mFAIL\033[0m"
    print(f"  [{mark}] {name}" + ("" if cond or info is None else f"  -> {str(info)[:300]}"))
    return cond


def expect(status_body, code, name):
    status, body = status_body
    check(status == code, f"{name} (HTTP {code})", f"got {status}: {body}")
    return body


def wait_for(fn, timeout=15, interval=0.4):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = fn()
            if value:
                return value
        except Exception:
            pass
        time.sleep(interval)
    return None


def login(email, password):
    status, body = Client().post("/api/auth/login", {"email": email, "password": password})
    assert status == 200, body
    return Client(body["token"]), body["user"]


def section(title):
    print(f"\n== {title}")


def main():
    anon = Client()
    stamp = str(int(time.time() * 1000))[-8:]

    section("Hạ tầng & bảo mật")
    status, health = anon.get("/api/health")
    check(status == 200 and health["status"] == "UP", "Tất cả service đều UP", health)
    expect(anon.get("/api/cart"), 401, "Chưa đăng nhập không xem được giỏ hàng")
    expect(Client("abc.def.ghi").get("/api/products"), 401, "Token sai bị từ chối kể cả route công khai")
    expect(anon.get("/api/khong-ton-tai"), 404, "Route không tồn tại trả 404")
    try:
        r = requests.post("http://127.0.0.1:8003/internal/inventory/reserve", json={"order_id": 1, "items": []}, timeout=3)
        check(r.status_code == 403, "Gọi thẳng endpoint nội bộ không có token bị chặn (403)", r.text)
        r = requests.get("http://127.0.0.1:8001/api/auth/me", headers={"X-User-Id": "1", "X-User-Role": "admin"}, timeout=3)
        check(r.status_code == 401, "Giả mạo header X-User-* khi bỏ qua gateway không có tác dụng", r.text)
    except requests.RequestException:
        print("  (bỏ qua kiểm tra gọi thẳng service - service không mở cổng ra ngoài, đúng với Docker)")

    section("Danh mục & sản phẩm")
    cats = expect(anon.get("/api/categories"), 200, "Lấy danh mục")["items"]
    check(len(cats) >= 10 and cats[0]["product_count"] > 0, "Có danh mục và đếm sản phẩm", cats[:1])
    page = expect(anon.get("/api/products", params={"page_size": 5}), 200, "Danh sách sản phẩm")
    check(page["total"] >= 50 and len(page["items"]) == 5 and page["stock_available"], "Phân trang + có tồn kho", page["total"])
    res = expect(anon.get("/api/products", params={"q": "gao st25"}), 200, "Tìm kiếm không dấu")
    check(any("ST25" in p["name"] for p in res["items"]), "Tìm 'gao st25' ra 'Gạo ST25'", [p["name"] for p in res["items"]])
    res = expect(anon.get("/api/products", params={"sort": "price_asc", "category_id": 6, "page_size": 50}), 200, "Lọc + sắp xếp")
    prices = [p["final_price"] for p in res["items"]]
    check(prices == sorted(prices) and all(p["category_id"] == 6 for p in res["items"]), "Sắp xếp giá tăng dần trong danh mục", prices)
    res = expect(anon.get("/api/products", params={"on_sale": 1, "page_size": 50}), 200, "Lọc đang khuyến mãi")
    check(all(p["sale_price"] and p["discount_percent"] > 0 for p in res["items"]), "Chỉ sản phẩm có giá KM")
    p1 = expect(anon.get("/api/products/1"), 200, "Chi tiết sản phẩm")
    check(p1["available"] > 0 and len(p1["related"]) > 0 and p1["final_price"] == 179000, "Có tồn kho, giá KM, gợi ý liên quan", p1)
    expect(anon.get("/api/products/99999"), 404, "Sản phẩm không tồn tại")

    section("Tài khoản khách hàng")
    email = f"test{stamp}@example.com"
    reg = expect(anon.post("/api/auth/register", {"email": email, "password": "Test@123", "full_name": "Trần Thị Test",
                                                    "phone": "0987654321"}), 201, "Đăng ký")
    expect(anon.post("/api/auth/register", {"email": email, "password": "Test@123", "full_name": "X"}), 409, "Email trùng")
    expect(anon.post("/api/auth/register", {"email": "sai-email", "password": "1", "full_name": "X"}), 400, "Dữ liệu sai")
    expect(anon.post("/api/auth/login", {"email": email, "password": "sai"}), 401, "Sai mật khẩu")
    cust, cust_user = login(email, "Test@123")
    check(cust_user["role"] == "customer" and reg["user"]["id"] == cust_user["id"], "Đăng nhập lấy JWT, vai trò customer")
    me = expect(cust.get("/api/auth/me"), 200, "Xem hồ sơ")
    check(me["full_name"] == "Trần Thị Test", "Tên tiếng Việt có dấu đi qua gateway đúng", me)
    upd = expect(cust.put("/api/auth/me", {"full_name": "Trần Thị Kiểm Thử"}), 200, "Cập nhật hồ sơ")
    cust = Client(upd["token"])
    addr = expect(cust.post("/api/users/me/addresses", {"recipient_name": "Trần Thị Kiểm Thử", "phone": "0987654321",
                                                         "address_line": "1 Võ Văn Ngân", "district": "TP. Thủ Đức",
                                                         "city": "TP. Hồ Chí Minh"}), 201, "Thêm địa chỉ")
    check(addr["is_default"] == 1, "Địa chỉ đầu tiên là mặc định")
    expect(cust.put("/api/auth/change-password", {"old_password": "sai", "new_password": "Moi@1234"}), 400, "Đổi mật khẩu sai mật khẩu cũ")
    expect(cust.get("/api/orders"), 403, "Khách không xem được danh sách đơn của cửa hàng")
    welcome = wait_for(lambda: [n for n in cust.get("/api/notifications")[1]["items"] if n["type"] == "WELCOME"])
    check(welcome, "Sự kiện user.registered -> thông báo chào mừng")

    staff, _ = login("staff@taphoa.vn", "Staff@123")
    admin, _ = login("admin@taphoa.vn", "Admin@123")
    stock_before = expect(staff.get("/api/inventory/1"), 200, "Nhân viên xem tồn kho")

    section("Giỏ hàng")
    expect(cust.post("/api/cart/items", {"product_id": 1, "quantity": 2}), 201, "Thêm sản phẩm vào giỏ")
    cart = expect(cust.post("/api/cart/items", {"product_id": 7, "quantity": 10}), 201, "Thêm sản phẩm thứ 2")
    check(cart["item_count"] == 12 and cart["subtotal"] == 2 * 179000 + 10 * 4500, "Tính tạm tính theo giá hiện hành", cart)
    cart = expect(cust.put("/api/cart/items/7", {"quantity": 20}), 200, "Cập nhật số lượng")
    check(cart["subtotal"] == 2 * 179000 + 20 * 4500, "Tạm tính sau cập nhật")
    expect(cust.post("/api/cart/items", {"product_id": 23, "quantity": 1}), 409, "Không thêm được sản phẩm hết hàng")
    expect(cust.post("/api/cart/items", {"product_id": 5, "quantity": 50}), 409, "Không thêm vượt tồn kho")
    check(cust.get("/api/cart/count")[1]["count"] == 22, "Đếm số lượng trong giỏ")

    section("Mã giảm giá")
    coupons = expect(anon.get("/api/coupons/available"), 200, "Danh sách mã công khai")["items"]
    check(any(c["code"] == "WELCOME10" for c in coupons) and not any(c["code"] == "VIP15" for c in coupons), "Mã riêng tư bị ẩn")
    v = expect(cust.post("/api/coupons/validate", {"code": "welcome10", "subtotal": 448000}), 200, "Kiểm tra mã hợp lệ")
    check(v["discount"] == 30000, "Giảm 10% nhưng tối đa 30.000đ", v)
    expect(cust.post("/api/coupons/validate", {"code": "KHONGCO", "subtotal": 100000}), 400, "Mã không tồn tại")
    expect(cust.post("/api/coupons/validate", {"code": "SALE50K", "subtotal": 100000}), 400, "Chưa đạt giá trị tối thiểu")
    pv = expect(cust.post("/api/orders/preview", {"coupon_code": "WELCOME10"}), 200, "Xem trước đơn hàng")
    check(pv["subtotal"] == 448000 and pv["discount"] == 30000 and pv["shipping_fee"] == 0 and pv["total"] == 418000,
          "Tạm tính / giảm giá / miễn phí ship", pv)

    section("Đặt hàng online (Saga) - COD")
    order = expect(cust.post("/api/orders", {"address_id": addr["id"], "payment_method": "COD", "coupon_code": "WELCOME10",
                                             "note": "Giao giờ hành chính"}), 201, "Đặt hàng từ giỏ")
    check(order["total"] == 418000 and order["status"] == "PENDING" and len(order["items"]) == 2, "Đơn PENDING đúng tổng tiền", order)
    check(order["payment"]["status"] == "PENDING" and order["payment"]["method"] == "COD", "Tạo giao dịch COD chờ thanh toán")
    check(cust.get("/api/cart")[1]["item_count"] == 0, "Giỏ hàng được xóa sau khi đặt")
    s1 = staff.get("/api/inventory/1")[1]
    check(s1["reserved"] == stock_before["reserved"] + 2 and s1["quantity"] == stock_before["quantity"], "Kho giữ hàng (reserved +2)", s1)
    expect(cust.post("/api/coupons/validate", {"code": "WELCOME10", "subtotal": 448000}), 400, "Mã 1 lần/khách không dùng lại được")
    check(wait_for(lambda: [n for n in cust.get("/api/notifications")[1]["items"] if order["code"] in n["title"]]),
          "Sự kiện order.created -> thông báo khách")
    check(wait_for(lambda: [n for n in staff.get("/api/notifications")[1]["items"] if n["type"] == "NEW_ORDER"
                            and order["code"] in n["title"]]), "Nhân viên nhận thông báo đơn mới")

    section("Saga thất bại -> bù trừ")
    my_before = cust.get("/api/orders/my")[1]["total"]
    fail = expect(cust.post("/api/orders", {"items": [{"product_id": 1, "quantity": 1}, {"product_id": 23, "quantity": 2}],
                                            "shipping_address": {"recipient_name": "A", "phone": "0987654321", "address_line": "B"},
                                            "payment_method": "COD"}), 409, "Đặt sản phẩm hết hàng bị từ chối")
    check(fail["error"]["code"] == "OUT_OF_STOCK", "Mã lỗi OUT_OF_STOCK kèm chi tiết", fail)
    check(cust.get("/api/orders/my")[1]["total"] == my_before, "Không tạo đơn rác khi saga lỗi")
    check(staff.get("/api/inventory/1")[1]["reserved"] == s1["reserved"], "Không giữ hàng sót (rollback reserve)")
    expect(cust.post("/api/orders", {"items": [{"product_id": 2, "quantity": 1}], "payment_method": "COD",
                                     "shipping_address": {"recipient_name": "A", "phone": "0987654321", "address_line": "B"},
                                     "coupon_code": "SALE50K"}), 400, "Mã không đủ điều kiện -> không tạo đơn")

    section("Xử lý đơn hàng (nhân viên)")
    oid = order["id"]
    expect(staff.put(f"/api/orders/{oid}/status", {"status": "DELIVERED"}), 400, "Không cho nhảy trạng thái sai quy trình")
    expect(staff.put(f"/api/orders/{oid}/status", {"status": "CONFIRMED"}), 200, "Xác nhận đơn")
    expect(cust.post(f"/api/orders/{oid}/cancel", {"reason": "đổi ý"}), 400, "Khách không tự hủy đơn đã xác nhận")
    expect(staff.put(f"/api/orders/{oid}/status", {"status": "SHIPPING"}), 200, "Giao hàng -> xuất kho")
    s2 = staff.get("/api/inventory/1")[1]
    check(s2["quantity"] == stock_before["quantity"] - 2 and s2["reserved"] == stock_before["reserved"], "Xuất kho: quantity -2", s2)
    check(any(m["type"] == "SALE" and m["ref_id"] == order["code"] for m in s2["movements"]), "Ghi nhận lịch sử xuất kho")
    done = expect(staff.put(f"/api/orders/{oid}/status", {"status": "DELIVERED"}), 200, "Giao thành công")
    check(done["payment_status"] == "PAID" and len(done["history"]) == 4, "COD tự chuyển ĐÃ THANH TOÁN khi giao", done)
    pay = expect(cust.get(f"/api/payments/order/{oid}"), 200, "Khách xem giao dịch")
    check(pay["status"] == "PAID", "Giao dịch COD đã thanh toán")
    check(wait_for(lambda: anon.get("/api/products/1")[1]["sold_count"] >= 2), "Sự kiện order.completed -> tăng 'đã bán'")
    other = Client(login("khach@taphoa.vn", "Khach@123")[0].token)
    expect(other.get(f"/api/orders/{oid}"), 403, "Khách khác không xem được đơn")

    section("Đánh giá sản phẩm")
    expect(cust.post("/api/products/2/reviews", {"rating": 5, "comment": "ngon"}), 403, "Chưa mua thì không đánh giá được")
    expect(cust.post("/api/products/1/reviews", {"rating": 4, "comment": "Gạo dẻo thơm"}), 201, "Đánh giá sản phẩm đã mua")
    rv = expect(anon.get("/api/products/1/reviews"), 200, "Xem đánh giá")
    check(rv["total"] >= 1 and anon.get("/api/products/1")[1]["rating_count"] >= 1, "Cập nhật điểm trung bình")

    section("Thanh toán ví điện tử (event-driven)")
    o2 = expect(cust.post("/api/orders", {"items": [{"product_id": 12, "quantity": 2}], "payment_method": "EWALLET",
                                          "address_id": addr["id"]}), 201, "Đặt hàng thanh toán ví")
    check(o2["shipping_fee"] == 25000 and o2["total"] == 2 * 38000 + 25000, "Tính phí ship cho đơn nhỏ", o2)
    check(o2["payment"]["payment_url"].startswith("/pay.html"), "Trả về link cổng thanh toán")
    expect(cust.post(f"/api/payments/{o2['payment']['id']}/pay", {"success": False}), 402, "Mô phỏng thanh toán thất bại")
    expect(cust.post(f"/api/payments/{o2['payment']['id']}/pay", {"success": True}), 200, "Thanh toán thành công")
    o2d = wait_for(lambda: (lambda o: o if o["payment_status"] == "PAID" and o["status"] == "CONFIRMED" else None)(
        cust.get(f"/api/orders/{o2['id']}")[1]))
    check(o2d, "Sự kiện payment.completed -> đơn tự động xác nhận + đã thanh toán")
    c2 = expect(staff.put(f"/api/orders/{o2['id']}/status", {"status": "CANCELLED", "note": "Hết shipper khu vực"}), 200,
                "Cửa hàng hủy đơn đã thanh toán")
    check(c2["status"] == "CANCELLED" and c2["payment_status"] == "REFUNDED", "Hoàn tiền khi hủy đơn đã thanh toán", c2)
    check(wait_for(lambda: [n for n in cust.get("/api/notifications")[1]["items"] if "Hoàn tiền" in n["title"]]),
          "Thông báo hoàn tiền")

    section("Khách tự hủy đơn")
    s_before = staff.get("/api/inventory/3")[1]
    o3 = expect(cust.post("/api/orders", {"items": [{"product_id": 3, "quantity": 3}], "payment_method": "BANK_TRANSFER",
                                          "address_id": addr["id"]}), 201, "Đặt đơn chuyển khoản")
    check(o3["payment"]["instructions"]["content"] == o3["code"], "Có hướng dẫn chuyển khoản với nội dung = mã đơn")
    check(staff.get("/api/inventory/3")[1]["reserved"] == s_before["reserved"] + 3, "Giữ 3 sản phẩm")
    c3 = expect(cust.post(f"/api/orders/{o3['id']}/cancel", {"reason": "Đặt nhầm"}), 200, "Khách hủy đơn chờ xác nhận")
    check(c3["status"] == "CANCELLED", "Đơn đã hủy")
    check(staff.get("/api/inventory/3")[1]["reserved"] == s_before["reserved"], "Trả lại hàng đã giữ")
    check(cust.get(f"/api/payments/order/{o3['id']}")[1]["status"] == "CANCELLED", "Hủy giao dịch chờ thanh toán")

    section("Bán tại quầy (POS)")
    bc = expect(staff.get("/api/products/barcode/8930000000295"), 200, "Quét mã vạch")
    check(bc["sku"] == "COCA-LON", "Tìm đúng sản phẩm theo mã vạch")
    expect(cust.get("/api/products/barcode/8930000000295"), 403, "Khách không dùng được API POS")
    coca_before = staff.get(f"/api/inventory/{bc['id']}")[1]["quantity"]
    expect(staff.post("/api/pos/orders", {"items": [{"product_id": bc["id"], "quantity": 6}], "payment_method": "CASH",
                                         "cash_received": 10000}), 400, "Tiền khách đưa không đủ")
    pos = expect(staff.post("/api/pos/orders", {"items": [{"product_id": bc["id"], "quantity": 6}, {"product_id": 31, "quantity": 2}],
                                               "payment_method": "CASH", "cash_received": 100000}), 201, "Thanh toán tại quầy")
    check(pos["status"] == "COMPLETED" and pos["payment_status"] == "PAID" and pos["total"] == 70000 and pos["change_amount"] == 30000,
          "Hoàn tất ngay + tính tiền thối", pos)
    check(staff.get(f"/api/inventory/{bc['id']}")[1]["quantity"] == coca_before - 6, "Trừ kho ngay khi bán tại quầy")

    section("Kho hàng: nhập hàng, điều chỉnh, cảnh báo")
    sup = expect(staff.post("/api/suppliers", {"name": f"NCC Test {stamp}", "phone": "0281112222"}), 201, "Thêm nhà cung cấp")
    q5 = staff.get("/api/inventory/5")[1]
    rc = expect(staff.post("/api/stock-receipts", {"supplier_id": sup["id"], "note": "Nhập bổ sung",
                                                   "items": [{"product_id": 5, "quantity": 30, "unit_cost": 50000}]}), 201, "Tạo phiếu nhập")
    check(rc["total_cost"] == 1500000 and rc["code"].startswith("PN"), "Phiếu nhập tính tổng tiền", rc)
    check(staff.get("/api/inventory/5")[1]["quantity"] == q5["quantity"] + 30, "Nhập kho tăng tồn")
    q9 = staff.get("/api/inventory/9")[1]
    new_q9 = max(q9["reserved"], 3 if q9["quantity"] != 3 else 2)
    expect(staff.post("/api/inventory/adjust", {"product_id": 9, "new_quantity": new_q9, "reason": "Kiểm kê hư hỏng"}), 200,
           "Điều chỉnh tồn kho")
    check(wait_for(lambda: [n for n in staff.get("/api/notifications")[1]["items"] if n["type"] == "LOW_STOCK"
                            and "Bún" in n["title"]]), "Sự kiện inventory.low_stock -> cảnh báo nhân viên")
    low = expect(staff.get("/api/inventory", params={"status": "alert"}), 200, "Lọc hàng sắp hết")
    check(any(i["product_id"] == 9 for i in low["items"]), "Sản phẩm vừa điều chỉnh nằm trong danh sách cảnh báo")
    expect(staff.get("/api/inventory/movements", params={"product_id": 5}), 200, "Lịch sử nhập xuất")

    section("Quản lý sản phẩm (event: product.created -> inventory)")
    newp = expect(staff.post("/api/products", {"name": f"Bánh mì sandwich {stamp}", "sku": f"BM-{stamp}", "category_id": 7,
                                               "price": 25000, "unit": "gói", "initial_stock": 15, "min_quantity": 5}),
                  201, "Tạo sản phẩm mới")
    inv = wait_for(lambda: (lambda s: s[1] if s[0] == 200 and s[1]["quantity"] == 15 else None)(staff.get(f"/api/inventory/{newp['id']}")))
    check(inv, "Kho tự tạo bản ghi với tồn đầu kỳ qua sự kiện")
    expect(staff.post("/api/products", {"name": "Trùng", "sku": f"BM-{stamp}", "category_id": 7, "price": 1, "unit": "x"}), 409, "SKU trùng")
    expect(staff.put(f"/api/products/{newp['id']}", {"sale_price": 30000}), 400, "Giá KM không được lớn hơn giá gốc")
    expect(staff.put(f"/api/products/{newp['id']}", {"sale_price": 22000}), 200, "Cập nhật giá khuyến mãi")
    expect(staff.delete(f"/api/products/{newp['id']}"), 200, "Ngừng kinh doanh")
    expect(anon.get(f"/api/products/{newp['id']}"), 404, "Khách không thấy sản phẩm ngừng kinh doanh")
    expect(cust.post("/api/products", {"name": "x"}), 403, "Khách không tạo được sản phẩm")

    section("Khuyến mãi (quản trị)")
    cp = expect(admin.post("/api/coupons", {"code": f"T{stamp}", "name": "Test", "discount_type": "PERCENT", "discount_value": 5,
                                            "min_order_value": 0, "usage_limit": 1}), 201, "Tạo mã giảm giá")
    expect(admin.post("/api/coupons", {"code": "X", "name": "x", "discount_type": "PERCENT", "discount_value": 150}), 400, "Phần trăm > 100")
    expect(admin.put(f"/api/coupons/{cp['id']}", {"is_active": False}), 200, "Vô hiệu hóa mã")
    expect(cust.post("/api/coupons/validate", {"code": cp["code"], "subtotal": 100000}), 400, "Mã bị vô hiệu không dùng được")
    expect(admin.delete(f"/api/coupons/{cp['id']}"), 200, "Xóa mã chưa dùng")

    section("Người dùng (quản trị)")
    new_staff = expect(admin.post("/api/users", {"email": f"nv{stamp}@taphoa.vn", "password": "Nv@12345", "full_name": "NV Mới",
                                                 "role": "staff"}), 201, "Admin tạo tài khoản nhân viên")
    expect(staff.post("/api/users", {"email": "x@y.zz", "password": "123456", "full_name": "x"}), 403, "Nhân viên không tạo được user")
    expect(admin.put(f"/api/users/{new_staff['id']}", {"is_active": False}), 200, "Khóa tài khoản")
    expect(anon.post("/api/auth/login", {"email": f"nv{stamp}@taphoa.vn", "password": "Nv@12345"}), 403, "Tài khoản bị khóa không đăng nhập được")
    users = expect(admin.get("/api/users", params={"q": "taphoa"}), 200, "Tìm kiếm người dùng")
    check(users["total"] >= 3, "Có kết quả tìm kiếm")

    section("Báo cáo & tổng quan")
    rep = expect(staff.get("/api/reports/summary"), 200, "Báo cáo doanh thu 7 ngày")
    check(rep["totals"]["revenue"] >= 418000 + 70000 and len(rep["revenue_by_day"]) == 7, "Doanh thu gồm đơn online + tại quầy", rep["totals"])
    check(any(t["product_id"] == bc["id"] for t in rep["top_products"]), "Top sản phẩm bán chạy")
    dash = expect(staff.get("/api/dashboard"), 200, "Dashboard tổng hợp (API Composition)")
    check(not dash["partial"] and dash["inventory"]["products"] > 0 and dash["users"]["total"] > 0 and dash["recent_orders"]["items"],
          "Gộp dữ liệu từ order + inventory + product + auth", dash.get("errors"))
    expect(cust.get("/api/dashboard"), 403, "Khách không xem được dashboard")
    pays = expect(staff.get("/api/payments"), 200, "Danh sách giao dịch")
    check(pays["summary"]["paid_amount"] > 0, "Tổng hợp tiền đã thu")
    expect(admin.get("/api/notifications/emails"), 200, "Nhật ký email")

    section("Thông báo")
    n = expect(cust.get("/api/notifications"), 200, "Danh sách thông báo")
    check(n["unread"] > 0, "Có thông báo chưa đọc")
    expect(cust.put("/api/notifications/read-all"), 200, "Đánh dấu đã đọc tất cả")
    check(cust.get("/api/notifications/unread-count")[1]["unread"] == 0, "Không còn thông báo chưa đọc")
    sn = staff.get("/api/notifications")[1]
    expect(staff.put(f"/api/notifications/{sn['items'][0]['id']}/read"), 200, "Nhân viên đọc thông báo chung")
    check(admin.get("/api/notifications")[1]["unread"] >= 1, "Thông báo chung đọc riêng theo từng nhân viên")

    section("SOA: Service Registry & Discovery")
    reg = expect(staff.get("/api/registry"), 200, "Nhân viên xem danh bạ dịch vụ")
    svcs = reg["services"]
    business = ["auth", "product", "inventory", "cart", "order", "payment", "promotion", "notification"]
    check(all(svcs.get(n, {}).get("up", 0) >= 1 for n in business), "8 service nghiệp vụ đã tự đăng ký và đang UP",
          {n: svcs.get(n, {}).get("up") for n in business})
    check(svcs["order"]["layer"] == "task" and svcs["notification"]["layer"] == "utility" and svcs["product"]["layer"] == "entity",
          "Phân lớp dịch vụ: task / entity / utility")
    expect(cust.get("/api/registry"), 403, "Khách không xem được danh bạ")
    hs = anon.get("/api/health")[1]["services"]
    check(all(hs[n]["discovery"] == "registry" for n in business), "Gateway tìm địa chỉ service qua registry",
          {n: hs[n]["discovery"] for n in business})
    if svcs["product"]["up"] > 1:
        seen = {S.get(BASE + "/api/products", params={"page_size": 1}).headers.get("X-Instance") for _ in range(8)}
        check(len(seen) >= 2, "Cân bằng tải xoay vòng giữa các instance product-service", seen)

    section("SOA: Hợp đồng dịch vụ (OpenAPI)")
    idx = expect(anon.get("/api/contracts"), 200, "Danh mục dịch vụ (service inventory)")
    check(len(idx["items"]) == 10 and all(i["layer"] for i in idx["items"]), "10 hợp đồng kèm lớp dịch vụ", idx["items"])
    pc = expect(anon.get("/api/contracts/product"), 200, "Hợp đồng product-service")
    ops = [(path, verb, op) for path, v in pc["paths"].items() for verb, op in v.items()]
    check(pc["openapi"] == "3.0.3" and pc["info"]["x-service-layer"] == "entity" and len(ops) >= 10, "OpenAPI 3.0.3 đúng lớp entity")
    check(all(op["summary"] and " " in op["summary"] for _, _, op in ops), "Mọi thao tác đều có mô tả nghiệp vụ")
    check(not any(path.startswith("/internal") for path, _, _ in ops), "Hợp đồng công khai không lộ API nội bộ")
    oc = anon.get("/api/contracts/order")[1]
    check(oc["paths"]["/api/orders"]["post"]["x-access"] == "authenticated" and oc["info"]["x-service-layer"] == "task",
          "Quyền truy cập ghi trong hợp đồng (đặt hàng cần đăng nhập)")
    ic = anon.get("/api/contracts/inventory")[1]
    check(ic["paths"]["/api/inventory"]["get"]["x-access"].startswith("roles:"), "Hợp đồng ghi vai trò được phép")
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "contracts", "openapi", "product-service.json")
    if os.path.exists(local):
        import json as _json
        exported = {p for p in _json.load(open(local, encoding="utf-8"))["paths"] if p.startswith("/api/")}
        check(exported == {p for p in pc["paths"] if p.startswith("/api/")}, "File contracts/openapi khớp với service đang chạy")
    check(anon.get("/api/v1/products", params={"page_size": 1})[1]["total"] == page["total"], "Phiên bản API: /api/v1 tương đương /api")

    section("SOA: ESB — SOAP/WSDL ↔ REST")
    import xml.etree.ElementTree as ET
    SOAP_NS, CNS = "http://schemas.xmlsoap.org/soap/envelope/", "urn:taphoaxanh:catalog:v1"

    def soap(body):
        xml = (f'<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="{SOAP_NS}" xmlns:c="{CNS}">'
               f'<soap:Body>{body}</soap:Body></soap:Envelope>')
        r = S.post(BASE + "/api/soap/catalog", data=xml.encode("utf-8"), headers={"Content-Type": "text/xml; charset=utf-8"}, timeout=30)
        return r.status_code, ET.fromstring(r.content).find(f"{{{SOAP_NS}}}Body")[0], r.content

    w = S.get(BASE + "/api/soap/catalog?wsdl", timeout=30)
    wsdl_root = ET.fromstring(w.content)
    check(w.status_code == 200 and wsdl_root.tag.endswith("definitions") and b"CatalogService" in w.content, "Công bố WSDL 1.1")
    st, el, raw = soap("<c:GetCategories/>")
    check(st == 200 and len(el.findall(f"{{{CNS}}}Category")) >= 10, "SOAP GetCategories")
    st, el, raw = soap("<c:SearchProducts><c:keyword>gao st25</c:keyword></c:SearchProducts>")
    names = [p.findtext(f"{{{CNS}}}name") for p in el.findall(f"{{{CNS}}}Product")]
    check(st == 200 and any("ST25" in n for n in names), "SOAP SearchProducts (tìm không dấu qua REST)", names)
    st, el, raw = soap("<c:GetProduct><c:productId>1</c:productId></c:GetProduct>")
    check(st == 200 and el.find(f"{{{CNS}}}Product").findtext(f"{{{CNS}}}name") == p1["name"], "SOAP GetProduct khớp dữ liệu REST")
    st, el, raw = soap("<c:GetProduct><c:productId>99999</c:productId></c:GetProduct>")
    check(st == 500 and el.findtext("faultcode") == "soap:Client" and "Không tìm thấy" in el.findtext("faultstring"),
          "Lỗi nghiệp vụ trả về SOAP Fault")
    r = S.post(BASE + "/api/soap/catalog", data=b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', headers={"Content-Type": "text/xml"}, timeout=30)
    check(r.status_code == 500 and b"DTD_NOT_ALLOWED" in r.content, "Chặn DTD / XML entity trong SOAP message")
    try:
        from lxml import etree
        schema = etree.XMLSchema(etree.fromstring(w.content).find(".//{http://www.w3.org/2001/XMLSchema}schema"))
        st, el, raw = soap("<c:SearchProducts><c:categoryId>6</c:categoryId><c:pageSize>50</c:pageSize></c:SearchProducts>")
        check(schema.validate(etree.fromstring(raw).find(f"{{{SOAP_NS}}}Body")[0]), "SOAP response hợp lệ theo XSD trong WSDL")
    except ImportError:
        print("  (bỏ qua kiểm tra XSD - chưa cài lxml)")

    section("Tính năng AI (mô hình cục bộ mặc định; chạy được cả khi thiếu tệp mô hình hoặc khóa API: dùng phương án dự phòng)")
    st = expect(anon.get("/api/ai/status"), 200, "Trạng thái AI")
    engine = st["engine"]
    check(engine in ("local", "llm", "basic"), "Trạng thái nêu rõ cách chạy", engine)
    sources = {"local": ("model", "history", "popular"), "llm": ("ai", "history", "popular"), "basic": ("history", "popular")}[engine]
    chat_source = {"local": "local", "llm": "ai", "basic": "keyword"}[engine]
    rec = expect(anon.get("/api/ai/recommendations/12"), 200, "Gợi ý mua kèm cho Nước mắm Nam Ngư")
    check(rec["items"] and 12 not in [i["id"] for i in rec["items"]] and rec["source"] in sources,
          "Có gợi ý, không gợi ý chính nó", rec.get("source"))
    check(all(i["final_price"] > 0 and i["name"] for i in rec["items"]), "Thẻ gợi ý có tên và giá")
    expect(anon.get("/api/ai/recommendations/999999"), 404, "Gợi ý cho sản phẩm không tồn tại")
    expect(anon.post("/api/ai/chat", {"messages": [{"role": "user", "content": "xin chào"}]}), 401, "Chat cần đăng nhập")
    expect(cust.post("/api/ai/chat", {"messages": []}), 400, "Chat với dữ liệu rỗng")
    chat_res = expect(cust.post("/api/ai/chat", {"messages": [{"role": "user", "content": "nuoc mam"}]}), 200, "Chat hỏi nước mắm")
    check(chat_res["reply"] and chat_res["source"] == chat_source, "Chat trả lời đúng nguồn", chat_res.get("source"))
    if engine != "llm":  # AI ngoài có thể diễn đạt khác; hai chế độ còn lại phải tìm ra nước mắm
        check(any("ước mắm" in p["name"] for p in chat_res["products"]), "Tìm ra nước mắm", chat_res["products"])
    expect(anon.post("/api/ai/meal-plan", {"request": "bữa tối cho 4 người"}), 401, "Lập thực đơn cần đăng nhập")
    expect(cust.post("/api/ai/meal-plan", {"request": ""}), 400, "Lập thực đơn với mô tả rỗng")
    if engine == "local":
        mp = expect(cust.post("/api/ai/meal-plan", {"request": "bữa tối cho 4 người"}), 200, "Lập thực đơn bữa tối cho 4 người")
        check(mp["source"] == "local" and mp["items"] and mp["total"] >= mp["main_total"] > 0, "Thực đơn có danh sách đi chợ và tổng tiền", mp.get("summary"))
    expect(cust.get("/api/ai/usage"), 403, "Khách không xem được thống kê AI")
    expect(admin.get("/api/ai/usage"), 200, "Admin xem thống kê AI")

    section("Thêm nhiều món vào giỏ một lần (danh sách đi chợ của thực đơn AI)")
    bulk_mail = f"bulk{stamp}@example.com"
    expect(anon.post("/api/auth/register", {"email": bulk_mail, "password": "Test@123", "full_name": "Khách Đi Chợ", "phone": "0987654321"}),
           201, "Đăng ký khách mới cho giỏ hàng hàng loạt")
    shopper, _ = login(bulk_mail, "Test@123")
    expect(anon.post("/api/cart/items/bulk", {"items": [{"product_id": 1, "quantity": 1}]}), 401, "Chưa đăng nhập không thêm hàng loạt được")
    expect(shopper.post("/api/cart/items/bulk", {"items": []}), 400, "Danh sách rỗng")
    expect(shopper.post("/api/cart/items/bulk", {"items": [{"product_id": 1, "quantity": 0}]}), 400, "Số lượng 0")
    expect(shopper.post("/api/cart/items/bulk", {"items": [{"product_id": n + 1, "quantity": 1} for n in range(31)]}), 400, "Quá 30 dòng")
    # Tồn kho thay đổi theo các lần chạy trước (kiểm thử nhập hàng), nên đọc tồn thực tế rồi xin vượt 5 đơn vị
    stock5 = expect(anon.get("/api/products/5"), 200, "Đọc tồn kho sản phẩm 5")["available"]
    ask5 = min(99, stock5 + 5)
    res = expect(shopper.post("/api/cart/items/bulk", {"items": [
        {"product_id": 1, "quantity": 2}, {"product_id": 7, "quantity": 3}, {"product_id": 1, "quantity": 1},
        {"product_id": 999999, "quantity": 1}, {"product_id": 23, "quantity": 1}, {"product_id": 5, "quantity": ask5}]}), 200, "Thêm 6 dòng (có dòng trùng, không tồn tại, hết hàng, vượt kho)")
    got = {a["product_id"]: a["quantity"] for a in res["added"]}
    check(got.get(1) == 3 and got.get(7) == 3, "Dòng trùng được cộng dồn (2 + 1)", res["added"])
    failed = {f["product_id"]: f["reason"] for f in res["failed"]}
    check(999999 in failed and 23 in failed and all(failed.values()), "Sản phẩm không tồn tại / hết hàng nằm trong failed kèm lý do", res["failed"])
    p5 = next((a for a in res["adjusted"] if a["product_id"] == 5), None)
    check(stock5 >= 99 or (p5 and p5["requested"] == ask5 and p5["added"] == stock5) or (stock5 == 0 and 5 in failed),
          "Vượt tồn kho: chỉ thêm đúng phần còn lại (adjusted) hoặc từ chối nếu hết hàng", (stock5, res["adjusted"], res["failed"]))
    added_total = sum(got.values()) + sum(a["added"] for a in res["adjusted"])
    check(res["cart"]["item_count"] == added_total and shopper.get("/api/cart/count")[1]["count"] == added_total,
          "Giỏ hàng khớp số đã thêm; dòng lỗi không làm hỏng các dòng còn lại", (res["cart"]["item_count"], added_total))
    res2 = expect(shopper.post("/api/cart/items/bulk", {"items": [{"product_id": 1, "quantity": 2}]}), 200, "Thêm tiếp cùng sản phẩm")
    line1 = next(i for i in res2["cart"]["items"] if i["product_id"] == 1)
    check(line1["quantity"] == 5, "Số lượng cộng dồn với giỏ hiện có (3 + 2)", line1["quantity"])

    section("Rate limiting")
    fake_ip = {"X-Forwarded-For": f"10.{stamp[-2:]}.{stamp[-4:-2]}.7"}  # tách bucket để không chặn lần chạy sau
    codes = [anon.post("/api/auth/login", {"email": "brute@force.vn", "password": "x"}, headers=dict(fake_ip))[0] for _ in range(25)]
    check(429 in codes, "Chặn đăng nhập dồn dập (429)", codes)

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = [name for ok, name in RESULTS if not ok]
    print(f"\nKẾT QUẢ: {passed}/{len(RESULTS)} kiểm tra đạt")
    for name in failed:
        print("  FAIL:", name)
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
