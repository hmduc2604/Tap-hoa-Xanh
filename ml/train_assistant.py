"""Huấn luyện bộ hiểu ngôn ngữ cho trợ lý mua sắm (phân loại ý định) và đánh giá toàn bộ pipeline hiểu câu hỏi.

  1. Đặc trưng TF-IDF từ common/nlp.py (từ, cặp từ, n-gram ký tự) - cùng code với lúc chạy thật.
  2. Hồi quy logistic đa lớp (scikit-learn), lưu trọng số vào JSON để ai-service suy luận bằng Python thuần.
  3. Đánh giá 3 lớp:
       a) tập kiểm tra sinh tự động, dùng mẫu câu / sản phẩm / món CHƯA thấy khi huấn luyện;
       b) tập câu tự viết tay (ml/handwritten_eval.py), độc lập với bộ sinh câu để tránh "tự chấm bài mình";
       c) trích thực thể: món ăn, số người, ngân sách, tìm sản phẩm trong danh mục.

    python ml/train_assistant.py
"""
import json
import os
import sys
import time
from collections import Counter

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "services", "utility", "ai-service"))
import nlu  # noqa: E402
from common.nlp import features, vectorize  # noqa: E402
from common.seed_data import CATEGORIES, PRODUCTS  # noqa: E402
from common.utils import strip_accents  # noqa: E402
from generate_utterances import generate  # noqa: E402
from handwritten_eval import HANDWRITTEN  # noqa: E402
from knowledge import DISHES, FAQ, LABELS, MEAL_WORDS, PREFER  # noqa: E402

OUT_MODEL = os.path.join(ROOT, "services", "utility", "ai-service", "models", "assistant.json")
OUT_REPORT = os.path.join(ROOT, "ml", "reports", "assistant.json")
THRESHOLD = 0.45  # dưới ngưỡng này trợ lý hỏi lại thay vì đoán


def build_vocab(texts, min_df=3, max_features=6000):
    df = Counter()
    for t in texts:
        df.update(features(t).keys())
    kept = [f for f, c in df.most_common() if c >= min_df][:max_features]
    kept.sort()
    n = len(texts)
    idf = [float(np.log((n + 1) / (df[f] + 1)) + 1) for f in kept]
    return kept, idf


def to_matrix(texts, vocab_index, idf):
    rows, cols, vals = [], [], []
    for r, t in enumerate(texts):
        for c, v in vectorize(t, vocab_index, idf).items():
            rows.append(r)
            cols.append(c)
            vals.append(v)
    return csr_matrix((vals, (rows, cols)), shape=(len(texts), len(vocab_index)))


def seed_catalog():
    """Danh mục demo dạng sản phẩm đang bán (đúng thứ tự seed = thứ tự phổ biến) để đo độ chính xác tìm sản phẩm."""
    return [{"id": i, "sku": p[1], "name": p[3], "brand": p[4], "unit": p[5], "category_name": CATEGORIES[p[0]][0]}
            for i, p in enumerate(PRODUCTS, 1)]


def parse_price_expected(text):
    t = strip_accents(text)
    for suffix, mult in (("trieu", 1_000_000), ("k", 1000), ("nghin", 1000), ("ngan", 1000)):
        if suffix in t.replace(" ", ""):
            digits = "".join(ch for ch in t.split(suffix)[0] if ch.isdigit())
            if digits:
                return int(digits) * mult
    digits = "".join(ch for ch in t if ch.isdigit())
    return int(digits) if digits else None


def predict(model, text):
    return model.predict(text)


def evaluate_intents(model, rows, label):
    y_true, y_pred, confident = [], [], 0
    for r in rows:
        top = predict(model, r["text"])
        y_true.append(r["intent"])
        y_pred.append(top[0][0])
        confident += top[0][1] >= THRESHOLD
    acc = float(np.mean([a == b for a, b in zip(y_true, y_pred)]))
    macro = float(f1_score(y_true, y_pred, average="macro"))
    answered = [a == b for a, b, r in zip(y_true, y_pred, rows) if predict(model, r["text"])[0][1] >= THRESHOLD]
    return {"samples": len(rows), "accuracy": round(acc, 4), "macro_f1": round(macro, 4),
            "answered_ratio": round(confident / len(rows), 4),
            "accuracy_when_answered": round(float(np.mean(answered)) if answered else 0, 4)}, y_true, y_pred


def evaluate_slots(model_data, rows):
    dish_index = nlu.DishIndex(model_data["dishes"])
    catalog = nlu.CatalogIndex(seed_catalog(), model_data["stopwords"])
    out = {}
    d = [r for r in rows if "dish" in r]
    out["dish_accuracy"] = round(float(np.mean([bool(dish_index.find(r["text"])) and dish_index.find(r["text"])["name"] == r["dish"] for r in d])), 4)
    s = [r for r in rows if "servings" in r]
    out["servings_accuracy"] = round(float(np.mean([nlu.parse_servings(r["text"]) == r["servings"] for r in s])), 4) if s else None
    p = [r for r in rows if "price" in r]
    out["price_accuracy"] = round(float(np.mean([nlu.parse_price(r["text"]) == parse_price_expected(r["price"]) for r in p])), 4)
    pr = [r for r in rows if "skus" in r and r["intent"] in ("find_product", "price_query", "bought_together")]
    top1 = top3 = 0
    for r in pr:
        found = [x[0]["sku"] for x in catalog.search(r["text"], limit=3, min_score=0.5, intent=r["intent"])]
        top1 += bool(found) and found[0] in r["skus"]
        top3 += any(s in r["skus"] for s in found)
    out["product_top1"] = round(top1 / len(pr), 4)
    out["product_top3"] = round(top3 / len(pr), 4)
    out["samples"] = {"dish": len(d), "servings": len(s), "price": len(p), "product": len(pr)}
    return out


def main():
    t0 = time.time()
    data, stopwords, _ = generate()
    train, test = data["train"], data["test"]
    classes = sorted({r["intent"] for r in train})
    vocab, idf = build_vocab([r["text"] for r in train])
    index = {f: i for i, f in enumerate(vocab)}
    x_train = to_matrix([r["text"] for r in train], index, idf)
    clf = LogisticRegression(C=12, max_iter=500)
    clf.fit(x_train, [r["intent"] for r in train])
    assert list(clf.classes_) == classes
    model_data = {
        "kind": "intent-classifier", "version": 1, "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "classes": classes, "vocab": vocab, "idf": [round(v, 4) for v in idf],
        "coef": np.round(clf.coef_, 3).tolist(), "intercept": np.round(clf.intercept_, 3).tolist(),
        "threshold": THRESHOLD, "stopwords": stopwords, "dishes": DISHES, "faq": FAQ, "meal_words": MEAL_WORDS,
        "labels": LABELS, "prefer": PREFER,
    }
    model = nlu.IntentModel(model_data)  # đánh giá bằng đúng code suy luận của service (đã làm tròn trọng số)

    train_metrics, _, _ = evaluate_intents(model, train[:1500], "train")
    test_metrics, yt, yp = evaluate_intents(model, test, "test")
    hand_rows = [{"text": t, "intent": i} for t, i in HANDWRITTEN]
    hand_metrics, ht, hp = evaluate_intents(model, hand_rows, "handwritten")
    slots = evaluate_slots(model_data, test)
    per_class = classification_report(yt, yp, output_dict=True, zero_division=0)
    wrong = [(t, i, predict(model, t)[0][0]) for t, i in HANDWRITTEN if predict(model, t)[0][0] != i]

    print(f"Huấn luyện: {len(train)} câu, {len(classes)} ý định, {len(vocab)} đặc trưng ({time.time() - t0:.1f}s)\n")
    print(f"{'Tập đánh giá':44} {'số câu':>7} {'accuracy':>9} {'macro-F1':>9} {'trả lời':>8}")
    for name, m in (("huấn luyện (mẫu 1500 câu)", train_metrics), ("kiểm tra sinh tự động (mẫu câu chưa thấy)", test_metrics),
                    ("viết tay độc lập", hand_metrics)):
        print(f"{name:44} {m['samples']:7d} {m['accuracy']:9.3f} {m['macro_f1']:9.3f} {m['answered_ratio']:8.2f}")
    print(f"\nTrích thực thể (tập kiểm tra): {slots}")
    print("\nTheo từng ý định (tập kiểm tra sinh tự động), F1:")
    for c in classes:
        print(f"  {c:16} {per_class[c]['f1-score']:.3f}")
    if wrong:
        print("\nCâu viết tay dự đoán sai:")
        for t, true, pred in wrong:
            print(f"  [{true} -> {pred}] {t}")

    os.makedirs(os.path.dirname(OUT_MODEL), exist_ok=True)
    model_data["metrics"] = {"test": test_metrics, "handwritten": hand_metrics, "slots": slots}
    json.dump(model_data, open(OUT_MODEL, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump({"train": train_metrics, "test": test_metrics, "handwritten": hand_metrics, "slots": slots,
               "per_class_f1": {c: round(per_class[c]["f1-score"], 3) for c in classes},
               "handwritten_wrong": wrong}, open(OUT_REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nĐã lưu mô hình: {os.path.relpath(OUT_MODEL, ROOT)} ({os.path.getsize(OUT_MODEL) // 1024} KB)")


if __name__ == "__main__":
    main()
