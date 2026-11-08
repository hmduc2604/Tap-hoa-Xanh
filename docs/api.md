# Tài liệu API

Mọi request từ client đi qua **API Gateway** (`http://localhost:8000/api/...` hoặc `http://localhost:8080/api/...` qua nginx).
Gateway kiểm tra JWT rồi định tuyến tới service tương ứng.

- Xác thực: header `Authorization: Bearer <token>` (lấy từ `/api/auth/login` hoặc `/api/auth/register`)
- Định dạng lỗi thống nhất: `{"error": {"code": "OUT_OF_STOCK", "message": "Không đủ hàng: ...", "details": [...]}}`
- Phân trang: `?page=1&page_size=20` → `{"items": [], "page", "page_size", "total", "total_pages"}`
- Tiền tệ: số nguyên VND. Thời gian: `YYYY-MM-DD HH:MM:SS` giờ Việt Nam.

Hợp đồng máy đọc được của từng service: `contracts/openapi/*.json` (OpenAPI 3) và `contracts/wsdl/catalog.wsdl`,
hoặc xem trực quan tại `/api-docs.html`.

Quyền: **Công khai** = không cần đăng nhập · **Khách** = mọi tài khoản đã đăng nhập · **NV** = nhân viên hoặc quản trị · **QT** = chỉ quản trị viên.

## API Gateway

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| GET | `/api/health` | Công khai | Trạng thái gateway + từng service (độ trễ, loại CSDL, circuit breaker) |
| GET | `/api/dashboard?date_from&date_to` | NV | **API Composition**: gộp báo cáo (order), tồn kho (inventory), sản phẩm (product), người dùng (auth) |
| GET | `/api/registry` | NV | Danh bạ dịch vụ từ Service Registry: service, lớp, phiên bản, instance, heartbeat |
| GET | `/api/contracts` | Công khai | Danh mục dịch vụ (service inventory) kèm đường dẫn hợp đồng |
| GET | `/api/contracts/{service}` | Công khai | Hợp đồng OpenAPI 3 công khai của một service (`auth`, `product`, …, `gateway`) |
| GET | `/api/soap/catalog?wsdl` | Công khai | WSDL 1.1 của CatalogService |
| POST | `/api/soap/catalog` | Công khai | CatalogService SOAP 1.1: `GetCategories`, `SearchProducts`, `GetProduct` (ESB chuyển sang REST) |

Phiên bản hợp đồng: mọi API service có thể gọi qua `/api/v1/...` (tương đương `/api/...`).

## auth-service (cổng 8001)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| POST | `/api/auth/register` | Công khai | Đăng ký `{email, password, full_name, phone}` → `{token, user}`; phát sự kiện `user.registered` |
| POST | `/api/auth/login` | Công khai | Đăng nhập `{email, password}` → `{token, user}` (giới hạn 20 lần/phút/IP) |
| GET / PUT | `/api/auth/me` | Khách | Xem / sửa hồ sơ `{full_name, phone}` (trả token mới) |
| PUT | `/api/auth/change-password` | Khách | `{old_password, new_password}` |
| GET / POST | `/api/users/me/addresses` | Khách | Sổ địa chỉ giao hàng |
| PUT / DELETE | `/api/users/me/addresses/{id}` | Khách | Sửa (kể cả `is_default`) / xóa địa chỉ |
| GET | `/api/users?q&role` | NV | Danh sách người dùng |
| GET | `/api/users/{id}` | NV | Chi tiết người dùng + địa chỉ |
| POST | `/api/users` | QT | Tạo tài khoản (nhân viên) `{email, password, full_name, role}` |
| PUT | `/api/users/{id}` | QT | Đổi vai trò, khóa/mở khóa (`is_active`), đặt lại mật khẩu |

## product-service (cổng 8002)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| GET | `/api/categories` | Công khai | Danh mục + số sản phẩm (`?all=1` cho NV xem cả danh mục ẩn) |
| POST / PUT / DELETE | `/api/categories[/{id}]` | NV | Quản lý danh mục (không xóa được danh mục còn sản phẩm) |
| GET | `/api/products` | Công khai | `q` (tìm không dấu), `category_id`, `min_price`, `max_price`, `on_sale`, `sort` (`popular`, `newest`, `price_asc`, `price_desc`, `discount`, `rating`, `name`), `ids`; kèm tồn kho từ inventory-service |
| GET | `/api/products/{id}` | Công khai | Chi tiết + tồn kho + sản phẩm cùng danh mục |
| GET | `/api/products/barcode/{code}` | NV | Tra theo mã vạch hoặc SKU (máy POS) |
| POST | `/api/products` | NV | Tạo sản phẩm (có thể kèm `initial_stock`, `min_quantity`) → sự kiện `product.created` |
| PUT | `/api/products/{id}` | NV | Cập nhật → sự kiện `product.updated` |
| DELETE | `/api/products/{id}` | NV | Ngừng kinh doanh (xóa mềm) |
| GET | `/api/products/{id}/reviews` | Công khai | Đánh giá + phân bố số sao |
| POST | `/api/products/{id}/reviews` | Khách | `{rating 1-5, comment}` — chỉ khi đã mua & nhận hàng (hỏi order-service) |

## inventory-service (cổng 8003)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| GET | `/api/inventory?q&status` | NV | Tồn kho; `status`: `alert` (cần nhập), `low`, `out` |
| GET | `/api/inventory/summary` | NV | Tổng quan kho |
| GET | `/api/inventory/{product_id}` | NV | Tồn kho + 50 biến động gần nhất + hàng đang giữ |
| PUT | `/api/inventory/{product_id}/settings` | NV | `{min_quantity}` ngưỡng cảnh báo |
| POST | `/api/inventory/adjust` | NV | Kiểm kê `{product_id, new_quantity | change, reason}` |
| GET | `/api/inventory/movements?product_id&type` | NV | Lịch sử nhập / xuất / điều chỉnh |
| GET / POST | `/api/suppliers` | NV | Nhà cung cấp |
| PUT | `/api/suppliers/{id}` | NV | Sửa nhà cung cấp |
| DELETE | `/api/suppliers/{id}` | QT | Ngừng hợp tác |
| GET | `/api/stock-receipts[/{id}]` | NV | Phiếu nhập kho |
| POST | `/api/stock-receipts` | NV | `{supplier_id, note, items: [{product_id, quantity, unit_cost}]}` → cộng tồn kho |

## cart-service (cổng 8004)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| GET | `/api/cart` | Khách | Giỏ hàng với giá & tồn kho mới nhất, cảnh báo hết hàng |
| GET | `/api/cart/count` | Khách | Tổng số lượng (badge) |
| POST | `/api/cart/items` | Khách | `{product_id, quantity}` (kiểm tra tồn kho) |
| PUT / DELETE | `/api/cart/items/{product_id}` | Khách | Đổi số lượng (0 = xóa) / xóa |
| DELETE | `/api/cart` | Khách | Xóa toàn bộ giỏ |

## order-service (cổng 8005)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| POST | `/api/orders/preview` | Khách | Tính tạm tính / giảm giá / phí ship `{coupon_code, items?}` |
| POST | `/api/orders` | Khách | **Đặt hàng (Saga)** `{payment_method: COD/BANK_TRANSFER/EWALLET, address_id | shipping_address, coupon_code, note, items?}` — bỏ `items` để đặt từ giỏ |
| GET | `/api/orders/my?status` | Khách | Đơn của tôi |
| GET | `/api/orders/{id}` | Khách (chủ đơn) / NV | Chi tiết + lịch sử + thanh toán |
| POST | `/api/orders/{id}/cancel` | Khách (đơn chờ xác nhận) / NV | Hủy đơn → trả hàng, hủy/hoàn tiền, hoàn lượt mã |
| GET | `/api/orders?status&channel&q&date_from&date_to` | NV | Quản lý đơn + đếm theo trạng thái |
| PUT | `/api/orders/{id}/status` | NV | `{status, note}`: `PENDING→CONFIRMED→SHIPPING→DELIVERED`, hoặc `CANCELLED` |
| POST | `/api/pos/orders` | NV | **Bán tại quầy** `{items, payment_method: CASH/CARD/BANK_TRANSFER, cash_received, coupon_code, customer_name, customer_phone}` |
| GET | `/api/reports/summary?date_from&date_to` | NV | Doanh thu, theo ngày, top sản phẩm, theo kênh / phương thức |

## payment-service (cổng 8006)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| GET | `/api/payments/methods` | Công khai | Phương thức + thông tin chuyển khoản |
| GET | `/api/payments/{id}` | Khách (chủ) / NV | Chi tiết giao dịch |
| GET | `/api/payments/order/{order_id}` | Khách (chủ) / NV | Giao dịch của đơn |
| POST | `/api/payments/{id}/pay` | Khách | Mô phỏng cổng thanh toán `{success: true/false}` → `payment.completed` / `payment.failed` |
| POST | `/api/payments/{id}/confirm` | NV | Xác nhận đã nhận chuyển khoản / COD |
| GET | `/api/payments?status&method&q` | NV | Danh sách + tổng hợp tiền |

## promotion-service (cổng 8007)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| GET | `/api/coupons/available` | Công khai | Mã công khai đang hiệu lực |
| POST | `/api/coupons/validate` | Khách | `{code, subtotal}` → số tiền giảm hoặc lý do không hợp lệ |
| GET / POST | `/api/coupons` | NV | Danh sách / tạo mã (`PERCENT` hoặc `FIXED`, tối đa, đơn tối thiểu, giới hạn lượt, thời gian) |
| PUT / DELETE | `/api/coupons/{id}` | NV | Sửa / xóa (mã đã dùng sẽ bị tắt thay vì xóa) |
| GET | `/api/coupons/{id}/usages` | NV | Lượt sử dụng |

## notification-service (cổng 8008)

| Method | Đường dẫn | Quyền | Mô tả |
|---|---|---|---|
| GET | `/api/notifications?unread=1` | Khách | Thông báo của tôi (NV thấy thêm thông báo chung của cửa hàng) |
| GET | `/api/notifications/unread-count` | Khách | Số chưa đọc |
| PUT | `/api/notifications/{id}/read` | Khách | Đánh dấu đã đọc |
| PUT | `/api/notifications/read-all` | Khách | Đọc tất cả |
| GET | `/api/notifications/emails` | QT | Nhật ký email (mô phỏng) |

## registry-service (cổng 8500, chỉ nội bộ)

| Method | Đường dẫn | Mô tả |
|---|---|---|
| POST | `/registry/instances` | Đăng ký instance `{service, instance_id, url, version, layer, description, health_url, contract_url}` |
| PUT | `/registry/instances/{service}/{id}/heartbeat` | Heartbeat (404 `NOT_REGISTERED` → instance đăng ký lại) |
| DELETE | `/registry/instances/{service}/{id}` | Hủy đăng ký |
| GET | `/registry/services` | Toàn bộ danh bạ |
| GET | `/registry/services/{service}` | Các instance đang UP của một service |

## API nội bộ (service ↔ service, không đi qua gateway)

Yêu cầu header `X-Internal-Token`. Gateway không định tuyến `/internal/*` nên client bên ngoài không gọi được.

| Service | Endpoint | Dùng bởi |
|---|---|---|
| auth | `GET /internal/users/{id}`, `GET /internal/users/{id}/addresses/{aid}`, `GET /internal/users?ids=`, `GET /internal/users/stats` | order, gateway |
| product | `POST /internal/products/batch`, `GET /internal/products/stats` | cart, order, inventory, gateway |
| inventory | `POST /internal/inventory/availability`, `.../reserve`, `.../commit`, `.../release`, `GET .../summary` | product, cart, order, gateway |
| cart | `GET /internal/carts/{user_id}`, `DELETE /internal/carts/{user_id}?product_ids=` | order |
| order | `GET /internal/orders/purchased`, `GET /internal/orders/report`, `GET /internal/orders/recent` | product, gateway |
| payment | `POST /internal/payments`, `POST .../order/{id}/mark-paid`, `POST .../order/{id}/cancel`, `GET .../order/{id}` | order |
| promotion | `POST /internal/coupons/validate`, `.../redeem`, `.../release` | order |
| tất cả | `POST /internal/events` | event bus chế độ HTTP (chạy local) |
| tất cả | `GET /health` | gateway, Docker healthcheck (trả cả `layer`, `instance`) |
| tất cả | `GET /contract[?public=1]` | Hợp đồng OpenAPI 3 sinh từ code (gateway, `scripts/export_contracts.py`) |

## Ví dụ nhanh (curl)

```bash
# Đăng nhập
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"khach@taphoa.vn","password":"Khach@123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Thêm vào giỏ và đặt hàng COD với mã giảm giá
curl -X POST http://localhost:8000/api/cart/items -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"product_id":1,"quantity":2}'
curl -X POST http://localhost:8000/api/orders -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"address_id":1,"payment_method":"COD","coupon_code":"WELCOME10"}'
```
