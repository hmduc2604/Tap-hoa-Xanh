# Đối chiếu kiến trúc với SOA (Service-Oriented Architecture)

## 1. Kết luận

Tạp Hóa Xanh được xây theo **kiến trúc hướng dịch vụ**: hệ thống là tập hợp các dịch vụ tự trị, mỗi dịch vụ có
hợp đồng công bố rõ ràng, được tìm thấy qua danh bạ dịch vụ, giao tiếp qua tầng tích hợp và được kết hợp
(orchestration / choreography) để tạo thành quy trình nghiệp vụ. Cách hiện thực theo phong cách microservice
(service nhỏ, triển khai độc lập, giao tiếp REST/message) — một dạng hiện đại của SOA.

Lần rà soát đầu tiên cho thấy project đạt 5/8 nguyên tắc SOA nhưng thiếu ba thành phần SOA kinh điển.
Các phần sau đã được bổ sung:

| Thiếu trước đây | Đã bổ sung |
|---|---|
| Hợp đồng dịch vụ chuẩn hóa (chỉ có tài liệu markdown) | OpenAPI 3.0 cho cả 9 thành phần, sinh trực tiếp từ code; WSDL 1.1 cho CatalogService; thư mục `contracts/`; kiểm tra hợp đồng khớp code |
| Khả năng khám phá dịch vụ (địa chỉ cấu hình cứng) | `registry-service`: tự đăng ký, heartbeat, tra cứu theo tên, cân bằng tải xoay vòng, dự phòng khi registry lỗi |
| Phân lớp dịch vụ & tầng tích hợp | Cấu trúc `services/task`, `services/entity`, `services/utility`, `integration/`; gateway làm ESB nhẹ: dàn xếp SOAP ↔ REST, biến đổi message |

## 2. Tám nguyên tắc thiết kế dịch vụ (Thomas Erl)

| # | Nguyên tắc | Hiện thực trong project |
|---|---|---|
| 1 | **Standardized Service Contract** — hợp đồng chuẩn hóa | Mỗi service phục vụ `GET /contract` (OpenAPI 3.0.3) sinh từ route + docstring + decorator phân quyền; gateway công bố bản công khai ở `/api/contracts/<service>`; CatalogService có WSDL 1.1 (`/api/soap/catalog?wsdl`); định dạng lỗi chung `{"error": {code, message, details}}`; phiên bản hợp đồng `/api/v1/*` |
| 2 | **Loose Coupling** — liên kết lỏng | Database per service; gọi nhau theo **tên** dịch vụ qua registry (không gắn địa chỉ); sự kiện bất đồng bộ qua RabbitMQ để bên phát không phụ thuộc bên nhận |
| 3 | **Abstraction** — trừu tượng hóa | Client chỉ thấy gateway; hợp đồng công khai ẩn toàn bộ API nội bộ `/internal/*`; client SOAP không cần biết bên trong là REST/JSON |
| 4 | **Reusability** — tái sử dụng | Entity service dùng chung cho nhiều quy trình: inventory phục vụ đặt hàng online, POS, nhập kho; payment phục vụ COD, ví, tại quầy; product được tái sử dụng bởi web, cart, order, inventory và CatalogService SOAP |
| 5 | **Autonomy** — tự trị | Mỗi service một CSDL, một container, một tiến trình; triển khai, khởi động lại, scale riêng lẻ |
| 6 | **Statelessness** — không trạng thái | Xác thực bằng JWT, không session; trạng thái nằm trong CSDL nên chạy được nhiều instance (`--scale product-service=2`) |
| 7 | **Discoverability** — khám phá được | Service Registry (danh bạ instance), danh mục dịch vụ `/api/contracts`, trang `/api-docs.html` hiển thị hợp đồng của mọi service theo lớp |
| 8 | **Composability** — kết hợp được | order-service điều phối Saga qua inventory, promotion, payment, cart; gateway kết hợp 4 service cho dashboard (API Composition); CatalogService SOAP là dịch vụ kết hợp trên product-service |

## 3. Phân lớp dịch vụ (service models)

| Lớp | Service | Vai trò |
|---|---|---|
| **Task service** | `services/task/order-service` | Hiện thực quy trình nghiệp vụ "bán hàng": đặt hàng online, POS, vòng đời đơn; không sở hữu thực thể nào khác ngoài đơn hàng, mà điều phối các entity service |
| **Entity service** | `services/entity/auth-service`, `product-service`, `inventory-service`, `cart-service`, `payment-service`, `promotion-service` | Mỗi service quản lý một thực thể nghiệp vụ và được tái sử dụng bởi nhiều quy trình |
| **Utility service** | `services/utility/notification-service`, `ai-service` | Năng lực dùng chung không gắn nghiệp vụ: thông báo, email (chỉ lắng nghe sự kiện); gợi ý, trợ lý chat và lập thực đơn AI (chỉ đọc dữ liệu, học từ sự kiện) |
| **Tầng tích hợp** | `integration/gateway`, `integration/registry` | ESB nhẹ (định tuyến, bảo mật, dàn xếp giao thức, biến đổi message) và danh bạ dịch vụ |

Lớp của mỗi service được ghi trong code (`create_base_app(layer=...)`), trong hợp đồng (`info.x-service-layer`),
trong health check và trong bản ghi registry.

## 4. Ánh xạ SOA Reference Architecture (The Open Group)

| Lớp SOA RA | Thành phần trong project |
|---|---|
| 1. Operational Systems | PostgreSQL 16 (9 database), RabbitMQ 3.13 |
| 2. Service Components | Mã nguồn Flask của từng service trong `services/<lớp>/<service>/app.py` |
| 3. Services | 9 service (8 nghiệp vụ + ai-service), hợp đồng OpenAPI trong `contracts/openapi/`, WSDL trong `contracts/wsdl/` |
| 4. Business Process | Saga đặt hàng, bán tại quầy, vòng đời đơn trong order-service; luồng sự kiện order/payment/inventory |
| 5. Consumer | Giao diện cửa hàng, trang quản trị, POS (`frontend/`); client SOAP bất kỳ đọc được WSDL |
| 6. Integration | API Gateway (ESB nhẹ), RabbitMQ (event bus), Service Registry |
| 7. Quality of Service | JWT, X-Internal-Token, rate limit, circuit breaker, timeout/retry, health check, X-Request-ID, dead letter queue |
| 8. Information | Database per service, dữ liệu sản phẩm nhân bản sang kho qua sự kiện, idempotent consumer |
| 9. Governance | Hợp đồng sinh từ code + `scripts/export_contracts.py --check`, phiên bản API `/api/v1`, danh bạ dịch vụ, 197 kiểm thử end-to-end |

## 5. Các thành phần SOA kinh điển

### Service Registry (tương đương UDDI)
- `integration/registry/app.py`, cổng 8500, chỉ nhận lời gọi có `X-Internal-Token`.
- Mỗi instance tự đăng ký khi khởi động (`common/registry.py`): tên, địa chỉ, phiên bản, lớp, địa chỉ hợp đồng.
- Heartbeat mỗi 10 giây; quá 30 giây không có heartbeat thì instance bị loại khỏi kết quả tra cứu.
- Bên gọi tra cứu theo tên (`discovery.resolve("inventory")`), xoay vòng giữa các instance; instance chết
  khi chưa kết nối được sẽ tự chuyển sang instance khác.
- Registry lỗi: hệ thống vẫn chạy bằng địa chỉ dự phòng `*_SERVICE_URL`; registry chạy lại thì các
  service tự đăng ký lại ở heartbeat kế tiếp.

| API registry | Mô tả |
|---|---|
| `POST /registry/instances` | Đăng ký instance |
| `PUT /registry/instances/{service}/{id}/heartbeat` | Gia hạn (404 nếu chưa đăng ký → đăng ký lại) |
| `DELETE /registry/instances/{service}/{id}` | Hủy đăng ký |
| `GET /registry/services` | Toàn bộ danh bạ |
| `GET /registry/services/{service}` | Các instance đang UP |

### ESB — dàn xếp giao thức và biến đổi message
`integration/gateway/soap.py`: CatalogService SOAP 1.1 document/literal.

```
Client SOAP ──XML──▶ API Gateway (ESB) ──REST/JSON──▶ product-service (tìm qua registry)
            ◀──XML──   biến đổi JSON → XML theo WSDL   ◀──────JSON───────
```

| Thao tác | Tham số | Gọi REST tương ứng |
|---|---|---|
| `GetCategories` | — | `GET /api/categories` |
| `SearchProducts` | `keyword`, `categoryId`, `page`, `pageSize` | `GET /api/products` |
| `GetProduct` | `productId` | `GET /api/products/{id}` |

Lỗi trả về **SOAP Fault** (`soap:Client` / `soap:Server`). SOAP message có DTD hoặc entity bị từ chối
(chống tấn công XXE / billion laughs), giới hạn 64 KB. Phản hồi đã được kiểm tra hợp lệ theo XSD trong WSDL.

### Orchestration và Choreography
- **Orchestration**: order-service điều khiển Saga đặt hàng (giữ hàng → ghi nhận mã → tạo thanh toán), bù trừ khi lỗi.
- **Choreography**: các service phản ứng với sự kiện mà không ai điều khiển — `payment.completed` làm đơn tự xác nhận,
  `product.created` làm kho tạo bản ghi, `order.created` làm notification gửi thông báo.

### Hợp đồng dịch vụ
- Sinh từ code nên không bị lệch: summary lấy từ docstring, quyền lấy từ decorator, tham số lấy từ route.
- `python scripts/export_contracts.py` ghi `contracts/openapi/*.json` và `contracts/wsdl/catalog.wsdl`;
  `--check` báo lỗi nếu API thay đổi mà chưa cập nhật hợp đồng.
- `x-access` trên mỗi thao tác: `public`, `authenticated`, `roles:admin,staff`, `internal`.

## 6. Microservice và SOA

SOA là triết lý kiến trúc (hệ thống là tập hợp dịch vụ có hợp đồng, liên kết lỏng, tái sử dụng được);
microservice là một cách hiện thực SOA, ưu tiên service nhỏ, triển khai độc lập, CSDL riêng và
giao tiếp nhẹ thay cho một ESB tập trung nặng nề. Project giữ đầy đủ nguyên tắc SOA, đồng thời có các
thành phần SOA kinh điển (registry, hợp đồng WSDL/OpenAPI, ESB mediation) để thể hiện rõ yêu cầu của
môn Kiến trúc hướng dịch vụ.

## 7. Cách kiểm chứng khi demo

1. `/admin/#system`: danh bạ dịch vụ — mỗi instance, lớp, phiên bản, heartbeat.
2. `/api-docs.html`: hợp đồng của từng service theo lớp; tab api-gateway có ô gửi thử SOAP request.
3. Chạy 2 instance: `python run_local.py --scale product=2` (local) hoặc
   `docker compose up -d --scale product-service=2` → header `X-Instance` của `/api/products` thay đổi luân phiên.
4. Tắt registry: hệ thống vẫn bán hàng được, `/api/health` báo `DEGRADED` và dùng địa chỉ dự phòng.
5. Gọi SOAP bằng curl:

```bash
curl -X POST http://localhost:8080/api/soap/catalog -H "Content-Type: text/xml; charset=utf-8" --data \
'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:c="urn:taphoaxanh:catalog:v1">
  <soap:Body><c:GetProduct><c:productId>1</c:productId></c:GetProduct></soap:Body>
</soap:Envelope>'
```

6. `python tests/e2e_test.py`: 197 kiểm thử, trong đó có nhóm "SOA: Service Registry", "SOA: Hợp đồng dịch vụ", "SOA: ESB — SOAP/WSDL ↔ REST".
