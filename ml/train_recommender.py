"""Huấn luyện mô hình gợi ý "thường mua cùng" từ giỏ hàng.

Mô hình dùng trong hệ thống gồm hai phần, pha trộn bằng trọng số chọn trên tập kiểm định:
  1. Xác suất có điều kiện P(j | i) đếm từ các giỏ hàng (mô hình thống kê, giải thích được).
  2. Mạng nơ-ron MLP (N sản phẩm -> 128 -> N sản phẩm) học "hoàn thiện giỏ hàng": nhận giỏ hàng một phần (multi-hot), dự đoán những
     món còn lại. Nhờ vậy gợi ý được cho cả giỏ nhiều món chứ không chỉ một sản phẩm.
Các phương án khác (lift, embedding PPMI-SVD kiểu item2vec) cũng được huấn luyện để so sánh, không dùng trong mô hình cuối.
Đánh giá trên tập kiểm tra chưa thấy lần nào: hit@4, precision@4, độ phủ danh mục, so với baseline "bán chạy nhất",
và bài toán "hoàn thiện giỏ" (bỏ một món, xem mô hình có gợi ý lại đúng món đó trong 4 gợi ý không).

    python ml/train_recommender.py [--baskets ml/data/baskets.json]
"""
import argparse
import itertools
import json
import os
import random
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from common.seed_data import KIND_OF, PRODUCTS  # noqa: E402

SKUS = [p[1] for p in PRODUCTS]
INDEX = {s: i for i, s in enumerate(SKUS)}
N = len(SKUS)
KIND = [KIND_OF[s] for s in SKUS]
TOPK = 30  # mỗi sản phẩm chỉ giữ 30 sản phẩm hay mua cùng nhất trong bảng xác suất (bảng thưa, mô hình gọn)
HIDDEN = 128
POP_FLOOR = 0.002  # sàn của độ phổ biến khi chia để giảm thiên vị hàng bán chạy (giống local_model.py)
ALPHAS = (0.0, 0.25, 0.5)  # mức giảm thiên vị hàng bán chạy; chọn trên tập kiểm định
DIM = 16
K = 4  # số gợi ý hiển thị
OUT_MODEL = os.path.join(ROOT, "services", "utility", "ai-service", "models", "recommender.json")
OUT_REPORT = os.path.join(ROOT, "ml", "reports", "recommender.json")


def load(path):
    baskets = json.load(open(path, encoding="utf-8"))["baskets"]
    unknown = {s for b in baskets for s in b if s not in INDEX}
    if unknown:
        raise SystemExit(f"Giỏ hàng chứa SKU không có trong danh mục: {sorted(unknown)[:5]}")
    return [[INDEX[s] for s in b] for b in baskets]


def split(baskets, seed=7):
    rng = random.Random(seed)
    idx = list(range(len(baskets)))
    rng.shuffle(idx)
    a, b = int(len(idx) * .7), int(len(idx) * .85)
    pick = lambda ids: [baskets[i] for i in ids]  # noqa: E731
    return pick(idx[:a]), pick(idx[a:b]), pick(idx[b:])


def cooccurrence(baskets):
    c = np.zeros((N, N))
    for b in baskets:
        for i, j in itertools.permutations(b, 2):
            c[i, j] += 1
    return c


class Stats:
    def __init__(self, train):
        self.n = len(train)
        self.count = np.zeros(N)
        for b in train:
            for i in b:
                self.count[i] += 1
        self.pop = self.count / self.n
        self.c = cooccurrence(train)

    def conf(self, topk=TOPK):
        """P(j | i): xác suất mua j khi đã mua i; chỉ giữ topk giá trị lớn nhất mỗi hàng (đúng như mô hình triển khai)."""
        full = self.c / np.maximum(self.count[:, None], 1)
        keep = np.argsort(-full, axis=1)[:, :topk]
        sparse = np.zeros_like(full)
        rows = np.arange(N)[:, None]
        sparse[rows, keep] = full[rows, keep]
        return sparse

    def lift(self, shrink=8.0):
        """P(j|i) / P(j), nhân hệ số c/(c+shrink) để cặp hiếm gặp không được điểm cao nhờ may rủi."""
        lift = self.conf() / np.maximum(self.pop[None, :], 1e-9)
        return lift * (self.c / (self.c + shrink))

    def embeddings(self, dim=DIM, alpha=.75):
        """PPMI với phân phối ngữ cảnh làm mượt (alpha) rồi SVD cắt hạng."""
        ctx = self.c.sum(0) ** alpha
        ctx = ctx / ctx.sum()
        total = self.c.sum()
        pij = self.c / total
        pi = self.c.sum(1) / total
        with np.errstate(divide="ignore", invalid="ignore"):
            pmi = np.log(pij / (pi[:, None] * ctx[None, :]))
        ppmi = np.nan_to_num(np.maximum(pmi, 0), neginf=0, posinf=0)
        u, s, _ = np.linalg.svd(ppmi, full_matrices=False)
        emb = u[:, :dim] * np.sqrt(s[:dim])
        return emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)


def row_norm(m):
    m = m.copy()
    np.fill_diagonal(m, 0)
    return m / np.maximum(m.max(1, keepdims=True), 1e-9)


def diverse_top(score_row, given, k=K):
    """k sản phẩm điểm cao nhất, mỗi nhóm hàng tối đa một sản phẩm và không trùng nhóm với món đã có trong giỏ.
    Hai loại nước mắm hay ba hãng sữa đặc là hàng thay thế nhau, hiển thị cả ba chỉ phí chỗ gợi ý. Cùng luật này
    được dùng trong ai-service (local_model.Recommender.recommend) nên số đo ở đây phản ánh đúng thứ người dùng thấy."""
    taken = {KIND[g] for g in given}
    out = []
    for j in np.argsort(-score_row):
        if j in given or KIND[j] in taken or not np.isfinite(score_row[j]):
            continue
        out.append(int(j))
        taken.add(KIND[j])
        if len(out) == k:
            break
    return out


def mask_self(score):
    score = score.copy()
    np.fill_diagonal(score, -np.inf)
    return score


def evaluate(score, baskets, k=K):
    """Với mỗi giỏ và mỗi sản phẩm làm "mỏ neo": gợi ý k món, trúng nếu có món nằm trong phần còn lại của giỏ."""
    score = mask_self(score)
    top = [diverse_top(score[a], [a], k) for a in range(N)]
    hits = precision = same = n = 0
    seen = set()
    for b in baskets:
        rest = set(b)
        for a in b:
            rec = top[a]
            inter = len(set(rec) & (rest - {a}))
            hits += inter > 0
            precision += inter / k
            same += sum(KIND[j] == KIND[a] for j in rec) / k
            n += 1
            seen.update(rec)
    return {"hit@4": round(hits / n, 4), "precision@4": round(precision / n, 4), "coverage": round(len(seen) / N, 4),
            "same_kind@4": round(same / n, 4)}


def multi_hot(items):
    v = np.zeros(N, dtype=np.float32)
    v[list(items)] = 1
    return v


def completion_data(baskets, rng, per_basket=5):
    """Mỗi giỏ tạo nhiều mẫu: đầu vào = tập con ngẫu nhiên của giỏ, nhãn = các món còn lại."""
    xs, ys = [], []
    for b in baskets:
        for _ in range(per_basket):
            k = rng.randint(1, len(b) - 1)
            given = rng.sample(b, k)
            xs.append(multi_hot(given))
            ys.append(multi_hot(set(b) - set(given)))
    return np.array(xs), np.array(ys)


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


class MLP:
    """Mạng 1 lớp ẩn; trọng số lưu ra JSON để suy luận bằng Python thuần trong ai-service."""

    def __init__(self, clf):
        self.w1, self.w2 = clf.coefs_
        self.b1, self.b2 = clf.intercepts_

    def predict(self, x):
        return sigmoid(np.maximum(x @ self.w1 + self.b1, 0) @ self.w2 + self.b2)


def train_mlp(train_b, seed=3, hidden=HIDDEN):
    from sklearn.neural_network import MLPClassifier
    rng = random.Random(seed)
    x, y = completion_data(train_b, rng)
    clf = MLPClassifier(hidden_layer_sizes=(hidden,), activation="relu", alpha=1e-3, batch_size=256, max_iter=40,
                        early_stopping=True, validation_fraction=.1, n_iter_no_change=6, random_state=seed)
    clf.fit(x, y)
    return MLP(clf), clf


def evaluate_completion(scorer, baskets, k=K, seed=11):
    """Bỏ ngẫu nhiên một món trong giỏ (cần giỏ >= 3 món), gợi ý từ phần còn lại, trúng nếu đoán lại đúng món bỏ."""
    rng = random.Random(seed)
    hit = n = 0
    for b in baskets:
        if len(b) < 3:
            continue
        gone = rng.choice(b)
        given = [i for i in b if i != gone]
        s = scorer(given).copy()
        s[given] = -np.inf
        hit += gone in diverse_top(s, given, k)
        n += 1
    return round(hit / n, 4)


def blend_scorer(mlp, conf, wm, wc, alpha=0.0, pop=None):
    discount = np.maximum(pop, POP_FLOOR) ** alpha if pop is not None else 1.0

    def scorer(given):
        m = mlp.predict(multi_hot(given)[None, :])[0] / discount
        c = conf[given].mean(0)
        return wm * m / max(m.max(), 1e-9) + wc * c / max(c.max(), 1e-9)
    return scorer


def train(baskets):
    train_b, val_b, test_b = split(baskets)
    st = Stats(train_b)
    emb = st.embeddings()
    conf = st.conf()
    mlp, clf = train_mlp(train_b)
    mlp_single = mlp.predict(np.eye(N, dtype=np.float32))  # hàng a = dự đoán khi giỏ chỉ có sản phẩm a
    pop = st.pop
    best_by_alpha = {}
    for alpha in ALPHAS:
        discount = np.maximum(pop, POP_FLOOR) ** alpha
        parts = {"conf": row_norm(conf), "mlp": row_norm(mlp_single / discount[None, :])}
        best, best_w = -1, None
        for wm, wc in itertools.product([0, .25, .5, .75, 1], repeat=2):
            if wm + wc == 0 or (wm == 0 and alpha > 0):
                continue
            blend = wm * parts["mlp"] + wc * parts["conf"]
            v = evaluate(blend, val_b)["precision@4"] + evaluate_completion(blend_scorer(mlp, conf, wm, wc, alpha, pop), val_b)
            if v > best:
                best, best_w = v, (wm, wc)
        best_by_alpha[alpha] = (best, best_w)
    top_v = max(v for v, _ in best_by_alpha.values())
    # giảm thiên vị hàng bán chạy càng nhiều càng tốt miễn là độ chính xác kiểm định còn >= 97% mức tốt nhất
    alpha = max(a for a, (v, _) in best_by_alpha.items() if v >= 0.97 * top_v)
    wm, wc = best_by_alpha[alpha][1]
    discount = np.maximum(pop, POP_FLOOR) ** alpha
    parts = {"conf": row_norm(conf), "mlp": row_norm(mlp_single / discount[None, :])}
    blend = row_norm(wm * parts["mlp"] + wc * parts["conf"])
    candidates = {
        "popularity (baseline)": np.tile(st.pop, (N, 1)),
        "xác suất có điều kiện": parts["conf"],
        "lift": row_norm(st.lift()),
        "embedding PPMI-SVD": row_norm(np.maximum(emb @ emb.T, 0)),
        "mạng nơ-ron MLP": row_norm(mlp_single),
        "pha trộn (mô hình dùng)": blend,
    }
    report = {name: {"validation": evaluate(sc, val_b), "test": evaluate(sc, test_b)} for name, sc in candidates.items()}
    pop_scorer = lambda given: pop  # noqa: E731
    conf_scorer = blend_scorer(mlp, conf, 0, 1)
    mlp_scorer = blend_scorer(mlp, conf, 1, 0)
    final_scorer = blend_scorer(mlp, conf, wm, wc, alpha, pop)
    report["popularity (baseline)"]["test"]["completion@4"] = evaluate_completion(pop_scorer, test_b)
    report["xác suất có điều kiện"]["test"]["completion@4"] = evaluate_completion(conf_scorer, test_b)
    report["mạng nơ-ron MLP"]["test"]["completion@4"] = evaluate_completion(mlp_scorer, test_b)
    report["pha trộn (mô hình dùng)"]["test"]["completion@4"] = evaluate_completion(final_scorer, test_b)
    return {"mlp": mlp, "conf": conf, "pop": pop, "weights": {"mlp": wm, "conf": wc}, "alpha": alpha, "iters": clf.n_iter_}, report, \
        (len(train_b), len(val_b), len(test_b))


def sparse_rows(conf):
    """Bảng xác suất thưa: với mỗi sản phẩm i, danh sách [j, P(j|i)] của các sản phẩm hay mua cùng (giảm dần)."""
    rows = []
    for i in range(N):
        js = np.argsort(-conf[i])[:TOPK]
        rows.append([[int(j), round(float(conf[i, j]), 4)] for j in js if conf[i, j] > 0])
    return rows


def r4(a):
    return np.round(np.asarray(a, dtype=float), 4).tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baskets", default=os.path.join(ROOT, "ml", "data", "baskets.json"))
    args = ap.parse_args()
    t0 = time.time()
    raw = json.load(open(args.baskets, encoding="utf-8"))
    baskets = load(args.baskets)
    model, report, sizes = train(baskets)
    print(f"Dữ liệu: {len(baskets)} giỏ ({raw.get('source', '?')}), chia train/val/test = {sizes}")
    print(f"MLP dừng sau {model['iters']} epoch. Trọng số pha trộn chọn trên tập kiểm định: {model['weights']}, giảm thiên vị hàng bán chạy alpha={model['alpha']}\n")
    print(f"{'Mô hình':28} {'hit@4':>8} {'prec@4':>8} {'phủ DM':>8} {'cùng nhóm':>10} {'hoàn thiện giỏ@4':>18}   (tập kiểm tra)")
    for name, r in report.items():
        t = r["test"]
        comp = f"{t['completion@4']:18.3f}" if "completion@4" in t else f"{'':>18}"
        print(f"{name:28} {t['hit@4']:8.3f} {t['precision@4']:8.3f} {t['coverage']:8.2f} {t['same_kind@4']:10.3f} {comp}")
    mlp = model["mlp"]
    os.makedirs(os.path.dirname(OUT_MODEL), exist_ok=True)
    final = report["pha trộn (mô hình dùng)"]["test"]
    json.dump({
        "kind": "basket-recommender", "version": 3, "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data": {"source": raw.get("source"), "baskets": len(baskets)}, "weights": model["weights"], "alpha": model["alpha"],
        "kinds": KIND,
        "skus": SKUS, "pop": r4(model["pop"]), "conf": sparse_rows(model["conf"]),
        "mlp": {"w1": r4(mlp.w1), "b1": r4(mlp.b1), "w2": r4(mlp.w2), "b2": r4(mlp.b2)},
        "metrics": final, "baseline": report["popularity (baseline)"]["test"],
    }, open(OUT_MODEL, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump({"data": {"source": raw.get("source"), "baskets": len(baskets), "split": sizes},
               "weights": model["weights"], "alpha": model["alpha"], "results": report}, open(OUT_REPORT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nĐã lưu mô hình: {os.path.relpath(OUT_MODEL, ROOT)} ({os.path.getsize(OUT_MODEL) // 1024} KB), "
          f"mất {time.time() - t0:.1f}s")
    scorer = blend_scorer(mlp, model["conf"], model["weights"]["mlp"], model["weights"]["conf"], model["alpha"], model["pop"])
    for sku in ("NM-NAMNGU-750", "CF-G7-18", "BIA-SG-LON", "OMO-36", "MI-HH-GOI", "SUA-VNM-1L"):
        i = INDEX[sku]
        s = scorer([i]).copy()
        s[i] = -np.inf
        print(f"  {PRODUCTS[i][3]}  ->  " + "; ".join(PRODUCTS[j][3] for j in diverse_top(s, [i])))


if __name__ == "__main__":
    main()
