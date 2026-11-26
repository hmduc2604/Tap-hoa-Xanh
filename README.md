# Tạp Hóa Xanh — Hệ thống cửa hàng tạp hóa theo Kiến trúc hướng dịch vụ (SOA)

Ứng dụng bán hàng cho cửa hàng tạp hóa: khách đặt hàng online, nhân viên xử lý đơn, bán tại quầy (POS),
quản lý kho, nhập hàng, khuyến mãi và báo cáo doanh thu. Hệ thống gồm **9 dịch vụ** (8 nghiệp vụ và ai-service) chia theo
lớp **task / entity / utility**, mỗi dịch vụ một CSDL riêng và một **hợp đồng OpenAPI**, được tìm thấy qua
**Service Registry**, giao tiếp qua **tầng tích hợp** (API Gateway đóng vai trò ESB nhẹ, có dàn xếp SOAP/WSDL ↔ REST)
và **RabbitMQ** (sự kiện bất đồng bộ).

```mermaid
flowchart TB
    C["Consumer: web cửa hàng, quản trị, POS, client SOAP"] --> GW
    subgraph INT["Tầng tích hợp"]
        GW["API Gateway / ESB<br/>JWT, định tuyến theo tên, SOAP ↔ REST"]
        REG["Service Registry<br/>đăng ký, heartbeat, tra cứu"]
    end
    GW -. tra cứu .-> REG
    GW --> T & E & U
    T["Task service<br/>order"] --> E["Entity services<br/>auth, product, inventory, cart, payment, promotion"]
    U["Utility services<br/>notification, ai"]
    T & E <-->|sự kiện| MQ{{RabbitMQ}}
    MQ --> U
```

Tài liệu: [Đối chiếu SOA](docs/soa.md) · [Kiến trúc chi tiết](docs/architecture.md) · [Danh sách API](docs/api.md) ·
Hợp đồng: [`contracts/`](contracts/)

## Kiến trúc hướng dịch vụ trong project

| Thành phần SOA | Hiện thực |
|---|---|
| Hợp đồng dịch vụ | OpenAPI 3.0 cho mọi service (`GET /contract`, `/api/contracts/<service>`), WSDL 1.1 cho CatalogService, file trong `contracts/` |
| Danh bạ & khám phá dịch vụ | `integration/registry`: service tự đăng ký + heartbeat, gateway và service tra cứu theo tên, xoay vòng nhiều instance |
| Phân lớp dịch vụ | `services/task` (điều phối quy trình), `services/entity` (thực thể nghiệp vụ), `services/utility` (hạ tầng dùng chung) |
| Tầng tích hợp / ESB | `integration/gateway`: định tuyến, xác thực, dàn xếp giao thức SOAP ↔ REST, biến đổi JSON ↔ XML |
| Kết hợp dịch vụ | Orchestration (Saga đặt hàng ở order-service) và choreography (sự kiện qua RabbitMQ) |
| Chất lượng dịch vụ | JWT, khóa nội bộ, rate limit, circuit breaker, retry, health check, truy vết X-Request-ID |
| Quản trị (governance) | Hợp đồng sinh từ code + kiểm tra khớp code, phiên bản `/api/v1`, 197 kiểm thử end-to-end |

Đối chiếu đầy đủ với 8 nguyên tắc SOA của Thomas Erl và SOA Reference Architecture: [docs/soa.md](docs/soa.md).

## Tính năng

**Khách hàng**
- Đăng ký / đăng nhập (JWT), hồ sơ, đổi mật khẩu, sổ địa chỉ giao hàng
- Duyệt theo danh mục, **tìm kiếm không dấu** ("gao st25" ra "Gạo ST25"), lọc giá, lọc hàng giảm giá, 7 kiểu sắp xếp
- Chi tiết sản phẩm, tồn kho, sản phẩm liên quan, đánh giá (chỉ khách đã mua & nhận hàng)
- Giỏ hàng luôn theo giá & tồn kho mới nhất; mã giảm giá; miễn phí giao hàng từ 300.000đ
- Thanh toán COD, chuyển khoản, ví điện tử Xanh Pay (mô phỏng); theo dõi đơn, tự hủy đơn
- Thông báo trong app + email (mô phỏng)
- **Chế độ sáng / tối**: nút mặt trời/mặt trăng ở thanh đầu trang (cửa hàng) và góc phải tiêu đề (admin); nhớ lựa chọn trên trình duyệt, lần đầu theo cài đặt hệ điều hành
- **AI**: gợi ý "thường được mua cùng" (trong chi tiết sản phẩm và giỏ hàng) **trợ lý mua sắm** dạng chat ("nấu canh chua cho 4 người cần mua gì?") và **thực đơn AI** (trang `/meal.html`: nhập bữa ăn muốn nấu, nhận danh sách đi chợ theo ngân sách rồi thêm cả danh sách vào giỏ một lần bấm), xem mục *Tính năng AI* bên dưới

**Nhân viên / Quản trị viên** (`/admin/`)
- Dashboard doanh thu, đơn hàng (xác nhận → giao → hoàn tất, hủy tự hoàn kho / tiền / lượt mã)
- **Bán tại quầy (POS)**: quét mã vạch, tiền thối, in hóa đơn
- Sản phẩm, danh mục, kho (kiểm kê, ngưỡng cảnh báo, lịch sử), phiếu nhập, nhà cung cấp
- Mã giảm giá, thanh toán, người dùng & phân quyền, thông báo, nhật ký email
- **Trạng thái dịch vụ**: sức khỏe từng service, danh bạ Service Registry (instance, lớp, phiên bản, heartbeat)

**Cho nhà phát triển**
- `/api-docs.html`: xem hợp đồng của mọi service theo lớp, gửi thử SOAP request
- `/api/soap/catalog?wsdl`: WSDL của CatalogService

## Cấu trúc thư mục

```
├── services/                          # Các dịch vụ nghiệp vụ, chia theo lớp SOA
│   ├── task/
│   │   └── order-service/             # :8005  điều phối đặt hàng (Saga), POS, báo cáo
│   ├── entity/
│   │   ├── auth-service/              # :8001  người dùng, JWT, địa chỉ, phân quyền
│   │   ├── product-service/           # :8002  danh mục, sản phẩm, tìm kiếm, đánh giá
│   │   ├── inventory-service/         # :8003  tồn kho, giữ hàng, nhập kho, nhà cung cấp
│   │   ├── cart-service/              # :8004  giỏ hàng
│   │   ├── payment-service/           # :8006  thanh toán, hoàn tiền
│   │   └── promotion-service/         # :8007  mã giảm giá
│   └── utility/
│       ├── notification-service/      # :8008  thông báo, email (chỉ nghe sự kiện)
│       └── ai-service/                # :8009  gợi ý mua kèm + trợ lý mua sắm + thực đơn (mô hình tự huấn luyện)
├── integration/                       # Tầng tích hợp
│   ├── gateway/                       # :8000  API Gateway / ESB (app.py, soap.py)
│   └── registry/                      # :8500  Service Registry
├── contracts/                         # Hợp đồng dịch vụ: openapi/*.json, wsdl/catalog.wsdl
├── common/                            # Thư viện hạ tầng dùng chung: DB, event bus, registry client,
│                                      #   hợp đồng OpenAPI, auth/JWT, HTTP client + circuit breaker
│   ├── seed_data.py                   #   Dữ liệu mẫu: 13 danh mục, 598 sản phẩm
│   └── catalog/                       #   Sinh danh mục theo nhóm hàng (dry, drinks_snacks, fresh, home)
├── frontend/                          # Lớp consumer: cửa hàng, admin/, api-docs.html (HTML/CSS/JS thuần, không cần build)
│   └── assets/                        #   css/base.css (biến màu sáng/tối), store.css, admin.css; js/theme.js (chế độ sáng/tối)
├── infra/                             # Script tạo database PostgreSQL, cấu hình nginx
├── scripts/export_contracts.py        # Xuất / kiểm tra hợp đồng dịch vụ
├── ml/                                # Dữ liệu mô phỏng + huấn luyện mô hình AI (xem ml/README.md); 144 món ăn: knowledge.py, dishes_extra.py
├── tests/e2e_test.py                  # 197 kiểm thử end-to-end qua gateway (+ model_test, ai_local_test, ai_test)
├── docs/                              # soa.md, architecture.md, api.md, slide báo cáo
├── docker-compose.yml
└── run_local.py                       # Chạy toàn bộ hệ thống không cần Docker
```

Mỗi service: `app.py`, `Dockerfile`, `requirements.txt`.

## Tính năng AI

`ai-service` (utility, cổng 8009, database `ai_db`) có ba chức năng, chạy bằng **mô hình do dự án tự huấn luyện** (mặc định, không cần
khóa API, không gửi dữ liệu ra ngoài) hoặc, tùy chọn, bằng API mô hình ngôn ngữ bên ngoài:

| Chức năng | API (qua gateway) | Cách hoạt động (`AI_ENGINE=local`) |
|---|---|---|
| Gợi ý "thường mua cùng" | `GET /api/ai/recommendations/{id}?cart=1,2,3` (công khai) | Mạng nơ-ron MLP "hoàn thiện giỏ hàng" + xác suất có điều kiện: nhận sản phẩm đang xem (và cả giỏ hàng nếu có `cart`) rồi dự đoán món còn thiếu. Điểm được **cộng thêm từ đơn hàng thật** (sự kiện `order.completed`), nên càng bán nhiều càng sát thực tế |
| Trợ lý mua sắm | `POST /api/ai/chat` (cần đăng nhập, 15 lượt/phút/người) | Mô hình phân loại 14 ý định (tìm hàng, hỏi giá, nấu món, gợi ý bữa ăn, mua kèm, khuyến mãi, ngân sách, thông tin cửa hàng, đơn hàng...) + trích xuất món ăn / số người / ngân sách / sản phẩm, rồi soạn câu trả lời từ **dữ liệu thật** của product-service. Thẻ sản phẩm có số lượng gợi ý và nút **Thêm** (trợ lý chỉ đọc dữ liệu, khách tự bấm thêm vào giỏ) |
| Thực đơn AI | `POST /api/ai/meal-plan` (cần đăng nhập, 6 lượt/phút/người) rồi `POST /api/cart/items/bulk` | Khách nhập "bữa tối cho 4 người, khoảng 200k": AI (Gemini/Claude) nghĩ ra các món và nguyên liệu kèm khối lượng, còn **code** tra sản phẩm thật trong danh mục, đổi khối lượng ra số gói/chai cần mua, cộng tiền và so với ngân sách (vượt thì cho AI lập lại một lần kèm giá thật). AI không bao giờ đặt được id hay giá sản phẩm. Không có khóa API: ghép thực đơn từ 144 món của cơ sở dữ liệu trợ lý (món mặn + canh + rau + cơm). Giao diện cho chỉnh số lượng, bỏ chọn món, đổi thực đơn khác, rồi thêm tất cả vào giỏ (gia vị và gạo mặc định không chọn vì nhà thường có sẵn) |
| Trạng thái, chi phí | `GET /api/ai/status`, `GET /api/ai/usage` (admin) | Engine đang chạy, chỉ số chất lượng mô hình, số lượt dùng |

Chất lượng đo trên dữ liệu chưa thấy khi huấn luyện (báo cáo đầy đủ ở `ml/reports/`, cách huấn luyện ở `ml/README.md`):

| | Mô hình | Baseline "bán chạy nhất" |
|---|---|---|
| Gợi ý: hit@4 (có món đúng trong 4 gợi ý), 598 sản phẩm | 0,42 | 0,34 |
| Gợi ý: độ phủ danh mục | 0,34 | 0,01 |
| Gợi ý: đoán lại món bị giấu khỏi giỏ (completion@4) | 0,16 | 0,07 |
| Gợi ý: trùng nhóm hàng với món đã có (same_kind@4, thấp là tốt) | 0 | |
| Trợ lý: đúng ý định, 2.100 câu sinh tự động (mẫu câu chưa thấy) | 0,83 | |
| Trợ lý: đúng ý định, 43 câu viết tay độc lập | 0,95 | |
| Trợ lý: đúng món ăn (144 món) / đúng sản phẩm đứng đầu (598 sản phẩm) | 1,00 / 0,92 | |

**Lưu ý trung thực:** dữ liệu huấn luyện là dữ liệu **mô phỏng** (giỏ hàng sinh từ các "tình huống mua sắm" của người Việt, câu hỏi sinh từ mẫu câu có
nhiễu gõ sai), vì cửa hàng demo chưa có đơn thật. Các chỉ số trên cho biết mô hình học được cấu trúc đó, không phải hành vi khách thật. Khi có đơn thật:
đưa vào `ml/data/baskets.json` rồi chạy lại `python ml/train_recommender.py`. Trợ lý là mô hình thống kê nhỏ chạy trên mẫu câu đã định, **không phải
mô hình ngôn ngữ sinh văn bản**: câu quen thì trả lời đúng và nhanh (vài ms), câu lạ thì hỏi lại hoặc từ chối chứ không đoán bừa.

Chọn engine bằng biến môi trường `AI_ENGINE` (đặt trong `.env`, không đưa khóa lên git), rồi `docker compose up -d --build ai-service`:

```
AI_ENGINE=local                     # mặc định: mô hình tự huấn luyện, không cần khóa
AI_ENGINE=llm                       # dùng API mô hình ngôn ngữ bên ngoài (gọi bằng requests, không cần SDK)
AI_API_KEY=...                      # khóa Gemini (hoặc Anthropic); thiếu khóa thì tự dùng mô hình cục bộ
AI_MODEL=gemini-3-flash-preview     # tùy chọn; mặc định theo nhà cung cấp (Anthropic: claude-haiku-5-5)
AI_FALLBACK_MODELS=gemini-3.1-flash-lite   # tùy chọn: model thử tiếp khi model chính báo bận
AI_THINKING=low                     # tùy chọn: mức suy nghĩ của Gemini 3 (minimal|low|medium|high|off), thấp = nhanh hơn
AI_PROVIDER=gemini                  # tùy chọn: gemini | anthropic, bỏ trống = tự nhận theo tên model/dạng khóa
AI_CATALOG_TTL=15                   # tùy chọn: số giây lưu đệm danh mục (598 sản phẩm) khi trợ lý đọc; 0 = luôn đọc mới
```

Chế độ `llm` dùng một lớp dịch trong `services/utility/ai-service/llm.py`: phần còn lại của service nói chuyện bằng định dạng Anthropic Messages
(khối `text`/`tool_use`/`tool_result`), còn với Gemini lớp này tự dịch sang `generateContent` (function calling, `thoughtSignature`) và dịch ngược lại.
Lỗi tạm thời (429/5xx) được thử lại một lần rồi chuyển sang model dự phòng; nếu API vẫn không dùng được thì gợi ý chuyển sang lịch sử mua chung,
còn trợ lý chat và thực đơn chuyển sang mô hình cục bộ (`fallback: true`), khách không thấy lỗi. Khóa chỉ nằm trong `.env` (đã được `.gitignore`), không có trong log.

Nếu thiếu tệp mô hình, service vẫn chạy bằng phương án dự phòng (gợi ý theo lịch sử mua chung, chat tìm theo từ khóa).
Kiểm thử: `python tests/model_test.py` (offline, kiểm tra mô hình), `python tests/ai_local_test.py` (API local qua gateway),
`python tests/fake_llm.py` rồi `python tests/ai_test.py` (chế độ llm với API giả, cả định dạng Anthropic lẫn Gemini, xem đầu file test).
Nếu thêm service vào hệ thống đã chạy từ trước, database `ai_db` được tự tạo khi service khởi động.

## Giao diện & chế độ tối

Giao diện dùng HTML/CSS/JS thuần, màu sắc nằm trong các biến CSS ở đầu `frontend/assets/css/base.css`: một khối `:root` cho chế độ sáng và một khối `:root[data-theme="dark"]` cho chế độ tối.

- **Chuyển giao diện**: bấm nút mặt trời/mặt trăng. Lựa chọn lưu ở `localStorage` (khóa `thx_theme`); chưa chọn thì theo `prefers-color-scheme` của hệ điều hành. `assets/js/theme.js` chạy ngay trong `<head>` nên trang không bị nháy sáng khi tải.
- **Thêm màu mới**: dùng biến (`var(--surface)`, `var(--ink)`, `var(--link)`...) thay cho mã màu cố định, và khai báo giá trị ở cả hai khối. Màu nền nút/nhãn (`--leaf`, `--chili-fill`) tách khỏi màu chữ (`--link`, `--chili`) để chữ vẫn đủ tương phản ở chế độ tối.
- **Ngoại lệ có chủ ý**: hóa đơn bán tại quầy luôn nền giấy trắng (khai báo lại biến trong `.receipt`), còn `pay.html` (cổng thanh toán giả lập, đóng vai ngân hàng bên ngoài) có bảng màu xanh dương riêng nhưng vẫn đổi sáng/tối theo nút chuyển.

## Cách chạy

**Nhanh nhất trên Windows**: bấm đúp `chay_du_an.bat`. File này tự mở Docker Desktop nếu đang tắt, build và chạy toàn bộ service, chờ hệ thống sẵn sàng rồi mở trình duyệt vào cửa hàng. Nếu máy chưa có Docker mà có Python thì tự chuyển sang chế độ local (Cách 2). Dừng bằng `dung_du_an.bat` (giữ nguyên dữ liệu). Cổng lấy từ `WEB_PORT` trong `.env`.

### Cách 1 — Docker Compose (PostgreSQL + RabbitMQ + Registry)

Yêu cầu: Docker Desktop.

```bash
docker compose up -d --build
docker compose up -d --scale product-service=2     # tùy chọn: chạy 2 instance, gateway tự cân bằng tải
```

| Địa chỉ | Nội dung |
|---|---|
| http://localhost:8080 | Cửa hàng |
| http://localhost:8080/admin/ | Trang quản trị (mục "Trạng thái dịch vụ" có danh bạ registry) |
| http://localhost:8080/api-docs.html | Hợp đồng dịch vụ OpenAPI + WSDL |
| http://localhost:8000/api/health | Sức khỏe các service (gọi thẳng gateway) |
| http://localhost:15672 | RabbitMQ Management (`grocery` / `grocery`) |
| `localhost:5433` | PostgreSQL (`grocery` / `grocery`), 9 database `*_db` |

Dừng: `docker compose down` · Xóa sạch dữ liệu: `docker compose down -v` · Log: `docker compose logs -f order-service`

### Cách 2 — Chạy local không cần Docker

Yêu cầu: Python 3.10 trở lên.

```bash
pip install -r requirements-local.txt
python run_local.py                    # thêm --reset để xóa dữ liệu cũ
python run_local.py --scale product=2  # chạy 2 instance product-service
```

Mở http://localhost:8000 (cửa hàng), http://localhost:8000/admin/ (quản trị), http://localhost:8000/api-docs.html (hợp đồng).
Chế độ này dùng SQLite riêng cho từng service (thư mục `data/`) và event bus qua HTTP thay cho RabbitMQ
(mỗi service nhận sự kiện ở một instance, giống competing consumers); registry, hợp đồng và SOAP hoạt động như bản Docker.

## Tài khoản & dữ liệu mẫu

| Vai trò | Email | Mật khẩu |
|---|---|---|
| Quản trị viên | admin@taphoa.vn | Admin@123 |
| Nhân viên | staff@taphoa.vn | Staff@123 |
| Khách hàng | khach@taphoa.vn | Khach@123 |

13 danh mục, 598 sản phẩm (có mã vạch, vài sản phẩm sắp hết / hết hàng), 3 nhà cung cấp, mã giảm giá
`WELCOME10`, `GIAM20K`, `SALE50K`, `VIP15` (mã riêng). Mã vạch thử POS: `8930000000295` (Coca-Cola lon).
Danh mục sinh từ `common/catalog/` (82 nhóm hàng: gạo, nước mắm, sữa, bia, rau củ, thịt cá, đồ gia dụng...); 55 sản phẩm gốc giữ nguyên SKU và mã vạch.
**Nâng cấp từ bản 55 sản phẩm:** không cần xóa dữ liệu. Khi khởi động, `product-service` tự thêm các SKU còn thiếu (theo SKU) và `inventory-service`
tự tạo dòng tồn kho cho sản phẩm mới (chạy nền, vài chục giây); dữ liệu, giá và tồn kho đã sửa của sản phẩm cũ được giữ nguyên.

### Ảnh sản phẩm

Ảnh nằm trong `common/catalog/images.json` (SKU → URL) và được `product-service` gắn vào các sản phẩm **chưa có ảnh** khi khởi động
(một lần cho mỗi phiên bản tệp; không ghi đè ảnh quản trị viên đã đặt, xóa ảnh thì không tự quay lại). Ảnh được tải trực tiếp từ nguồn gốc (không lưu trong repo):

- **Open Food Facts** (`images.openfoodfacts.org`): ảnh bao bì thật của sản phẩm đóng gói, giấy phép CC BY-SA, ghép theo thương hiệu và tên sản phẩm.
- **Wikipedia / Wikimedia Commons** (`upload.wikimedia.org`): ảnh minh họa cho rau củ, trái cây, thịt cá, gạo, đậu, gia vị... và một số thương hiệu phổ biến;
  giấy phép tự do (CC BY-SA hoặc phạm vi công cộng, tác giả ghi ở trang tệp trên Commons).

Hiện cả 598 sản phẩm đều có ảnh: 15 ảnh bao bì thật từ Open Food Facts, còn lại là ảnh minh họa từ Wikipedia/Commons chọn theo từng loại hàng (Open Food Facts có rất ít hàng Việt nên phần lớn là ảnh cùng loại chứ không phải đúng bao bì, ví dụ mọi loại gạo thơm dùng chung một ảnh gạo, các nhãn mì gói dùng chung ảnh mì gói). `scripts/build_images.py` gộp các tệp nguồn thành `images.json`. Muốn thay ảnh: sửa trong trang quản trị
(ô "Ảnh (URL)") hoặc cập nhật `images.json` rồi tăng `version`. Trình duyệt cần truy cập được các máy chủ ảnh nói trên.

## Kiểm thử

```bash
pip install requests lxml                                  # lxml để kiểm tra SOAP theo XSD (không bắt buộc)
python tests/e2e_test.py                                   # local: http://localhost:8000
GATEWAY_URL=http://localhost:8080 python tests/e2e_test.py # Docker, qua nginx
# Windows PowerShell: $env:GATEWAY_URL="http://localhost:8080"; python tests/e2e_test.py
python scripts/export_contracts.py --check                 # hợp đồng trong contracts/ có khớp code không
```

197 kiểm thử end-to-end: bảo mật & phân quyền, tìm kiếm, giỏ hàng, mã giảm giá, Saga đặt hàng và bù trừ, vòng đời đơn,
thanh toán ví tự xác nhận đơn qua sự kiện, hủy & hoàn tiền, POS, kho, báo cáo, thông báo, rate limiting,
**tính năng AI** (gợi ý, chat, mô hình cục bộ / dự phòng), **Service Registry** (đăng ký, phân lớp, cân bằng tải), **hợp đồng OpenAPI** (đủ mô tả, không lộ API nội bộ,
khớp file `contracts/`) và **SOAP/WSDL** (3 thao tác, SOAP Fault, chặn DTD, hợp lệ theo XSD).

## Kịch bản demo gợi ý

1. `/admin/#system`: 9 service + registry đều UP, xem danh bạ instance và lớp dịch vụ.
2. `/api-docs.html`: mở hợp đồng order-service (task) và inventory-service (entity); tab api-gateway gửi thử SOAP.
3. Khách tìm "nuoc mam", thêm giỏ, áp `WELCOME10`, đặt hàng COD; RabbitMQ Management thấy message `order.created`.
4. Đặt đơn bằng Xanh Pay → thanh toán → đơn tự "Đã xác nhận" (sự kiện `payment.completed`, choreography).
5. Đặt sản phẩm hết hàng qua API → 409, không có đơn rác (Saga bù trừ, orchestration).
6. Nhân viên xử lý đơn; POS quét `8930000000295`, in hóa đơn.
7. `docker compose up -d --scale product-service=2` → registry thấy 2 instance, header `X-Instance` luân phiên.
8. `docker compose stop registry` → hệ thống vẫn bán hàng (địa chỉ dự phòng); `start registry` → service tự đăng ký lại.
9. `docker compose stop inventory-service` → cửa hàng vẫn xem được sản phẩm, đặt hàng báo lỗi rõ ràng.
10. Khách mở một sản phẩm: thấy "Thường được mua cùng"; bấm nút **Trợ lý mua sắm** hỏi "nấu canh chua cho 4 người cần mua gì?" rồi bấm **Thêm** vào giỏ.

## Xử lý sự cố

- **Cổng đã bị dùng** (8000, 8080, 5433, 15672): tạo file `.env` cạnh `docker-compose.yml` và đổi `WEB_PORT`, `GATEWAY_PORT`, `POSTGRES_PORT`, `RABBITMQ_UI_PORT` (xem `.env.example`). Cổng AMQP 5672 của RabbitMQ không mở ra máy nên không bị trùng.
- **Service khởi động lại vài lần lúc đầu**: PostgreSQL / RabbitMQ / registry chưa sẵn sàng, service tự kết nối lại sau 30–60 giây.
- **Dữ liệu mẫu ban đầu**: `docker compose down -v` hoặc `python run_local.py --reset`.
- **Triển khai thật**: sao chép `.env.example` thành `.env`, đặt `JWT_SECRET`, `INTERNAL_API_KEY`, mật khẩu DB / RabbitMQ.
