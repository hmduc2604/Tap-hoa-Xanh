"""Trợ lý mua sắm chạy cục bộ (không gọi dịch vụ ngoài).

Cách hoạt động, từng bước cho mỗi câu của khách:
  1. Mô hình hồi quy logistic đã huấn luyện (models/assistant.json) đoán ý định: tìm hàng, hỏi giá, nấu món, gợi ý bữa ăn,
     mua kèm, khuyến mãi, ngân sách, thông tin cửa hàng, hỗ trợ đơn hàng, chào hỏi, ngoài phạm vi...
  2. Trích thực thể bằng quy tắc và tra cứu: món ăn, số người, ngân sách, sản phẩm trong danh mục đang bán.
  3. Soạn câu trả lời từ DỮ LIỆU THẬT (danh mục, giá, tồn kho, mô hình mua kèm) theo mẫu câu cố định.
Mô hình chỉ dùng để hiểu câu hỏi; mọi sản phẩm và giá trong câu trả lời đều lấy từ product-service nên không bịa hàng.
Đây là mô hình nhỏ chạy bằng thống kê, không phải mô hình ngôn ngữ sinh văn bản: nó hiểu được các dạng câu hỏi mua sắm
đã huấn luyện, gặp câu lạ thì hỏi lại hoặc từ chối thay vì đoán bừa.
"""
import math
import time
from datetime import date

import nlu
from common.nlp import tokens

DEFAULT_CHIPS = ["Nấu canh chua cho 4 người cần mua gì?", "Gợi ý bữa tối", "Có món nào đang giảm giá không?",
                 "Mì Hảo Hảo giá bao nhiêu?"]
MAX_QTY = 12
STRONG_MATCH = 0.75  # điểm tìm sản phẩm đủ tin cậy để đoán ý định khi mô hình không chắc


def money(v):
    return f"{int(v):,}".replace(",", ".") + "đ"


def local_hour():
    return (time.gmtime().tm_hour + 7) % 24  # giờ Việt Nam, không phụ thuộc múi giờ máy chủ


def default_meal():
    h = local_hour()
    return "sang" if h < 10 else "trua" if h < 14 else "toi" if h < 21 else "khuya"


class Assistant:
    def __init__(self, data, recommender=None):
        self.data = data
        self.model = nlu.IntentModel(data)
        self.threshold = data.get("threshold", 0.45)
        self.stopwords = data["stopwords"]
        self.dishes = nlu.DishIndex(data["dishes"])
        self.faq = data["faq"]
        self.meal_words = data["meal_words"]
        self.labels = data.get("labels", {})
        self.prefer = data.get("prefer", {})
        self.recommender = recommender
        self.metrics = data.get("metrics", {})
        self.trained_at = data.get("trained_at")
        self._index = (None, None)  # (chữ ký danh mục, CatalogIndex): dựng lại chỉ khi danh mục đổi

    def index_for(self, catalog):
        signature = tuple((p["id"], p["name"]) for p in catalog)
        if self._index[0] != signature:
            self._index = (signature, nlu.CatalogIndex(catalog, self.stopwords))
        return self._index[1]

    @classmethod
    def load(cls, path, recommender=None):
        return cls(nlu.load_json(path), recommender)

    def info(self):
        return {"kind": "tfidf+logistic-regression", "intents": self.model.classes, "features": len(self.model.vocab),
                "threshold": self.threshold, "dishes": len(self.dishes.dishes), "trained_at": self.trained_at,
                "metrics": self.metrics}

    # ------------------------------------------------------------------ điểm vào
    def reply(self, messages, catalog, co_history=None):
        """messages: [{role, content}] đã kiểm tra, tin cuối là của khách. catalog: sản phẩm còn bán (đã sắp theo độ phổ biến).
        co_history(product_id) -> {product_id khác: số đơn thật mua cùng} (không bắt buộc).

        Trả về {"reply", "products": [{"product", "qty", "reason"}], "suggestions", "intent", "confidence", "link"?}."""
        text = messages[-1]["content"]
        prior = [m["content"] for m in messages[:-1] if m["role"] == "user"][-4:]
        ctx = Ctx(self, text, prior, catalog, co_history or (lambda pid: {}))
        intent, conf = self.understand(ctx)
        ctx.intent = intent
        handler = getattr(self, f"_do_{intent}", self._do_unclear)
        out = handler(ctx)
        out.setdefault("products", [])
        out.setdefault("suggestions", [])
        out["intent"], out["confidence"] = intent, round(conf, 3)
        return out

    def understand(self, ctx):
        """Ý định cuối cùng sau khi kết hợp mô hình với thực thể nhìn thấy trong câu. Trả về (ý định, độ tin cậy)."""
        ranked = self.model.predict(ctx.text)
        intent, prob = ranked[0]
        sure = prob >= self.threshold
        if ctx.dish and (not sure or intent in ("recipe", "find_product", "price_query", "budget", "meal_suggest")):
            if sure and intent in ("find_product", "price_query", "budget"):
                ctx.intent = intent  # "còn bán cà phê không": tên món trùng tên hàng thì tin vào mô hình khi có sản phẩm khớp rõ ràng
                hit = ctx.search(min_score=STRONG_MATCH)
                ctx.intent = None
                if hit:
                    return intent, prob
            return "recipe", max(prob, self.threshold)
        if not sure:
            # câu tiếp nối ngắn: "cho 4 người", "dưới 50k" -> dùng ngữ cảnh các câu trước
            if ctx.servings and ctx.prior_dish:
                ctx.dish = ctx.prior_dish
                return "recipe", self.threshold
            if ctx.price and ctx.prior_product_text:
                ctx.follow_up = True
                return "budget", self.threshold
            ctx.intent = "find_product"  # bỏ các từ khung câu kiểu "cần mua", "có bán" trước khi tìm hàng
            hits = ctx.search(min_score=STRONG_MATCH)
            if hits:
                return "find_product", hits[0][1] * self.threshold
            if intent in ("find_product", "price_query") and prob >= 0.3 and ctx.query_tokens():
                return intent, prob  # hỏi về hàng hóa nhưng cửa hàng không có: trả lời "chưa có"
            ctx.intent = None
            return "unclear", prob
        return intent, prob

    # ------------------------------------------------------------------ chào hỏi, giới thiệu
    def _do_greeting(self, ctx):
        return {"reply": "Chào bạn! Mình là trợ lý mua sắm của Tạp Hóa Xanh. Mình giúp bạn tìm hàng, tính nguyên liệu cho món ăn, "
                         "xem hàng giảm giá hay gợi ý món mua kèm. Bạn cần gì hôm nay?", "suggestions": DEFAULT_CHIPS}

    def _do_about_bot(self, ctx):
        return {"reply": "Mình là trợ lý mua sắm của Tạp Hóa Xanh, một mô hình AI nhỏ do cửa hàng huấn luyện và chạy ngay trong hệ thống, "
                         "câu hỏi của bạn không gửi ra dịch vụ bên ngoài. Mình giúp: tìm sản phẩm và báo giá, tính nguyên liệu cho món ăn, "
                         "gợi ý bữa ăn, xem hàng giảm giá, gợi ý món thường mua kèm. Mình có thể nhầm với câu hỏi lạ, lúc đó bạn nói lại "
                         "ngắn gọn giúp mình nhé.", "suggestions": DEFAULT_CHIPS}

    def _do_thanks(self, ctx):
        return {"reply": "Không có gì ạ! Cần thêm gì bạn cứ hỏi mình nhé.", "suggestions": []}

    def _do_goodbye(self, ctx):
        return {"reply": "Hẹn gặp lại bạn! Chúc bạn một bữa ăn ngon.", "suggestions": []}

    def _do_out_of_scope(self, ctx):
        return {"reply": "Mình chỉ hỗ trợ việc mua sắm ở Tạp Hóa Xanh: tìm hàng, giá, khuyến mãi và nguyên liệu nấu ăn. "
                         "Với câu hỏi này mình chưa giúp được, bạn thử hỏi về sản phẩm hoặc món ăn nhé.", "suggestions": DEFAULT_CHIPS}

    def _do_unclear(self, ctx):
        return {"reply": "Mình chưa hiểu rõ ý bạn. Bạn có thể nói tên món hàng (ví dụ \"nước mắm\"), tên món ăn muốn nấu, "
                         "hoặc chọn một gợi ý bên dưới.", "suggestions": DEFAULT_CHIPS}

    # ------------------------------------------------------------------ tìm hàng, giá
    def _do_find_product(self, ctx):
        hits = ctx.search(limit=5)
        if not hits:
            return self._not_found(ctx)
        n = len(hits)
        sale = [p for p, _ in hits if p.get("sale_price")]
        extra = f" Trong đó {sale[0]['name']} đang giảm giá." if sale else ""
        return {"reply": f"Mình tìm thấy {n} sản phẩm phù hợp.{extra}", "products": [self._line(p) for p, _ in hits],
                "suggestions": self._together_chip(hits[0][0])}

    def _not_found(self, ctx):
        return {"reply": "Cửa hàng chưa có sản phẩm khớp với yêu cầu này, hoặc mình chưa hiểu đúng ý bạn. "
                         "Bạn thử gõ tên món hàng ngắn gọn hơn, hoặc xem các gợi ý bên dưới nhé.", "suggestions": DEFAULT_CHIPS}

    def _do_price_query(self, ctx):
        hits = ctx.search(limit=3)
        if not hits:
            return self._not_found(ctx)
        lines = []
        for p, _ in hits:
            tail = f" (đang giảm từ {money(p['price'])})" if p.get("sale_price") else ""
            lines.append(f"{p['name']}: {money(p['final_price'])}{tail}")
        return {"reply": "Giá hiện tại:\n" + "\n".join(lines), "products": [self._line(p) for p, _ in hits],
                "suggestions": self._together_chip(hits[0][0])}

    def _together_chip(self, product):
        return [f"{product['name']} thường mua kèm gì?"]

    # ------------------------------------------------------------------ khuyến mãi, ngân sách
    def _do_promotion(self, ctx):
        sale = [p for p in ctx.catalog if p.get("sale_price")]
        if not sale:
            return {"reply": "Hiện chưa có sản phẩm nào đang giảm giá. Bạn quay lại sau nhé.", "suggestions": DEFAULT_CHIPS}
        sale.sort(key=lambda p: -(p.get("discount_percent") or 0))
        top = sale[:6]
        best = top[0]
        return {"reply": f"Đang có {len(sale)} sản phẩm giảm giá, nhiều nhất là {best['name']} (giảm {best.get('discount_percent') or 0}%). "
                         f"Đây là những món nổi bật:", "products": [self._line(p) for p in top]}

    def _do_budget(self, ctx):
        price = ctx.price
        hits = ctx.search(limit=12, min_score=0.5) if ctx.query_tokens() else []
        hits = [h for h in hits if h[1] >= hits[0][1] - 0.2]  # bỏ món chỉ khớp một phần từ khóa
        if not hits and len(tokens(ctx.text)) <= 4 and ctx.prior_product_text:
            ctx.follow_up = True  # "dưới 50k" ngắn gọn: hỏi tiếp về sản phẩm vừa nhắc
        if not hits and ctx.follow_up and ctx.prior_product_text:
            hits = ctx.search(text=ctx.prior_product_text, limit=12, min_score=0.5)
            hits = [h for h in hits if h[1] >= hits[0][1] - 0.2] if hits else []
        if hits:
            items = [p for p, _ in hits]
            cheapest = any(w in " ".join(tokens(ctx.text)) for w in ("re nhat", "re hon", "gia re", "tiet kiem", "binh dan", "mem"))
            if price:
                fit = [p for p in items if p["final_price"] <= price]
                if not fit:
                    low = min(items, key=lambda p: p["final_price"])
                    return {"reply": f"Chưa có sản phẩm nào dưới {money(price)}. Món rẻ nhất mình tìm được là {low['name']} giá "
                                     f"{money(low['final_price'])}.", "products": [self._line(low)]}
                items = sorted(fit, key=lambda p: p["final_price"]) if cheapest else fit
                return {"reply": f"Có {len(items[:5])} sản phẩm trong tầm {money(price)}:", "products": [self._line(p) for p in items[:5]]}
            items = sorted(items, key=lambda p: p["final_price"])[:5]
            return {"reply": f"Mình xếp theo giá từ thấp lên cao, rẻ nhất là {items[0]['name']} giá {money(items[0]['final_price'])}:",
                    "products": [self._line(p) for p in items]}
        if price:
            servings = ctx.servings or 2
            fits = []
            for d in self.dishes.dishes:
                plan = self.plan(d, servings, ctx)
                if plan["usable"] and plan["total"] <= price:
                    fits.append((plan["total"], d, plan))
            fits.sort(key=lambda x: -x[0])  # món "đáng tiền" nhất trong ngân sách trước
            if not fits:
                return {"reply": f"Với {money(price)} mình chưa tìm được món nấu trọn bữa cho {servings} người. "
                                 f"Bạn tăng ngân sách hoặc hỏi một món cụ thể nhé.", "suggestions": DEFAULT_CHIPS}
            picks = fits[:3]
            names = ", ".join(f"{d['name']} (khoảng {money(t)})" for t, d, _ in picks)
            return {"reply": f"Với {money(price)} cho {servings} người, bạn có thể nấu: {names}. Chọn một món để mình liệt kê nguyên liệu.",
                    "suggestions": [f"Nấu {d['name']} cho {servings} người cần mua gì?" for _, d, _ in picks]}
        return {"reply": "Bạn muốn tìm món gì và ngân sách khoảng bao nhiêu? Ví dụ: \"nước mắm dưới 50k\".", "suggestions": DEFAULT_CHIPS}

    # ------------------------------------------------------------------ mua kèm
    def _do_bought_together(self, ctx):
        product = None
        hits = ctx.search(limit=1, min_score=0.5)
        if hits:
            product = hits[0][0]
        elif ctx.prior_product_text:
            prior = ctx.search(text=ctx.prior_product_text, limit=1, min_score=0.5)
            product = prior[0][0] if prior else None
        if not product:
            return {"reply": "Bạn muốn xem món mua kèm với sản phẩm nào? Ví dụ: \"mì gói thường mua kèm gì?\".",
                    "suggestions": ["Mì Hảo Hảo thường mua kèm gì?", "Bia thường mua kèm gì?"]}
        recs = self.together(product, ctx, limit=4)
        if not recs:
            return {"reply": f"Mình chưa có đủ dữ liệu về món mua kèm với {product['name']}.", "products": [], "suggestions": DEFAULT_CHIPS}
        return {"reply": f"Khách mua {product['name']} thường mua kèm:", "products": recs}

    def together(self, product, ctx, limit=4):
        """Món mua kèm từ mô hình đã huấn luyện, cộng điểm theo lịch sử đơn thật; trả về dòng sản phẩm có lý do."""
        if not self.recommender or not product.get("sku") or not self.recommender.knows(product["sku"]):
            return []
        by_sku = {p["sku"]: p for p in ctx.catalog if p.get("sku") and p["id"] != product["id"]}
        by_id = {p["id"]: p for p in ctx.catalog}
        real = ctx.co_history(product["id"])
        history = {by_id[i]["sku"]: n for i, n in real.items() if i in by_id and by_id[i].get("sku")}
        ranked = self.recommender.recommend([product["sku"]], limit, history, allowed=set(by_sku))
        return [self._line(by_sku[s], reason=f"Thường mua cùng {product['name']}") for s, _ in ranked]

    # ------------------------------------------------------------------ món ăn
    def plan(self, dish, servings, ctx):
        """Tra nguyên liệu của món trong danh mục: [{product, qty, pantry}], cần mua nơi khác, tổng tiền."""
        lines, missing, absent, total = [], [], [], 0
        used, main_count, found_main = set(), 0, 0
        for ing in dish["ingredients"]:
            label = self.labels.get(ing["kw"], ing["kw"])
            if ing.get("missing"):
                missing.append(label)
                continue
            is_main = not ing.get("pantry")
            main_count += is_main
            product = ctx.ingredient(ing, self.prefer.get(ing["kw"]))
            if not product:
                absent.append(label)
                continue
            if product["id"] in used:
                found_main += is_main
                continue
            used.add(product["id"])
            found_main += is_main
            qty = self.quantity(ing, servings, product)
            total += qty * product["final_price"]
            lines.append({"product": product, "qty": qty, "pantry": bool(ing.get("pantry")), "label": label})
        usable = found_main >= max(1, math.ceil(0.7 * main_count))  # đủ phần lớn nguyên liệu chính thì mới đề xuất món
        return {"lines": lines, "missing": missing + absent, "total": total, "usable": usable}

    @staticmethod
    def quantity(ing, servings, product):
        if ing.get("pantry"):
            return 1
        grams, pcs = nlu.unit_amount(product)
        if "g" in ing:
            need = ing["g"] * servings
            qty = math.ceil(need / grams) if grams else 1
        elif "pcs" in ing:
            qty = math.ceil(ing["pcs"] * servings / max(pcs, 1))
        else:
            qty = 1
        return max(1, min(qty, MAX_QTY))

    def _do_recipe(self, ctx):
        dish = ctx.dish
        if not dish and ctx.prior_dish and (ctx.servings or not ctx.query_tokens()):
            dish = ctx.prior_dish  # "cho 4 người" nối tiếp món vừa hỏi
        if not dish:
            names = [d["name"] for d in self.dishes.dishes[:4]]
            return {"reply": "Mình chưa có công thức món này. Mình biết nguyên liệu của các món như " + ", ".join(names) +
                             "... Bạn chọn một món hoặc hỏi \"gợi ý bữa tối\" nhé.",
                    "suggestions": [f"Nấu {n} cần mua gì?" for n in names[:3]]}
        stated = ctx.servings
        servings = stated or ctx.prior_servings or 2
        plan = self.plan(dish, servings, ctx)
        lines = sorted(plan["lines"], key=lambda x: x["pantry"])
        if not lines:
            return {"reply": f"Mình biết {dish['name']} nhưng cửa hàng hiện chưa có nguyên liệu chính. Bạn thử món khác nhé.",
                    "suggestions": DEFAULT_CHIPS}
        main_total = sum(x["qty"] * x["product"]["final_price"] for x in lines if not x["pantry"])
        parts = [f"{dish['name'].capitalize()} cho {servings} người: cửa hàng có {len(lines)} nguyên liệu, tạm tính {money(plan['total'])}"
                 f" (nguyên liệu chính {money(main_total)})."]
        pantry = [x["label"] for x in lines if x["pantry"]]
        if pantry:
            parts.append("Gia vị đã có sẵn ở nhà thì bạn bỏ qua: " + ", ".join(pantry) + ".")
        if plan["missing"]:
            parts.append("Cần mua thêm ở nơi khác: " + ", ".join(plan["missing"]) + ".")
        if not stated and not ctx.prior_servings:
            parts.append("Mình tính cho 2 người, bạn nói số người để mình tính lại.")
        if dish.get("how") and "cach" in tokens(ctx.text):
            parts.append("Cách làm nhanh: " + dish["how"])
        chips = []
        if not stated:
            chips.append("Cho 4 người")
        if dish.get("how") and "cach" not in tokens(ctx.text):
            chips.append(f"Cách làm {dish['name']}")
        chips.append("Gợi ý bữa tối")
        products = [self._line(x["product"], qty=x["qty"], reason="Gia vị, bỏ qua nếu nhà đã có" if x["pantry"] else x["label"].capitalize())
                    for x in lines]
        return {"reply": " ".join(parts), "products": products, "suggestions": chips}

    def _do_meal_suggest(self, ctx):
        meals = ctx.meals or [default_meal()]
        pool = self.dishes.for_meals(meals)
        if not pool:
            pool = self.dishes.dishes
        offset = date.today().toordinal() % max(len(pool), 1)  # xoay theo ngày để mỗi ngày gợi ý khác nhau
        pool = pool[offset:] + pool[:offset]
        servings = ctx.servings or 2
        picks = []
        for d in pool:
            plan = self.plan(d, servings, ctx)
            if plan["usable"]:
                if ctx.price and plan["total"] > ctx.price:
                    continue
                picks.append((d, plan))
            if len(picks) == 3:
                break
        names = {"sang": "bữa sáng", "trua": "bữa trưa", "toi": "bữa tối", "nhau": "bàn nhậu", "vat": "ăn vặt", "khuya": "bữa khuya"}
        label = names.get(meals[0], "bữa ăn")
        if not picks:
            return {"reply": f"Mình chưa tìm được món cho {label} với nguyên liệu cửa hàng đang có.", "suggestions": DEFAULT_CHIPS}
        desc = ", ".join(f"{d['name']} (khoảng {money(p['total'])})" for d, p in picks)
        return {"reply": f"Gợi ý cho {label} {servings} người: {desc}. Chọn một món để mình liệt kê nguyên liệu.",
                "suggestions": [f"Nấu {d['name']} cho {servings} người cần mua gì?" for d, _ in picks]}

    # ------------------------------------------------------------------ cửa hàng, đơn hàng
    def _do_store_info(self, ctx):
        t = " ".join(tokens(ctx.text))
        best, best_hits = None, 0
        for item in self.faq:
            hits = sum(1 for k in item["keywords"] if k in t)
            if hits > best_hits:
                best, best_hits = item, hits
        if best:
            return {"reply": best["answer"], "suggestions": []}
        return {"reply": "Tạp Hóa Xanh mở cửa 6:00 đến 22:00 mỗi ngày, giao hàng trong khoảng 2 giờ, miễn phí giao cho đơn từ 300.000đ. "
                         "Thanh toán bằng tiền mặt khi nhận hàng, chuyển khoản hoặc ví Xanh Pay.",
                "suggestions": ["Phí giao hàng bao nhiêu?", "Có những cách thanh toán nào?", "Đổi trả thế nào?"]}

    def _do_order_help(self, ctx):
        return {"reply": "Mình chưa xem được đơn hàng cụ thể của bạn. Bạn vào mục Đơn hàng để xem trạng thái, hủy đơn chưa giao hoặc thanh toán lại nhé.",
                "link": {"text": "Mở đơn hàng của tôi", "href": "orders.html"}}

    # ------------------------------------------------------------------ định dạng
    @staticmethod
    def _line(product, qty=None, reason=None):
        return {"product": product, "qty": qty, "reason": reason}


class Ctx:
    """Thông tin của một lượt hỏi: câu hỏi, thực thể đã trích xuất và các tra cứu có nhớ lại kết quả."""

    def __init__(self, bot, text, prior, catalog, co_history):
        self.bot, self.text, self.prior = bot, text, prior
        self.catalog, self.co_history = catalog, co_history
        self.index = bot.index_for(catalog)
        self.intent = None
        self.follow_up = False
        self.dish = bot.dishes.find(text)
        self.servings = nlu.parse_servings(text)
        self.price = nlu.parse_price(text)
        self.meals = nlu.find_meals(text, bot.meal_words)
        self.prior_dish = next((d for d in (bot.dishes.find(t) for t in reversed(prior)) if d), None)
        self.prior_servings = next((s for s in (nlu.parse_servings(t) for t in reversed(prior)) if s), None)
        self.prior_product_text = next((t for t in reversed(prior) if self.index.search(t, limit=1, min_score=0.5)), None)
        self._cache = {}

    def query_tokens(self, text=None):
        return self.index.content_tokens(text or self.text, self.intent)

    def search(self, limit=5, min_score=0.6, text=None):
        key = (text, limit, min_score, self.intent)
        if key not in self._cache:
            self._cache[key] = self.index.search(text or self.text, limit=limit, min_score=min_score, intent=self.intent)
        return self._cache[key]

    def ingredient(self, ing, prefer=None):
        """Sản phẩm trong danh mục khớp nguyên liệu (từ khóa không dấu); ưu tiên sản phẩm có từ `prefer` / đúng quy cách."""
        key = ("ing", ing["kw"], prefer, ing.get("unit_pcs"))
        if key not in self._cache:
            self._cache[key] = self._resolve(ing, prefer)
        return self._cache[key]

    def _resolve(self, ing, prefer):
        hits = self.index.search("", limit=12, min_score=0.6, content=tokens(ing["kw"]))
        if not hits:
            return None
        top = hits[0][1]
        tied = [p for p, s in hits if s >= top - 0.02]

        def rank(item):
            i, p = item
            name = set(tokens(p["name"]))
            want_one = ing.get("unit_pcs") == 1 and nlu.unit_amount(p)[1] != 1
            return (0 if prefer and prefer in name else 1, 1 if want_one else 0, i)

        return sorted(enumerate(tied), key=rank)[0][1]
