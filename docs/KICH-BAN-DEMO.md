# Kịch bản demo Tạp Hóa Xanh (khoảng 12 phút)

Đi kèm slide `docs/BaoCao-TapHoaXanh.pptx` (21 slide) và bản giải thích AI `docs/AI-TapHoaXanh.pdf`.

## 1. Chuẩn bị trước giờ báo cáo

1. Bật Docker Desktop, bấm đúp `chay_du_an.bat` (hoặc `docker compose up -d`). Chờ http://localhost:8000/api/health báo `UP` đủ 9 service.
2. Muốn dữ liệu sạch (không còn đơn hàng, giỏ hàng làm thử): `docker compose down -v` rồi `docker compose up -d --build`. **Lệnh này xóa hết đơn đã tạo.**
3. File `.env` có `AI_ENGINE=llm` và `AI_API_KEY` thì AI chạy bằng Gemini; thiếu khóa hoặc Gemini lỗi thì tự dùng mô hình cục bộ, demo vẫn chạy bình thường.
4. Mở sẵn 3 tab: cửa hàng http://localhost:8080 (đăng nhập khách), quản trị http://localhost:8080/admin/ (cửa sổ ẩn danh, đăng nhập admin), http://localhost:8000/api/health.
5. Mạng: ảnh sản phẩm tải từ Wikipedia và Open Food Facts. Không có mạng thì hiện biểu tượng thay ảnh, các chức năng khác không ảnh hưởng.
6. Trước khi đứng lên: thử một lần "Thực đơn AI" để Gemini đã "ấm" (lượt đầu có thể mất 10–16 giây).

| Vai trò | Email | Mật khẩu |
|---|---|---|
| Quản trị viên | admin@taphoa.vn | Admin@123 |
| Nhân viên | staff@taphoa.vn | Staff@123 |
| Khách hàng | khach@taphoa.vn | Khach@123 |

Mã giảm giá: `WELCOME10`, `GIAM20K`, `SALE50K`. Mã vạch thử POS: `8930000000295` (Coca-Cola lon).

## 2. Luồng demo

| # | Phút | Làm gì | Điều cần nói |
|---|---|---|---|
| 1 | 1 | Slide 5, rồi trang quản trị, mục "Trạng thái dịch vụ" | 9 service chia lớp task/entity/utility, mỗi service một CSDL, tự đăng ký vào Service Registry |
| 2 | 2 | Cửa hàng: tìm `nuoc mam` (không dấu), bật dark mode, thêm vào giỏ, mở giỏ xem khung "mua kèm" | Tìm không dấu; giỏ luôn lấy giá và tồn kho mới nhất từ product-service; gợi ý mua kèm là mô hình AI tự huấn luyện |
| 3 | 2 | "🍳 Thực đơn AI": gõ `Bữa tối cho 4 người, có món canh, khoảng 200k`, xem món, công thức và thanh ngân sách, chỉnh số lượng, bấm "Thêm N sản phẩm vào giỏ" | AI chỉ nghĩ món; sản phẩm, giá, số lượng và tồn kho do code tính từ dữ liệu thật; gạo và gia vị tách riêng; khách xem rồi mới thêm. Thử thêm `Nấu bún chả cho 5 người` |
| 4 | 1 | Nút "Trợ lý mua sắm" góc phải: `nước mắm dưới 40k`, `nấu canh chua cho 4 người cần mua gì` | Hiểu ý định, tính nguyên liệu theo số người, trả lời kèm thẻ sản phẩm có nút Thêm |
| 5 | 2 | Giỏ hàng, áp `WELCOME10`, thanh toán bằng ví Xanh Pay, mở chuông thông báo | Saga đặt hàng: giữ hàng, ghi nhận mã, thanh toán; sự kiện `payment.completed` tự xác nhận đơn; thông báo đi qua RabbitMQ |
| 6 | 2 | Quản trị: dashboard doanh thu, đơn vừa đặt (xác nhận, giao), POS quét `8930000000295`, kho cảnh báo sắp hết | Doanh thu cập nhật ngay; POS và online dùng chung inventory-service |
| 7 | 1 | http://localhost:8080/api-docs.html | Hợp đồng OpenAPI cho 10 thành phần và WSDL; thử gửi SOAP, gateway dịch SOAP sang REST |
| 8 | 1 | Terminal: `docker compose stop inventory-service`, tải lại trang (sản phẩm vẫn hiển thị, đặt hàng báo lỗi rõ ràng), rồi `docker compose start inventory-service` | Circuit breaker, một service chết không kéo cả hệ thống; service tự đăng ký lại khi chạy lại |

## 3. Câu hỏi thầy có thể hỏi

- **Vì sao tách microservice?** Triển khai và mở rộng riêng, một phần lỗi không làm dừng cả hệ thống (slide 3, 12).
- **Đặt hàng lỗi giữa chừng thì sao?** Saga bù trừ theo thứ tự ngược, mọi bước idempotent (slide 10).
- **Chống bán âm kho thế nào?** Giữ hàng bằng câu lệnh UPDATE có điều kiện; test 15 đơn cùng lúc tranh 6 sản phẩm chỉ bán đúng 6 (slide 18).
- **AI có tự làm không?** Gợi ý mua kèm và trợ lý do project tự huấn luyện trên dữ liệu mô phỏng (hit@4 = 0,42 so với "bán chạy nhất" = 0,34). Chat và thực đơn dùng thêm Gemini, lỗi thì tự về mô hình cục bộ. AI không quyết giá hay mã sản phẩm.
- **Khóa API để đâu?** Chỉ trong file `.env` trên máy, đã nằm trong `.gitignore`, không đưa lên git.
- **Hạn chế?** Thanh toán và email đang mô phỏng; dữ liệu huấn luyện là mô phỏng nên chỉ số AI chưa phản ánh khách thật; registry một instance (slide 20).

## 4. Nếu có sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Trang báo 502 hoặc không tải được dữ liệu | `docker compose ps` xem service nào chưa `running`; `docker compose logs -f api-gateway`; thử `docker compose restart frontend` |
| Thực đơn AI chậm hoặc báo "AI đang bận" | Chờ vài giây; hệ thống tự dùng thực đơn cục bộ (trang ghi rõ nguồn). Có thể nói đây chính là cơ chế dự phòng |
| Ảnh sản phẩm không hiện | Do không có mạng; hiện biểu tượng thay thế, các chức năng khác bình thường |
| Quên mật khẩu hoặc dữ liệu lộn xộn | Dùng bảng tài khoản ở mục 1; hoặc đặt lại dữ liệu bằng `docker compose down -v` |
| Chạy không có Docker | `pip install -r requirements-local.txt`, rồi `python run_local.py --reset`, mở http://localhost:8000 |
