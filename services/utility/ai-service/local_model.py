"""Mô hình gợi ý "thường mua cùng" đã huấn luyện sẵn (ml/train_recommender.py), suy luận bằng Python thuần.

Mô hình gồm hai phần pha trộn theo trọng số chọn trên tập kiểm định:
  - bảng xác suất có điều kiện P(j | i) (thống kê từ giỏ hàng),
  - mạng nơ-ron MLP "hoàn thiện giỏ hàng": nhận cả giỏ (multi-hot) và dự đoán món còn thiếu.
Mô hình nhận SKU, không nhận id, nên danh mục có thể đổi id mà không cần huấn luyện lại. Hàng mới chưa có trong
mô hình thì không được mô hình gợi ý (service sẽ dùng phương án dự phòng); lịch sử đơn thật (co_purchases) được cộng
thêm vào điểm nên mô hình tự "học" dần từ dữ liệu thật mà không cần huấn luyện lại ngay.
"""
import math

from nlu import load_json

POP_FLOOR = 0.002  # phải khớp ml/train_recommender.py
MIN_SCORE = 0.2  # điểm (0..1) tối thiểu để một món được gợi ý, tránh gợi ý bừa khi mô hình không chắc
HISTORY_WEIGHT = 1.2  # điểm cộng từ lịch sử đơn thật: 1.2 * n / (n + 10); khoảng 20 đơn mua chung là đủ lọt top gợi ý, vượt cả dự đoán của mô hình khi n lớn


class Recommender:
    def __init__(self, data):
        self.skus = data["skus"]
        self.index = {s: i for i, s in enumerate(self.skus)}
        n = len(self.skus)
        conf = data["conf"]
        if conf and isinstance(conf[0], list) and conf[0] and not isinstance(conf[0][0], list):  # bảng đặc (phiên bản 2)
            conf = [[[j, v] for j, v in enumerate(row) if v > 0] for row in conf]
        self.conf = [{int(j): v for j, v in row} for row in conf]  # bảng thưa: conf[i][j] = P(j | i)
        self.pop = data["pop"]
        self.alpha = data.get("alpha", 0.0)  # giảm thiên vị hàng bán chạy: điểm MLP chia cho độ phổ biến^alpha
        self.discount = [max(p, POP_FLOOR) ** self.alpha for p in self.pop]
        self.kinds = data.get("kinds") or list(range(n))  # nhóm hàng của từng SKU (không có thì coi mỗi SKU một nhóm)
        mlp = data["mlp"]
        self.w1, self.b1, self.b2 = mlp["w1"], mlp["b1"], mlp["b2"]
        w2 = mlp["w2"]  # (ẩn x n) -> chuyển vị (n x ẩn) để tính từng đầu ra nhanh hơn
        self.w2t = [[w2[h][j] for h in range(len(w2))] for j in range(n)]
        self.w_mlp = data["weights"].get("mlp", 1.0)
        self.w_conf = data["weights"].get("conf", 0.0)
        self.metrics = data.get("metrics", {})
        self.baseline = data.get("baseline", {})
        self.trained_at = data.get("trained_at")

    @classmethod
    def load(cls, path):
        return cls(load_json(path))

    def knows(self, sku):
        return sku in self.index

    def _mlp(self, given):
        hidden = list(self.b1)
        for g in given:
            row = self.w1[g]
            for h in range(len(hidden)):
                hidden[h] += row[h]
        active = [(h, x) for h, x in enumerate(hidden) if x > 0]  # ReLU: chỉ các nơ-ron đang bật mới đóng góp
        out = []
        for j in range(len(self.skus)):
            w = self.w2t[j]
            z = self.b2[j] + sum(x * w[h] for h, x in active)
            out.append((1 / (1 + math.exp(-z)) if z > -30 else 0.0) / self.discount[j])
        return out

    def score(self, given_skus):
        """Điểm 0..1 cho từng SKU trong mô hình, theo giỏ hàng (danh sách SKU). SKU lạ bị bỏ qua. Giỏ rỗng -> {}."""
        given = sorted({self.index[s] for s in given_skus if s in self.index})
        if not given:
            return {}
        m = self._mlp(given)
        c = {}
        for g in given:
            for j, v in self.conf[g].items():
                c[j] = c.get(j, 0.0) + v / len(given)
        m_max, c_max = max(max(m), 1e-9), max(max(c.values(), default=0.0), 1e-9)
        total = (self.w_mlp + self.w_conf) or 1.0
        scores = {}
        for j, sku in enumerate(self.skus):
            if j in given:
                continue
            scores[sku] = (self.w_mlp * m[j] / m_max + self.w_conf * c.get(j, 0.0) / c_max) / total
        return scores

    def recommend(self, given_skus, limit=4, history=None, allowed=None):
        """[(sku, điểm)] giảm dần, bỏ món điểm thấp.

        history: {sku: số đơn thật đã mua cùng} - cộng thêm điểm từ dữ liệu thật.
        allowed: tập SKU được phép gợi ý (ví dụ chỉ hàng còn bán); None = tất cả.
        """
        scores = self.score(given_skus)
        history = history or {}
        ranked = []
        for sku, s in scores.items():
            if allowed is not None and sku not in allowed:
                continue
            n = history.get(sku, 0)
            total = s + HISTORY_WEIGHT * n / (n + 10)
            if total >= MIN_SCORE:
                ranked.append((sku, round(total, 4)))
        ranked.sort(key=lambda x: -x[1])
        # hàng thay thế nhau (cùng nhóm hàng) chỉ hiện một món, và không gợi ý nhóm hàng khách đã có trong giỏ
        taken = {self.kinds[self.index[s]] for s in given_skus if s in self.index}
        out = []
        for sku, s in ranked:
            kind = self.kinds[self.index[sku]]
            if kind in taken:
                continue
            taken.add(kind)
            out.append((sku, s))
            if len(out) == limit:
                break
        return out

    def info(self):
        return {"kind": "mlp+conditional-probability", "products": len(self.skus), "trained_at": self.trained_at,
                "weights": {"mlp": self.w_mlp, "conf": self.w_conf}, "alpha": self.alpha, "metrics": self.metrics, "baseline": self.baseline}
