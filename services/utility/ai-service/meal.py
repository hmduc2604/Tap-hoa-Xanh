"""Lập thực đơn và danh sách đi chợ: từ MỘT câu mô tả bữa ăn ("bữa tối cho 4 người, khoảng 200k") ra các món ăn,
nguyên liệu khớp với sản phẩm THẬT đang bán (giá, tồn kho), số lượng cần mua và tổng tiền.

Hai nguồn thực đơn, cùng một định dạng kết quả:
  - AI (Gemini/Claude): model nghĩ ra món và nguyên liệu (tên + khối lượng); phần còn lại do code làm: tra sản phẩm thật
    trong danh mục, đổi khối lượng thành số gói/chai/kg cần mua, cộng tiền, kiểm tra ngân sách. Model không bao giờ
    được tự đưa id sản phẩm hay giá vào kết quả nên không bịa được hàng.
  - Cục bộ (không cần khóa API): dùng cơ sở món ăn đã huấn luyện kèm trợ lý (models/assistant.json) để ghép thực đơn
    cơm gia đình (món mặn + canh + rau + cơm), món khách nêu tên, hoặc món hợp bữa sáng/ăn vặt/nhậu.

Module này chỉ chứa logic thuần (không gọi mạng); việc gọi model và product-service nằm ở app.py.
"""
import math
import re
import zlib
from datetime import date

import nlu
from assistant import Ctx, default_meal
from common.nlp import tokens
from common.utils import strip_accents

MAX_DISHES = 4          # tối đa số món một thực đơn
MAX_INGREDIENTS = 14    # tối đa nguyên liệu mỗi món (model quá lời thì cắt bớt)
MAX_QTY = 12            # tối đa số lượng một sản phẩm trong một thực đơn (khớp mức gợi ý của trợ lý chat)
RICE_G_PER_PERSON = 80  # gạo/người cho một bữa cơm
DEFAULT_BUDGET_PER_PERSON = 70000  # khi khách không nêu ngân sách, thực đơn cục bộ chọn món vừa mức này mỗi người (chỉ để chọn món, không báo vượt)
FALLBACK_PACK_G = 400   # giả định khối lượng một đơn vị bán khi tên/quy cách không ghi (bó rau, củ, hộp...)

MEAL_NAMES = {"sang": "bữa sáng", "trua": "bữa trưa", "toi": "bữa tối", "nhau": "bữa tiệc", "vat": "bữa ăn vặt", "khuya": "bữa khuya"}
# Gạo tính là hàng nhà thường tích trữ (túi 5kg đủ ăn cả tuần): hiện trong nhóm "nhà thường có sẵn", không cộng vào ngân sách bữa ăn.
RICE_DISH = {"name": "cơm trắng", "meals": ["trua", "toi"], "ingredients": [{"kw": "gao", "pantry": True}],
             "how": f"Vo gạo, nấu cơm như thường lệ (khoảng {RICE_G_PER_PERSON}g gạo mỗi người)."}

# Phân vai món để ghép bữa cơm gia đình. Vai suy ra từ tên món trong cơ sở dữ liệu của trợ lý.
VEG_NAMES = {"khoai tây nghiền", "rau muống xào tỏi", "cải ngọt xào tỏi", "bắp cải xào", "su hào cà rốt xào", "đậu cô ve xào",
             "rau củ xào thập cẩm", "cà tím nướng mỡ hành"}
ONE_DISH_FIRST = {"pho", "bun", "mi", "mien", "hu", "banh", "com", "kimbap", "chao", "xoi", "lau", "tiec", "bua", "tokbokki"}
SPLIT_DISHES = re.compile(r"\s*(?:,|;|\+|&|\bvà\b|\bvới\b|\bkèm\b|\bcùng\b|\bcộng\b)\s*", re.I)


def money(v):
    return f"{int(v):,}".replace(",", ".") + "đ"


def dish_role(dish):
    toks = tokens(dish["name"])
    meals = set(dish.get("meals", []))
    if toks and toks[0] in ("canh", "sup"):
        return "soup"
    if not meals & {"trua", "toi"}:
        return "snack"
    if dish["name"] in VEG_NAMES or (toks and toks[0] == "salad"):
        return "veg"
    if toks and toks[0] in ONE_DISH_FIRST:
        return "one"
    return "main"


# =================================================================== đổi nguyên liệu thành sản phẩm thật
def pack_amount(product):
    """(gam hoặc ml trong một đơn vị bán | None, số cái trong một đơn vị bán): 'túi 5kg' -> (5000, 1), 'vỉ 10 quả' -> (None, 10)."""
    grams, pcs = nlu.unit_amount(product)
    if grams is None:
        for text in (product.get("unit") or "", f"{product.get('unit') or ''} {product.get('name') or ''}"):
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ml|lit|l)\b", strip_accents(text))
            if m:
                grams = float(m.group(1).replace(",", ".")) * (1 if m.group(2) == "ml" else 1000)
                break
    return grams, pcs


def quantity(need_g, need_pcs, product):
    """Số đơn vị bán cần mua cho nhu cầu `need_g` gam/ml hoặc `need_pcs` cái. Quy cách không rõ thì ước lượng thận trọng,
    khách vẫn chỉnh được số lượng trước khi thêm vào giỏ."""
    grams, pcs = pack_amount(product)
    if need_pcs:
        if grams and pcs == 1:       # bán theo khối lượng nhưng model đếm theo cái: coi mỗi cái ~100g
            qty = math.ceil(need_pcs * 100 / grams)
        else:
            qty = math.ceil(need_pcs / max(pcs, 1))
    elif need_g:
        if grams:
            qty = math.ceil(need_g / grams)
        elif pcs > 1:
            qty = 1
        else:
            qty = max(1, min(3, round(need_g / FALLBACK_PACK_G)))
    else:
        qty = 1
    return max(1, min(qty, MAX_QTY))


class Resolver:
    """Khớp tên nguyên liệu (do AI viết, tiếng Việt có hoặc không dấu) với sản phẩm đang bán, dùng chỉ mục tìm kiếm của trợ lý."""

    def __init__(self, catalog, stopwords=None):
        self.index = nlu.CatalogIndex(catalog, stopwords or {})

    def find(self, *names):
        for name in names:
            toks = [t for t in tokens(name or "") if not t.isdigit()]
            attempts = [toks]
            if len(toks) >= 3:
                attempts.append(toks[1:])  # "thịt ba rọi" -> "ba rọi": tên hàng trong danh mục thường bỏ chữ "thịt"
            for kw in attempts:
                if not kw:
                    continue
                hits = self.index.search("", limit=4, min_score=0.6, content=kw)
                if hits:
                    return hits[0][0]
        return None


# =================================================================== đọc kết quả của AI
def _text(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _amount(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= 50000 else None


def clean_spec(parsed):
    """Chuẩn hóa JSON do AI trả về thành {"title", "dishes": [{"name", "how", "ingredients": [...]}]}; None nếu không dùng được.
    Mọi trường đều bị kiểm tra kiểu và cắt độ dài vì đây là dữ liệu từ bên ngoài."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("dishes"), list):
        return None
    dishes = []
    for d in parsed["dishes"]:
        if not isinstance(d, dict) or not isinstance(d.get("ingredients"), list):
            continue
        name = _text(d.get("name"), 60)
        ingredients = []
        for i in d["ingredients"][:MAX_INGREDIENTS]:
            if not isinstance(i, dict):
                continue
            label = _text(i.get("name"), 50)
            search = _text(i.get("search"), 50) or label
            if not label:
                continue
            ingredients.append({"name": label, "search": search, "grams": _amount(i.get("amount_g")),
                                "pieces": _amount(i.get("pieces")),
                                "pantry": i.get("pantry") is True or str(i.get("pantry")).lower() == "true"})
        if name and ingredients:
            dishes.append({"name": name, "how": _text(d.get("how"), 220), "ingredients": ingredients})
        if len(dishes) >= MAX_DISHES:
            break
    if not dishes:
        return None
    return {"title": _text(parsed.get("title"), 80), "dishes": dishes}


def lines_from_spec(spec, resolver):
    """Tra sản phẩm thật cho nguyên liệu của AI. Trả về (danh sách món kèm dòng hàng, tên nguyên liệu cửa hàng chưa bán)."""
    entries, missing, used = [], [], set()
    for d in spec["dishes"]:
        lines = []
        for ing in d["ingredients"]:
            product = resolver.find(ing["search"], ing["name"])
            if not product:
                if not ing["pantry"] and ing["name"] not in missing:
                    missing.append(ing["name"])
                continue
            if (d["name"], product["id"]) in used:
                continue
            used.add((d["name"], product["id"]))
            qty = 1 if ing["pantry"] else quantity(ing["grams"], ing["pieces"], product)
            lines.append({"product": product, "qty": qty, "pantry": ing["pantry"], "label": ing["name"]})
        entries.append({"name": d["name"], "how": d["how"], "lines": lines})
    return entries, missing


# =================================================================== gộp thành kết quả trả về giao diện
def assemble(entries, to_card):
    """Gộp các món thành một danh sách đi chợ: cùng một sản phẩm dùng cho nhiều món thì cộng dồn số lượng.
    entries: [{"name", "how", "lines": [{"product", "qty", "pantry", "label"}]}]. to_card(product) -> thẻ sản phẩm."""
    merged = {}
    dishes = []
    for e in entries:
        ids = []
        for line in e["lines"]:
            p = line["product"]
            item = merged.get(p["id"])
            if item is None:
                item = merged[p["id"]] = {"product": to_card(p), "qty": line["qty"], "pantry": line["pantry"],
                                          "label": line["label"], "dishes": []}
            elif line["pantry"]:
                pass  # gia vị dùng lại cho món khác: vẫn chỉ một lần mua
            elif item["pantry"]:
                item["qty"], item["pantry"] = line["qty"], False  # là nguyên liệu chính ở món này thì phải mua đủ số lượng
            else:
                item["qty"] = min(MAX_QTY, item["qty"] + line["qty"])
            if e["name"] not in item["dishes"]:
                item["dishes"].append(e["name"])
            ids.append(p["id"])
        dishes.append({"name": e["name"], "how": e.get("how") or "", "item_ids": ids})
    items = list(merged.values())
    for item in items:
        item["line_total"] = item["qty"] * (item["product"].get("final_price") or 0)
    items.sort(key=lambda x: (x["pantry"], x["dishes"][0] if x["dishes"] else ""))
    return dishes, items


def totals(items):
    """(tổng nguyên liệu chính, tổng gồm cả gia vị). Ngân sách so với nguyên liệu chính vì gia vị mặc định nhà đã có."""
    main = sum(i["line_total"] for i in items if not i["pantry"])
    return main, main + sum(i["line_total"] for i in items if i["pantry"])


def budget_feedback(items, budget):
    """Đoạn nhắc gửi lại cho AI khi thực đơn vượt ngân sách: giá thật của từng dòng để AI bớt/đổi món đắt."""
    lines = "\n".join(f"- {i['label']}: {i['qty']} x {money(i['product']['final_price'])} = {money(i['line_total'])}"
                      for i in items if not i["pantry"])
    main, _ = totals(items)
    return (f"Lần lập trước, giá thật ở cửa hàng cộng lại là {money(main)}, VƯỢT ngân sách {money(budget)}.\n"
            f"Chi tiết giá:\n{lines}\nHãy lập lại thực đơn rẻ hơn (bớt món, giảm khẩu phần mỗi món, hoặc đổi sang nguyên liệu rẻ) "
            f"để nguyên liệu chính không vượt {money(budget)}.")


# =================================================================== thực đơn cục bộ (không cần AI ngoài)
def _rotate(seq, seed):
    if not seq:
        return []
    k = seed % len(seq)
    return seq[k:] + seq[:k]


def local_menu(bot, catalog, text, servings, budget=None, avoid=(), today=None):
    """Lập thực đơn bằng cơ sở món ăn của trợ lý cục bộ. Trả về (tên thực đơn, [món kèm dòng hàng], nguyên liệu thiếu).
    Thứ tự ưu tiên: món khách nêu tên > bữa cơm gia đình (trưa/tối) > món hợp bữa sáng/ăn vặt/nhậu. Món gợi ý xoay theo ngày."""
    ctx = Ctx(bot, text, [], catalog, lambda pid: {})
    seed = (today or date.today()).toordinal() + zlib.crc32(strip_accents(text).encode()) % 997
    avoid = {a.strip().lower() for a in avoid}
    plans = {}

    def plan(dish):
        if dish["name"] not in plans:
            p = bot.plan(dish, servings, ctx)
            p["cost"] = sum(x["qty"] * x["product"]["final_price"] for x in p["lines"] if not x["pantry"])
            plans[dish["name"]] = p
        return plans[dish["name"]]

    def usable(role, meals=None):
        pool = [d for d in bot.dishes.dishes if dish_role(d) == role and d["name"].lower() not in avoid
                and (not meals or set(meals) & set(d.get("meals", [])))]
        for d in _rotate(pool, seed):
            if plan(d)["usable"]:
                yield d

    named = []
    for chunk in SPLIT_DISHES.split(text):
        d = bot.dishes.find(chunk)
        if d and d["name"] not in [n["name"] for n in named]:
            named.append(d)
    meals = ctx.meals or [default_meal()]
    label = MEAL_NAMES.get(meals[0], "bữa ăn")
    picks = []
    if named:
        picks = named[:MAX_DISHES]
        title = ", ".join(d["name"] for d in picks)
        title = title[:1].upper() + title[1:]
    elif set(meals) & {"trua", "toi"}:
        picks = _family_menu(usable, plan, budget or servings * DEFAULT_BUDGET_PER_PERSON)
        title = f"Bữa cơm gia đình ({label})"
    else:
        pool = [d for d in usable("snack", meals)] + [d for d in usable("one", meals)] + [d for d in usable("main", meals)]
        for d in pool:
            if len(picks) >= 2:
                break
            if budget is None or sum(plan(x)["cost"] for x in picks) + plan(d)["cost"] <= budget:
                picks.append(d)
        title = label[:1].upper() + label[1:]
    entries, missing = [], []
    for d in picks:
        p = plan(d)
        entries.append({"name": d["name"], "how": d.get("how") or "", "lines": p["lines"]})
        missing += [m for m in p["missing"] if m not in missing]
    return title, entries, missing


def _family_menu(usable, plan, budget):
    """Món mặn + canh + rau + cơm trắng sao cho vừa ngân sách; không vừa thì chọn bộ rẻ nhất."""
    rice = plan(RICE_DISH)
    best = None
    for n, main in enumerate(usable("main", ("trua", "toi"))):
        if n >= 14:
            break
        base = rice["cost"] + plan(main)["cost"]
        soup = next((s for s in usable("soup") if budget is None or base + plan(s)["cost"] <= budget), None)
        base += plan(soup)["cost"] if soup else 0
        veg = next((v for v in usable("veg") if budget is None or base + plan(v)["cost"] <= budget), None)
        base += plan(veg)["cost"] if veg else 0
        picks = [d for d in (main, soup, veg) if d]
        if budget is None or base <= budget:
            if soup or veg or budget is None:
                return picks + [RICE_DISH]
        if best is None or base < best[0]:
            best = (base, picks)
    if best:
        return best[1] + [RICE_DISH]
    return []
