"""Kiểm thử OFFLINE hai mô hình AI tự huấn luyện (không cần chạy hệ thống, không cần mạng).

    python tests/model_test.py

Kiểm tra: tệp mô hình hợp lệ, chất lượng so với baseline, suy luận Python thuần khớp numpy, trợ lý trả lời đúng và
không bịa sản phẩm, chịu đầu vào bẩn, tốc độ. Muốn huấn luyện lại: python ml/train_recommender.py và python ml/train_assistant.py.
"""
import os
import random
import string
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AI = os.path.join(ROOT, "services", "utility", "ai-service")
sys.path[:0] = [ROOT, AI, os.path.join(ROOT, "ml")]

import assistant as A  # noqa: E402
import local_model as L  # noqa: E402
from common.seed_data import BASE_PRODUCTS, CATEGORIES, KIND_OF, PRODUCTS  # noqa: E402

RESULTS = []


def check(cond, name, info=None):
    RESULTS.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond or info is None else f"  -> {str(info)[:300]}"))


def catalog():
    out = []
    for i, p in enumerate(PRODUCTS, 1):
        price, sale = p[6], p[7]
        out.append({"id": i, "sku": p[1], "name": p[3], "brand": p[4], "unit": p[5], "category_name": CATEGORIES[p[0]][0],
                    "category_id": p[0], "price": price, "sale_price": sale, "final_price": sale or price, "in_stock": p[8] > 0,
                    "discount_percent": round(100 - sale * 100 / price) if sale else 0})
    return [p for p in out if p["in_stock"]]


# Câu mới viết sau khi huấn luyện xong, KHÔNG nằm trong dữ liệu huấn luyện hay tập viết tay dùng để chỉnh mô hình
FRESH = [
    ("chào shop", "greeting"), ("alo có ai không", "greeting"), ("bạn là bot hả", "about_bot"), ("cảm ơn nhiều", "thanks"),
    ("thôi mình đi đây", "goodbye"), ("tìm giúp mình dầu ăn", "find_product"), ("shop còn bán cà phê không", "find_product"),
    ("trứng gà bao nhiêu tiền một hộp", "price_query"), ("giá của nước giặt là bao nhiêu", "price_query"),
    ("nấu thịt kho cần những gì", "recipe"), ("làm cơm chiên cho 3 người mua gì", "recipe"),
    ("tối nay ăn gì nhỉ", "meal_suggest"), ("gợi ý thực đơn bữa trưa", "meal_suggest"),
    ("mua bia thì nên lấy thêm gì", "bought_together"), ("ai mua sữa chua cũng hay mua gì nữa", "bought_together"),
    ("đang có khuyến mãi gì", "promotion"), ("có món nào sale không", "promotion"),
    ("mình có 200k thì mua được gì", "budget"), ("cho mình sữa tươi dưới 40k", "budget"),
    ("cửa hàng mở đến mấy giờ", "store_info"), ("mua bao nhiêu thì miễn phí giao", "store_info"),
    ("đơn của tôi giao tới đâu rồi", "order_help"), ("tôi muốn hủy đơn đã đặt", "order_help"),
    ("kể chuyện cười đi", "out_of_scope"), ("giá vàng hôm nay bao nhiêu", "out_of_scope"), ("làm sao để học tốt tiếng anh", "out_of_scope"),
]


def main():
    import json
    rec_path = os.path.join(AI, "models", "recommender.json")
    bot_path = os.path.join(AI, "models", "assistant.json")

    print("\n== Mô hình gợi ý mua kèm")
    data = json.load(open(rec_path, encoding="utf-8"))
    rec = L.Recommender(data)
    seed_skus = [p[1] for p in PRODUCTS]
    check(rec.skus == seed_skus, "SKU trong mô hình khớp danh mục seed", (len(rec.skus), len(seed_skus)))
    m, b = rec.metrics, rec.baseline
    check(m["hit@4"] > b["hit@4"] and m["precision@4"] > b["precision@4"], "Trên tập kiểm tra: hit@4 và precision@4 hơn baseline bán chạy", (m, b))
    check(m["completion@4"] >= 2 * b["completion@4"], "Hoàn thiện giỏ hàng: gấp ít nhất 2 lần baseline", (m["completion@4"], b["completion@4"]))
    check(m["coverage"] >= 0.25, f"Gợi ý phủ ít nhất 1/4 danh mục (không chỉ hàng bán chạy): {m['coverage']}", m["coverage"])
    check(m["same_kind@4"] <= 0.01, "Không gợi ý hàng cùng nhóm (thay thế nhau) với món đã có", m["same_kind@4"])
    check(len(seed_skus) >= 500 and len(set(rec.kinds)) >= 60, f"Mô hình phủ danh mục lớn ({len(seed_skus)} sản phẩm, {len(set(rec.kinds))} nhóm hàng)")
    try:
        import numpy as np
        w1, b1, w2, b2 = (np.array(data["mlp"][k]) for k in ("w1", "b1", "w2", "b2"))
        x = np.zeros(len(seed_skus))
        x[[3, 10, 20]] = 1
        ref = 1 / (1 + np.exp(-(np.maximum(x @ w1 + b1, 0) @ w2 + b2))) / np.array(rec.discount)
        check(float(np.abs(np.array(rec._mlp([3, 10, 20])) - ref).max()) < 1e-9, "Suy luận Python thuần khớp numpy")
    except ImportError:
        print("  (bỏ qua so khớp numpy - chưa cài numpy)")
    r = rec.recommend(["MI-HH-GOI"], 4)
    check(r and "MI-HH-GOI" not in [s for s, _ in r] and all(0 <= s <= 2 for _, s in r), "Không gợi ý chính sản phẩm đang xem", r)
    kinds = lambda skus, n=4: {KIND_OF[s] for s, _ in rec.recommend(skus, n)}  # noqa: E731
    check("trung" in kinds(["MI-HH-GOI"]), "Mì gói -> có trứng trong 4 gợi ý", rec.recommend(["MI-HH-GOI"], 4))
    check("snack" in kinds(["BIA-SG-LON"]) or "hat_say" in kinds(["BIA-SG-LON"]), "Bia -> snack hoặc hạt nhắm", rec.recommend(["BIA-SG-LON"], 4))
    check("rua_chen" in kinds(["OMO-36"]) or "xa_vai" in kinds(["OMO-36"]), "Nước giặt -> nước rửa chén hoặc nước xả vải", rec.recommend(["OMO-36"], 4))
    check("sua_dac" in kinds(["CF-G7-18"]), "Cà phê -> sữa đặc", rec.recommend(["CF-G7-18"], 4))
    ks = [KIND_OF[s] for s, _ in rec.recommend(["NM-NAMNGU-750"], 8)]
    check(len(ks) == len(set(ks)) and "nuoc_mam" not in ks, "Mỗi nhóm hàng tối đa một gợi ý, không gợi ý nước mắm khác khi đã có nước mắm", ks)
    check(rec.recommend(["KHONG-CO"], 4) == [] and rec.recommend([], 4) == [], "SKU lạ hoặc giỏ rỗng -> không gợi ý")
    only = {"UC-GA-500", "TOM-THE-500"}
    check(all(s in only for s, _ in rec.recommend(["BIA-SG-LON"], 4, allowed=only)), "Chỉ gợi ý trong tập được phép (hàng còn bán)")
    boosted = rec.recommend(["OMO-36"], 4, history={"CLEAR-630": 200}, allowed=None)
    check("CLEAR-630" in [s for s, _ in boosted], "Lịch sử đơn thật đẩy món lên (mô hình học dần từ dữ liệu thật)", boosted)
    basket = rec.recommend(["CA-BASA-500", "CA-CHUA-1KG"], 4)
    check(basket and not {"CA-BASA-500", "CA-CHUA-1KG"} & {s for s, _ in basket}, "Gợi ý theo cả giỏ không lặp món đã có", basket)
    t0 = time.time()
    for _ in range(200):
        rec.recommend(["MI-HH-GOI", "TRUNG-GA-10"], 4)
    ms = (time.time() - t0) * 5
    check(ms < 40, f"Suy luận nhanh ({ms:.2f} ms/lần)", ms)

    print("\n== Mô hình hiểu ý định của trợ lý")
    bot = A.Assistant.load(bot_path, rec)
    mt = bot.metrics
    check(mt["test"]["accuracy"] >= 0.8, f"Tập kiểm tra sinh tự động (mẫu mới): accuracy {mt['test']['accuracy']}", mt["test"])
    check(mt["handwritten"]["accuracy"] >= 0.9, f"Tập viết tay độc lập: accuracy {mt['handwritten']['accuracy']}", mt["handwritten"])
    check(mt["slots"]["product_top1"] >= 0.9 and mt["slots"]["dish_accuracy"] >= 0.95, "Trích xuất sản phẩm và món ăn chính xác", mt["slots"])
    cat = catalog()
    wrong = []
    for text, want in FRESH:
        got = bot.reply([{"role": "user", "content": text}], cat)["intent"]
        if got != want:
            wrong.append((text, want, got))
    acc = 1 - len(wrong) / len(FRESH)
    print(f"     câu mới viết: {len(FRESH) - len(wrong)}/{len(FRESH)} đúng ý định ({acc:.0%})")
    for w in wrong:
        print("       sai:", w)
    check(acc >= 0.8, f"Câu hoàn toàn mới (chưa từng thấy): đúng ý định ≥ 80% ({acc:.0%})", wrong)

    print("\n== Câu trả lời của trợ lý (danh mục seed)")
    ids = {p["id"] for p in cat}

    def ask(*texts):
        msgs, out = [], None
        for t in texts:
            msgs.append({"role": "user", "content": t})
            out = bot.reply(msgs, cat)
            msgs.append({"role": "assistant", "content": out["reply"]})
        return out

    o = ask("Nấu canh chua cho 4 người cần mua gì?")
    lines = {x["product"]["sku"]: x for x in o["products"]}
    check(o["intent"] == "recipe" and "CA-BASA-500" in lines and "CA-CHUA-1KG" in lines, "Canh chua: có cá basa và cà chua", [x["product"]["name"] for x in o["products"]])
    check(lines["CA-BASA-500"]["qty"] == 2, "4 người x 150g cá = 600g -> 2 khay 500g", lines["CA-BASA-500"]["qty"])
    check(all("Gia vị" in x["reason"] for k, x in lines.items() if k in ("NM-NAMNGU-750", "DUONG-BH-1KG")), "Gia vị được đánh dấu để khách bỏ qua nếu đã có")
    elsewhere = o["reply"].split("Cần mua thêm ở nơi khác:")[-1] if "Cần mua thêm ở nơi khác:" in o["reply"] else ""
    check(" me" in " " + elsewhere and any("Giá đỗ" in x["product"]["name"] for x in o["products"]),
          "Nguyên liệu cửa hàng không bán (me) báo cần mua nơi khác; hàng có bán (giá đỗ) được liệt kê", o["reply"])
    o2 = ask("mì xào trứng cho 2 người", "cho 4 người")
    check(o2["intent"] == "recipe" and "4 người" in o2["reply"] and {x["product"]["sku"]: x["qty"] for x in o2["products"]}.get("MI-HH-GOI") == 4,
          "Câu nối tiếp 'cho 4 người' tính lại cho món vừa hỏi", o2["reply"])
    o = ask("mì hảo hảo giá bao nhiêu")
    check(o["intent"] == "price_query" and any("Hảo Hảo" in x["product"]["name"] for x in o["products"]), "Hỏi giá ra đúng sản phẩm")
    o = ask("có gì đang giảm giá không")
    check(o["products"] and all(x["product"]["sale_price"] for x in o["products"]), "Khuyến mãi: chỉ liệt kê hàng đang giảm giá")
    o = ask("nước mắm dưới 50k")
    check(o["products"] and all(x["product"]["final_price"] <= 50000 for x in o["products"]), "Ngân sách: mọi món đều trong tầm giá")
    o = ask("nước mắm", "dưới 20k")
    check(o["intent"] == "budget" and "Nước mắm" in o["reply"] + " ".join(x["product"]["name"] for x in o["products"]), "Câu nối tiếp 'dưới 20k' nói về nước mắm", o["reply"])
    o = ask("bia thường mua kèm gì")
    check(o["intent"] == "bought_together" and o["products"] and all(x["product"]["sku"] != "BIA-SG-LON" for x in o["products"]),
          "Mua kèm: không lặp sản phẩm đang hỏi")
    o = ask("gợi ý bữa tối")
    check(o["intent"] == "meal_suggest" and len(o["suggestions"]) >= 1, "Gợi ý bữa ăn kèm các câu bấm nhanh", o)
    o = ask("shop mở cửa mấy giờ")
    check("6:00" in o["reply"] and not o["products"], "Giờ mở cửa lấy từ câu hỏi thường gặp")
    o = ask("hủy đơn giúp mình")
    check(o.get("link", {}).get("href") == "orders.html", "Hỗ trợ đơn hàng: chỉ đường tới trang Đơn hàng")
    o = ask("viết thơ giúp mình")
    check(o["intent"] == "out_of_scope" and not o["products"], "Ngoài phạm vi: từ chối lịch sự, không bịa sản phẩm")
    o = ask("có bán sầu riêng không")
    check(not o["products"] and "chưa có" in o["reply"], "Hàng cửa hàng không bán -> nói chưa có, không gợi ý bừa", o["reply"])
    o = ask("có bán thịt bò không")
    check(o["products"] and all("bò" in x["product"]["name"].lower() for x in o["products"]), "Danh mục mới: hỏi thịt bò ra đúng các loại thịt bò", [x["product"]["name"] for x in o["products"]])
    o = ask("gợi ý bữa tối")
    check(all(x["product"]["id"] in ids for x in o["products"]), "Mọi sản phẩm trả về đều có trong danh mục")
    out_of_stock = [p for p in catalog() if p["sku"] != "CA-BASA-500"]
    o = bot.reply([{"role": "user", "content": "nấu cá kho tộ cho 2 người"}], out_of_stock)
    check("cá basa" in o["reply"] and all(x["product"]["sku"] != "CA-BASA-500" for x in o["products"]),
          "Hết hàng cá basa -> không đề xuất, báo cần mua nơi khác", o["reply"])
    check(bot.reply([{"role": "user", "content": "gạo"}], [])["products"] == [], "Danh mục rỗng -> không lỗi")

    print("\n== Trích xuất số người và ngân sách")
    import nlu
    servings = {"cho 4 người": 4, "nấu cho ba người ăn": 3, "gia đình 5 người": 5, "1 người": 1, "40 người": None, "không có số": None}
    prices = {"dưới 100k": 100000, "200.000đ": 200000, "1,5 triệu": 1500000, "2tr": 2000000, "50 nghìn": 50000, "giá 35000": 35000,
              "không có giá": None, "3 củ khoai": None}
    bad_s = {t: nlu.parse_servings(t) for t, v in servings.items() if nlu.parse_servings(t) != v}
    bad_p = {t: nlu.parse_price(t) for t, v in prices.items() if nlu.parse_price(t) != v}
    check(not bad_s, "Đọc đúng số người (kể cả chữ 'ba', chặn số vô lý)", bad_s)
    check(not bad_p, "Đọc đúng ngân sách (100k, 200.000đ, 1,5 triệu...; '3 củ khoai' không bị hiểu là giá)", bad_p)

    print("\n== Chịu đầu vào bẩn và tốc độ")
    rng = random.Random(5)
    junk = ["", "   ", "???", "😀😀😀", "a" * 500, "<script>alert(1)</script>", "'; DROP TABLE products;--", "\u0000​",
            "9" * 40 + "k", "dưới 99999999999999999999k", "cho 0 người", "cho 999 người nấu canh chua",
            "".join(rng.choice(string.printable) for _ in range(300))]
    crashed = []
    for t in junk:
        try:
            if t.strip():
                bot.reply([{"role": "user", "content": t}], cat)
        except Exception as exc:  # noqa: BLE001
            crashed.append((t[:30], repr(exc)))
    check(not crashed, "Đầu vào lạ (rỗng, emoji, mã độc, số khổng lồ) không làm hỏng trợ lý", crashed)
    o = bot.reply([{"role": "user", "content": "nấu canh chua cho 999 người"}], cat)
    check(all((x["qty"] or 1) <= 12 for x in o["products"]), "Số lượng gợi ý bị chặn trần (không gợi ý mua hàng nghìn)")
    t0 = time.time()
    for _ in range(50):
        bot.reply([{"role": "user", "content": "nấu canh chua cho 4 người cần mua gì?"}], cat)
    ms = (time.time() - t0) * 20
    check(ms < 100, f"Trả lời nhanh ({ms:.1f} ms/câu)", ms)

    ok = sum(RESULTS)
    print(f"\nKết quả: {ok}/{len(RESULTS)} đạt")
    sys.exit(0 if ok == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
