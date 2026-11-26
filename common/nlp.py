"""Xử lý ngôn ngữ dùng chung cho phần huấn luyện (ml/) và suy luận trong ai-service.

Cùng một hàm tạo đặc trưng được dùng ở cả hai nơi để mô hình học ra sao thì dự đoán đúng như vậy.
Chỉ dùng thư viện chuẩn của Python nên ai-service không cần cài numpy hay scikit-learn.
"""
import math
import re
from collections import Counter

from common.utils import strip_accents

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text):
    """'Cho mình hỏi nước mắm?' -> ['cho', 'minh', 'hoi', 'nuoc', 'mam'] (không dấu, chữ thường)."""
    return _WORD.findall(strip_accents(text))


def features(text):
    """Đặc trưng thô của một câu: từ đơn, cặp từ liền kề và n-gram ký tự (3-4) trong từng từ.

    N-gram ký tự giúp chịu lỗi gõ sai ('nuoc mm', 'gao ts25') và biến thể không dấu."""
    toks = tokens(text)
    feats = Counter()
    for t in toks:
        feats["w:" + t] += 1
        padded = f"^{t}$"
        for n in (3, 4):
            for i in range(len(padded) - n + 1):
                feats[f"c:{padded[i:i + n]}"] += 1
    for a, b in zip(toks, toks[1:]):
        feats[f"b:{a}_{b}"] += 1
    return feats


def vectorize(text, vocab, idf):
    """Đặc trưng TF-IDF (tf dạng log, chuẩn hóa L2) chỉ giữ các đặc trưng có trong từ vựng của mô hình.

    Trả về dict {chỉ số đặc trưng: giá trị}."""
    vec = {}
    for f, c in features(text).items():
        idx = vocab.get(f)
        if idx is not None:
            vec[idx] = (1.0 + math.log(c)) * idf[idx]
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm:
        for k in vec:
            vec[k] /= norm
    return vec


def softmax(scores):
    m = max(scores)
    exps = [math.exp(s - m) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]
