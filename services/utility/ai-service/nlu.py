"""Hiểu câu hỏi tiếng Việt của khách: phân loại ý định (mô hình đã huấn luyện) + trích thực thể (quy tắc và tra cứu).

- IntentModel: hồi quy logistic đa lớp trên đặc trưng TF-IDF (từ, cặp từ, n-gram ký tự), suy luận bằng Python thuần.
  Trọng số do ml/train_assistant.py huấn luyện và lưu trong models/assistant.json.
- parse_servings / parse_price: số người, ngân sách trong câu ("cho 4 người", "dưới 100k", "200.000đ").
- find_dish: nhận diện món ăn trong câu, chịu gõ sai nhẹ.
- CatalogIndex: tìm sản phẩm trong danh mục đang bán theo từ khóa (chấm điểm TF-IDF, chịu gõ sai).
"""
import difflib
import json
import math
import re
from collections import Counter

from common.nlp import softmax, tokens, vectorize

VI_NUMBERS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5, "sau": 6, "bay": 7, "tam": 8, "chin": 9, "muoi": 10}


class IntentModel:
    def __init__(self, data):
        self.classes = data["classes"]
        self.vocab = {f: i for i, f in enumerate(data["vocab"])}
        self.idf = data["idf"]
        self.coef = data["coef"]  # [lớp][đặc trưng]
        self.intercept = data["intercept"]

    def predict(self, text):
        """Trả về [(ý định, xác suất)] giảm dần theo xác suất."""
        vec = vectorize(text, self.vocab, self.idf)
        scores = [b + sum(w[i] * v for i, v in vec.items()) for w, b in zip(self.coef, self.intercept)]
        probs = softmax(scores)
        return sorted(zip(self.classes, probs), key=lambda x: -x[1])


# ------------------------------------------------------------------ số người, ngân sách
_SERVINGS = re.compile(r"\b(\d{1,2}|mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi)\s*(?:nguoi|suat|phan)\b")
_FAMILY = re.compile(r"\bgia dinh\s*(\d{1,2})\b")


def parse_servings(text):
    t = " ".join(tokens(text))
    m = _SERVINGS.search(t) or _FAMILY.search(t)
    if not m:
        return None
    raw = m.group(1)
    n = int(raw) if raw.isdigit() else VI_NUMBERS.get(raw)
    return n if n and 1 <= n <= 30 else None


_PRICE_DOTTED = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+)\s*(?:d|dong|vnd)?\b")
_PRICE_UNIT = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(k|nghin|ngan|tr|trieu)\b")
_PRICE_PLAIN = re.compile(r"(?<![\d.,])(\d{4,7})\s*(?:d|dong|vnd)?\b")


def parse_price(text):
    """'dưới 100k' -> 100000, '200.000đ' -> 200000, '1 triệu' -> 1000000; không thấy -> None."""
    t = strip(text)
    m = _PRICE_DOTTED.search(t)
    if m:
        return int(re.sub(r"[.,]", "", m.group(1)))
    m = _PRICE_UNIT.search(t)
    if m:
        number = float(m.group(1).replace(",", "."))
        unit = m.group(2)
        mult = 1_000_000 if unit in ("tr", "trieu") else 1_000
        return int(number * mult)
    m = _PRICE_PLAIN.search(t)
    return int(m.group(1)) if m else None


def strip(text):
    from common.utils import strip_accents
    return strip_accents(text)


# ------------------------------------------------------------------ món ăn
def _phrases(dish):
    return [dish["name"]] + dish.get("aliases", [])


class DishIndex:
    def __init__(self, dishes):
        self.dishes = dishes
        self.by_name = {d["name"]: d for d in dishes}
        self.phrases = []  # (tokens, tên món)
        for d in dishes:
            for p in _phrases(d):
                toks = tokens(p)
                if toks:
                    self.phrases.append((toks, d["name"]))

    def find(self, text):
        """Món ăn được nhắc tới: khớp cụm từ chính xác (ưu tiên cụm dài nhất), nếu không thì khớp gần đúng (gõ sai)."""
        q = tokens(text)
        best, best_score = None, 0.0
        for toks, name in self.phrases:
            n = len(toks)
            if n > len(q):
                continue
            joined = " ".join(toks)
            for i in range(len(q) - n + 1):
                window = q[i:i + n]
                if window == toks:
                    score = 1.0 + 0.01 * n
                elif n >= 2:
                    wj = " ".join(window)
                    if wj[0] != joined[0] or abs(len(wj) - len(joined)) > 3:  # loại nhanh các cụm chắc chắn không giống
                        continue
                    sm = difflib.SequenceMatcher(None, wj, joined)
                    if sm.real_quick_ratio() < 0.88 or sm.quick_ratio() < 0.88:
                        continue
                    ratio = sm.ratio()
                    score = ratio if ratio >= 0.88 else 0.0
                else:
                    score = 0.0
                if score > best_score:
                    best, best_score = name, score
        return self.by_name[best] if best else None

    def for_meals(self, meal_codes):
        return [d for d in self.dishes if not meal_codes or set(meal_codes) & set(d.get("meals", []))]


def find_meals(text, meal_words):
    t = " ".join(tokens(text))
    return [code for code, words in meal_words.items() if any(w in t for w in words)]


# ------------------------------------------------------------------ sản phẩm
class CatalogIndex:
    """Chỉ mục tìm kiếm trên danh mục (tên + thương hiệu + danh mục, không dấu). Thứ tự danh mục = độ phổ biến."""

    def __init__(self, products, stopwords=None):
        """stopwords: {"shared": [...], "by_intent": {ý định: [...]}} - từ khung câu cần bỏ khi tìm sản phẩm."""
        stopwords = stopwords or {}
        self.stop_shared = set(stopwords.get("shared", []))
        self.stop_by_intent = {k: set(v) for k, v in stopwords.get("by_intent", {}).items()}
        self.products = []
        self.bigrams = set()  # cặp từ liền nhau trong tên hàng: "nước mắm" khác "mắm tôm" dù từ "nước" là từ đệm
        df = Counter()
        for rank, p in enumerate(products):
            name_toks = tokens(p.get("name", ""))
            toks = set(name_toks) | set(tokens(p.get("brand") or "")) | set(tokens(p.get("category_name") or ""))
            self.products.append((p, toks, name_toks, rank, set(name_toks) | set(tokens(p.get("brand") or ""))))
            self.bigrams.update(zip(name_toks, name_toks[1:]))
            df.update(toks)
        n = max(len(self.products), 1)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) + 1 for t, c in df.items()}
        self.vocab = list(df)
        self._expand_cache = {}

    def content_tokens(self, text, intent=None):
        """Từ mang nội dung (tên hàng) sau khi bỏ từ đệm chung và từ khung câu của ý định đã nhận diện."""
        stop = self.stop_shared | self.stop_by_intent.get(intent, set())
        toks = tokens(text)
        out = []
        for i, t in enumerate(toks):
            if t.isdigit() or len(t) <= 1:
                continue
            if t in stop:
                prev_t = toks[i - 1] if i else None
                next_t = toks[i + 1] if i + 1 < len(toks) else None
                # từ đệm nhưng nằm trong tên hàng ("nuoc mam", "mi goi") thì vẫn là nội dung cần tìm
                part_of_name = (next_t and next_t not in stop and (t, next_t) in self.bigrams) or \
                               (prev_t and prev_t not in stop and (prev_t, t) in self.bigrams)
                if not part_of_name:
                    continue
            out.append(t)
        return out

    def _expand(self, q):
        """Các từ trong danh mục trùng hoặc gần giống từ khóa q (chịu gõ sai nhẹ); tính một lần cho mỗi từ khóa."""
        found = self._expand_cache.get(q)
        if found is None:
            found = {t for t in self.vocab if t == q}
            if len(q) >= 4:
                found |= {t for t in self.vocab if t[:1] == q[:1] and abs(len(t) - len(q)) <= 2
                          and difflib.SequenceMatcher(None, q, t).ratio() >= 0.86}
            self._expand_cache[q] = found
        return found

    def search(self, text, limit=5, min_score=0.6, content=None, intent=None):
        """[(sản phẩm, điểm 0..1)]: điểm = tỉ lệ trọng số từ khóa của câu khớp với sản phẩm; hòa điểm thì món bán chạy trước."""
        q = content if content is not None else self.content_tokens(text, intent)
        if not q:
            return []
        weights = {t: self.idf.get(t, math.log(len(self.products) + 1) + 1) for t in q}
        expanded = {t: self._expand(t) for t in q}
        total = sum(weights.values())
        scored = []
        for p, ptoks, name_toks, rank, named in self.products:
            got = sum(w for t, w in weights.items() if expanded[t] & ptoks)
            if not got:
                continue
            by_name = sum(w for t, w in weights.items() if expanded[t] & named)
            # từ khóa nằm đầu tên thường là loại sản phẩm chính ("Gạo ST25" hơn "Bánh gạo")
            bonus = sum(0.05 / (1 + name_toks.index(t)) for t in q if t in name_toks)
            scored.append((got / total, by_name / total, bonus, -rank, p))
        # Khớp theo tên/thương hiệu được ưu tiên: "nước mắm" không kéo theo "mắm tôm" chỉ vì nằm trong nhóm "nước chấm".
        # Chỉ khi không món nào khớp đủ qua tên (vd. "đồ uống", "gia vị") mới tính cả tên nhóm hàng.
        if scored and max(x[1] for x in scored) >= min_score:
            scored = [(by_name, by_name, bonus, r, p) for _, by_name, bonus, r, p in scored if by_name]
        else:
            scored = [(score, by_name, bonus, r, p) for score, by_name, bonus, r, p in scored]
        scored = [(s_, b_, r_, p_) for s_, _, b_, r_, p_ in scored]
        scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
        if not scored or scored[0][0] < min_score:
            return []
        return [(p, round(s, 3)) for s, _, _, p in scored if s >= min_score][:limit]


def unit_amount(product):
    """Ước lượng khối lượng và số cái trong một đơn vị bán: 'khay 500g' -> (500, 1), 'hộp 10 quả' -> (None, 10), 'kg' -> (1000, 1)."""
    text = strip(f"{product.get('unit', '')} {product.get('name', '')}")
    grams = None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", strip(product.get("unit") or "")) or re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", text)
    if m:
        grams = float(m.group(1).replace(",", ".")) * (1000 if m.group(2) == "kg" else 1)
    elif strip(product.get("unit") or "") in ("kg", "1kg"):
        grams = 1000.0
    pcs = 1
    m = re.search(r"(\d+)\s*(?:qua|goi|hop|lon|cai|mieng|cuon|chai)\b", strip(product.get("unit") or ""))
    if m:
        pcs = int(m.group(1))
    return grams, pcs


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
