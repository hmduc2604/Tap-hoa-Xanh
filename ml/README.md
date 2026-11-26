# Huấn luyện mô hình AI cho Tạp Hóa Xanh

Hai mô hình nhỏ chạy trong `ai-service` (suy luận bằng Python thuần, không cần numpy/scikit-learn khi chạy). Thư mục này chứa dữ liệu,
mã huấn luyện và báo cáo. Trọng số đã huấn luyện nằm ở `services/utility/ai-service/models/` (đã commit, chạy ngay không cần huấn luyện).

```bash
pip install -r ml/requirements.txt          # chỉ để huấn luyện lại
python ml/generate_baskets.py               # sinh 30.000 giỏ hàng mô phỏng -> ml/data/baskets.json
python ml/train_recommender.py              # -> models/recommender.json + ml/reports/recommender.json
python ml/generate_utterances.py            # sinh câu hỏi mô phỏng -> ml/data/utterances.json
python ml/train_assistant.py                # -> models/assistant.json + ml/reports/assistant.json
python tests/model_test.py                  # kiểm thử mô hình đã huấn luyện
```

Huấn luyện mất vài chục giây trên CPU. Sau khi huấn luyện lại, build lại image: `docker compose up -d --build ai-service`.

## 1. Gợi ý "thường mua cùng" (`train_recommender.py`)

- **Dữ liệu:** danh mục 598 sản phẩm (`common/catalog/`) chia thành 82 **nhóm hàng** (gạo, nước mắm, sữa tươi, bia...). `generate_baskets.py` sinh 30.000 giỏ
  hàng từ các "tình huống mua sắm" (nấu cơm, canh chua, tiệc bia, bữa sáng, giặt giũ, chăm em bé...): mỗi tình huống chọn **một** sản phẩm cho mỗi nhu cầu
  (không ai mua ba loại nước mắm cùng lúc), có độ phổ biến từng SKU, thói quen trung thành thương hiệu và mua ngẫu hứng. Chia 70/15/15 (huấn luyện / kiểm định / kiểm tra).
- **Mô hình:** (1) xác suất có điều kiện P(j|i) đếm từ giỏ hàng (giữ top 30 món đi kèm của mỗi sản phẩm); (2) mạng MLP 598 → 128 → 598 học "hoàn thiện giỏ hàng": nhận giỏ
  hàng một phần (multi-hot), dự đoán các món còn thiếu. Điểm cuối là tổng pha trộn, trọng số và mức giảm điểm cho hàng bán quá chạy (`alpha`) chọn trên tập kiểm định.
  Khi suy luận mỗi nhóm hàng chỉ giữ một gợi ý, và không gợi ý hàng cùng nhóm với món đã có (bia Tiger không kéo theo bia Heineken). Lift và embedding
  PPMI-SVD (kiểu item2vec) cũng được huấn luyện để so sánh nhưng không dùng vì không hơn trên dữ liệu này.
- **Đánh giá (tập kiểm tra 4.500 giỏ):** hit@4, precision@4, độ phủ danh mục, "hoàn thiện giỏ" (giấu một món, xem 4 gợi ý có đoán lại đúng không) và
  `same_kind@4` (tỉ lệ gợi ý trùng nhóm hàng với món đã có, càng thấp càng tốt).

| Mô hình | hit@4 | precision@4 | độ phủ | completion@4 | same_kind@4 |
|---|---|---|---|---|---|
| Bán chạy nhất (baseline) | 0,343 | 0,112 | 0,01 | 0,067 | 0 |
| Xác suất có điều kiện | 0,429 | 0,143 | 0,32 | 0,137 | 0 |
| MLP | 0,423 | 0,139 | 0,23 | 0,170 | 0 |
| **Pha trộn (đang dùng)** | 0,420 | 0,138 | 0,34 | 0,164 | 0 |

So với bản 55 sản phẩm, bài toán khó hơn nhiều (598 lựa chọn thay vì 55, nhiều nhãn hiệu thay thế nhau) nên hit@4 tuyệt đối thấp hơn; điều cần nhìn là mức hơn baseline
(hit@4 gấp 1,2 lần, hoàn thiện giỏ gấp 2,4 lần, phủ 34% danh mục thay vì 1%). Pha trộn kém xác suất có điều kiện đơn lẻ một chút ở hit@4 nhưng phủ rộng hơn và đoán lại
món bị giấu tốt hơn; lợi thế của MLP nằm ở gợi ý **theo cả giỏ hàng** (trang giỏ hàng gửi `?cart=`).
- **Suy luận:** `local_model.py`. Điểm của mô hình được cộng thêm `1,2·n/(n+10)` với n là số đơn thật đã mua cặp sản phẩm đó (bảng `co_purchases`,
  cập nhật theo sự kiện `order.completed`). Khoảng 20 đơn mua chung là đủ đẩy một cặp lên đầu, nên hệ thống tự thích nghi dần với khách thật.
  Món điểm thấp (< 0,2) bị loại thay vì gợi ý bừa. Mô hình khóa theo **SKU** nên đổi id sản phẩm không ảnh hưởng.
  Sản phẩm mới thêm sau khi huấn luyện (chưa có trong mô hình) chưa được gợi ý cho đến khi huấn luyện lại hoặc có đơn thật.

## 2. Trợ lý mua sắm (`train_assistant.py`)

- **Dữ liệu:** `generate_utterances.py` sinh ~9.800 câu huấn luyện (và 2.100 câu kiểm tra) cho 14 ý định từ mẫu câu + tên sản phẩm/món ăn thật + cách gọi khác + tiền tố/hậu tố +
  tiếng lóng + nhiễu (gõ sai, bỏ dấu 35%). Mẫu câu, sản phẩm và món ăn được **giữ riêng cho tập kiểm tra** để đo khả năng khái quát hóa,
  không chỉ nhớ lại câu đã học.
- **Mô hình:** đặc trưng TF-IDF (từ, cặp từ, n-gram ký tự 3–4, chịu bỏ dấu và gõ sai) → hồi quy logistic đa lớp. Trọng số lưu JSON.
  Dưới ngưỡng tin cậy (0,45) mô hình không "đoán": trợ lý hỏi lại hoặc dùng thực thể trong câu để suy ra ý định.
- **Trích thực thể (`nlu.py`):** món ăn (khớp cụm từ, chịu gõ sai nhẹ), số người, ngân sách ("dưới 100k", "1,5 triệu"), sản phẩm trong danh mục
  đang bán (TF-IDF có chịu gõ sai, bỏ từ khung câu riêng cho từng ý định).
- **Kiến thức món ăn (`knowledge.py`):** 144 món (`knowledge.py` và `dishes_extra.py`: món Việt ba miền, món chay, món nhậu, ăn sáng, lẩu, tráng miệng...) → nguyên liệu viết bằng **từ khóa**, không gắn cứng id sản phẩm; khi trả lời, `assistant.py` tra từ khóa
  trong danh mục đang bán nên thêm/đổi sản phẩm không cần huấn luyện lại. Nguyên liệu cửa hàng không bán được báo rõ là "cần mua thêm ở nơi khác".
  Số lượng tính từ khẩu phần mỗi người và quy cách bán (khay 500g, hộp 10 quả...).

| Tập đánh giá | số câu | accuracy | macro-F1 |
|---|---|---|---|
| Sinh tự động, mẫu câu chưa thấy | 2.100 | 0,828 | 0,838 |
| Viết tay độc lập (`handwritten_eval.py`) | 43 | 0,953 | 0,966 |
| Câu mới viết sau cùng (`tests/model_test.py`) | 26 | 0,96 | |

Trích thực thể: món ăn 1,00; số người 0,98; ngân sách 0,99; sản phẩm đúng đứng đầu 0,92 (top 3: 0,94) trên danh mục 598 sản phẩm. Yếu nhất là `find_product` (F1 0,53),
`about_bot`, `greeting` và `recipe` trên tập sinh tự động vì các ý định này có nhiều câu ngắn dễ lẫn nhau (xem `ml/reports/assistant.json`).
Câu ngoài phạm vi (`out_of_scope`) là loại khó khái quát nhất vì không giới hạn được. Tìm sản phẩm ưu tiên khớp theo **tên/thương hiệu** rồi mới đến tên nhóm hàng
("nước mắm" không còn kéo theo "mắm tôm"). Với danh mục lớn, `ai-service` đọc toàn bộ danh mục theo trang và lưu đệm `AI_CATALOG_TTL` giây (mặc định 15, đặt 0 để tắt).
Tập viết tay và tập "câu mới" ít câu, chỉ mang tính tham khảo; hai tập này đã được xem khi chỉnh mã nên không hoàn toàn độc lập.

## Giới hạn cần biết

- Dữ liệu là **mô phỏng**: chỉ số đo khả năng học lại cấu trúc do người viết dữ liệu đặt ra, không phải hành vi khách thật. Có đơn thật thì huấn luyện lại bằng
  `python ml/train_recommender.py --baskets <tệp JSON {"baskets": [[sku, ...], ...]}>`.
- Trợ lý **không phải mô hình ngôn ngữ sinh văn bản**: câu trả lời soạn từ mẫu và dữ liệu thật, hiểu tốt các dạng câu hỏi mua sắm đã học, không trò chuyện tự do.
  Cần trò chuyện tự do thì đặt `AI_ENGINE=llm` kèm `AI_API_KEY`.
