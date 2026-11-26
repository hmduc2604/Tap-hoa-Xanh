"""Sinh dữ liệu huấn luyện cho trợ lý mua sắm: câu hỏi tiếng Việt kèm ý định và thực thể.

Mỗi ý định có nhiều MẪU CÂU. Để đo khả năng khái quát hóa (không chỉ thuộc lòng), một phần mẫu câu, một phần tên
sản phẩm và một phần tên món chỉ xuất hiện ở tập kiểm tra. Câu được làm "bẩn" giống cách khách gõ thật: bỏ dấu, viết tắt
(ko, đc, mk, bn), gõ sai chữ, thêm lời đệm ("bạn ơi", "nhé", "giúp mình").

    python ml/generate_utterances.py        # ghi ml/data/utterances.json
"""
import json
import os
import random
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from common.utils import strip_accents  # noqa: E402
from knowledge import DISHES, PRODUCT_ALIASES  # noqa: E402

TEMPLATES = {
    "greeting": ["xin chào", "chào bạn", "hello", "hi shop", "alo", "chào shop ơi", "bạn ơi", "shop ơi có ai không", "chào buổi sáng",
                 "hey", "chào trợ lý", "chào buổi tối", "xin chào trợ lý mua sắm", "ê bot", "hế lô"],
    "about_bot": ["bạn là ai", "bạn làm được gì", "bạn có thể giúp gì cho mình", "bạn là bot à", "trợ lý này giúp được gì",
                  "bạn biết làm những gì", "giới thiệu về bạn đi", "chức năng của bạn là gì", "mình hỏi được những gì",
                  "bạn tên gì", "ai tạo ra bạn", "bạn hoạt động thế nào", "bạn có phải người thật không", "mình có thể nhờ bạn việc gì",
                  "bạn hỗ trợ được những gì", "trợ lý mua sắm là gì",
                  "bạn là phần mềm gì vậy", "bạn hiểu tiếng việt không", "bạn học từ đâu mà trả lời được", "bạn hoạt động ra sao",
                  "cách bạn trả lời câu hỏi là gì", "bạn có phải trí tuệ nhân tạo không"],
    "thanks": ["cảm ơn bạn", "cảm ơn nhé", "thanks", "ok cảm ơn", "tuyệt vời cảm ơn", "cám ơn shop nhiều", "hay quá cảm ơn",
               "ok rồi cảm ơn", "thank you", "cảm ơn nhiều lắm", "được rồi cảm ơn bạn", "ok luôn cảm ơn"],
    "goodbye": ["tạm biệt", "bye bye", "hẹn gặp lại", "mình đi đây", "thôi mình thoát nhé", "chào nhé hẹn lần sau", "bye",
                "mình off đây", "tạm biệt nhé", "thôi chào nha"],
    "find_product": ["có {prod} không", "bên bạn có bán {prod} không", "cho mình xem {prod}", "tìm {prod}", "mình muốn mua {prod}",
                     "{prod} còn hàng không", "shop có {prod} không", "cần mua {prod}", "xem giúp mình {prod}", "bán {prod} không shop",
                     "mình tìm {prod}", "{prod} đâu rồi", "cho hỏi {prod}", "đặt {prod}", "{prod} loại nào ngon",
                     "có những loại {prod} nào", "chỉ mình chỗ mua {prod}", "mua {prod}", "lấy cho mình {prod}", "hiện có {prod} nào",
                     "{prod} có sẵn không", "cho mình coi {prod}", "bên shop có {prod} hông", "mình cần {prod}", "tìm giúp {prod}",
                     "{prod} hết hàng chưa",
                     "shop còn {prod} không ạ", "mình đang cần kiếm {prod}", "ở đây có bán {prod} không", "{prod} có không bạn",
                     "tìm giúp mình món {prod}", "cho xem {prod} đi", "có {prod} loại nào không", "muốn mua {prod} thì có không",
                     "bạn có {prod} không", "nhà mình thiếu {prod} bên bạn có bán không", "xem {prod} giúp mình", "kiếm {prod}"],
    "price_query": ["{prod} giá bao nhiêu", "giá {prod} bao nhiêu vậy", "{prod} bao nhiêu tiền", "{prod} giá sao shop",
                    "cho hỏi giá {prod}", "{prod} bán sao", "{prod} nhiêu tiền", "báo giá {prod} giúp mình",
                    "một {prod} hết bao nhiêu", "{prod} giá thế nào", "giá của {prod} là bao nhiêu", "{prod} đang bán giá nào",
                    "{prod} bao nhiêu 1 cái", "{prod} giá hiện tại", "cho mình biết giá {prod}", "{prod} mắc không"],
    "recipe": ["nấu {dish} cần mua gì", "mua gì để nấu {dish}", "làm {dish} cần nguyên liệu gì", "nguyên liệu nấu {dish}",
               "cho mình danh sách mua để làm {dish}", "mình muốn nấu {dish} cho {n} người", "nấu {dish} cho {n} người cần gì",
               "hôm nay nấu {dish} thì mua gì", "gợi ý nguyên liệu {dish}", "{dish} cần những gì", "lên danh sách đi chợ làm {dish}",
               "chuẩn bị nấu {dish}", "định làm {dish} mua gì", "công thức {dish} cần đồ gì", "đi chợ cho món {dish}",
               "tối nay mình làm {dish} cho {n} người", "mua đồ làm {dish} cho {n} người ăn", "cần chuẩn bị gì để nấu {dish}",
               "muốn làm {dish} thì mua những gì", "nguyên liệu {dish} cho {n} người", "cách nấu {dish} cần mua gì",
               "hướng dẫn làm {dish}", "cách làm {dish} thế nào", "nấu {dish} thế nào cho ngon", "chỉ mình cách làm {dish}",
               "{dish} nấu sao", "mình muốn thử làm {dish}", "cuối tuần làm {dish} cần gì",
               "shop có đủ nguyên liệu làm {dish} không", "ngày mai định nấu {dish} mua đủ đồ ở đây được không",
               "muốn nấu {dish} bên bạn có đủ gia vị không", "{dish} làm cho {n} người thì lấy bao nhiêu"],
    "meal_suggest": ["hôm nay ăn gì", "gợi ý món ăn cho bữa tối", "bữa sáng nên ăn gì", "tối nay nấu gì ngon",
                     "gợi ý bữa trưa cho {n} người", "không biết nấu gì hôm nay", "nên nấu món gì", "ăn gì nhanh gọn",
                     "gợi ý thực đơn", "bữa tối cho gia đình {n} người", "có món nào dễ nấu không", "bữa sáng nhanh gọn",
                     "nấu gì cho cuối tuần", "đang đói không biết ăn gì", "gợi ý món nhậu", "trưa nay ăn gì", "tối nay ăn gì đây",
                     "gợi ý đồ ăn vặt", "món gì ngon cho bữa sáng",
                     "cuối tuần nên nấu gì cho cả nhà", "trời lạnh ăn món gì cho ấm", "gợi ý món chay cho bữa tối",
                     "bữa tối nhanh dưới 30 phút nấu gì", "ăn gì cho đỡ ngán", "thực đơn cho cả tuần", "nay ăn gì bây giờ",
                     "đồ ăn vặt nào ngon để nhâm nhi", "món gì đãi khách cuối tuần", "bữa trưa văn phòng nên mua gì"],
    "bought_together": ["mua {prod} thì nên mua thêm gì", "{prod} ăn kèm với gì", "mua {prod} tiện thể mua gì nữa",
                        "ai mua {prod} thường mua thêm gì", "gợi ý đồ mua kèm {prod}", "cần mua gì đi cùng {prod}",
                        "{prod} thường mua cùng món nào", "mua {prod} rồi nên lấy thêm gì", "kèm với {prod} thì mua gì",
                        "mua {prod} nên mua kèm gì", "{prod} hay được mua cùng với gì", "ngoài {prod} nên mua thêm gì"],
    "promotion": ["có khuyến mãi gì không", "đang giảm giá món nào", "hôm nay có sale gì", "có mã giảm giá không", "món nào đang giảm",
                  "có gì rẻ đang giảm giá", "khuyến mãi hôm nay", "cho mình xem hàng giảm giá", "sản phẩm đang sale",
                  "có ưu đãi gì không", "hàng khuyến mãi", "deal hôm nay", "đang có chương trình gì", "cho mình xem đồ đang giảm",
                  "shop có voucher không", "hôm nay giảm giá món nào", "mã khuyến mãi của shop", "tuần này có ưu đãi gì",
                  "có combo giảm giá không", "đồ nào đang được giảm giá vậy"],
    "budget": ["mình có {price} mua được gì", "tìm {prod} dưới {price}", "{prod} nào rẻ nhất", "cho mình {prod} giá rẻ",
               "mua đồ ăn tối với {price}", "có {prod} nào dưới {price} không", "ngân sách {price} nên mua gì",
               "{prod} giá tiết kiệm", "tìm {prod} rẻ rẻ", "cái nào rẻ nhất", "món nào dưới {price}", "có {price} thì mua gì",
               "{prod} dưới {price} có không", "gợi ý {prod} giá mềm"],
    "store_info": ["mấy giờ mở cửa", "cửa hàng đóng cửa lúc mấy giờ", "phí giao hàng bao nhiêu", "bao lâu thì giao tới",
                   "có miễn phí ship không", "giao hàng mất bao lâu", "địa chỉ cửa hàng ở đâu", "có nhận chuyển khoản không",
                   "thanh toán bằng gì được", "đổi trả thế nào", "cửa hàng ở đâu", "hotline là gì", "giờ làm việc của shop",
                   "có giao tận nhà không", "mua bao nhiêu thì free ship", "có cod không", "hàng lỗi thì đổi được không",
                   "shop có giao hàng không", "mình trả tiền bằng cách nào", "cửa hàng mở tới mấy giờ", "ship tới nhà mất mấy tiếng",
                   "có hỗ trợ ví điện tử không", "nhận chuyển khoản ngân hàng được không", "có quẹt thẻ khi nhận hàng không",
                   "thanh toán momo được không", "đơn nhỏ có tính phí ship không", "shop ở khu vực nào", "chính sách đổi trả ra sao",
                   "có trả góp hay thanh toán online không", "giờ nào shop nghỉ",
                   "đơn từ bao nhiêu thì miễn phí vận chuyển", "khi nào được freeship", "tổng tiền bao nhiêu thì không mất phí giao",
                   "ngưỡng miễn phí giao hàng là bao nhiêu", "đặt hàng tối thiểu bao nhiêu để được free ship"],
    "order_help": ["đơn hàng của mình đâu", "kiểm tra đơn hàng giúp mình", "mình muốn hủy đơn", "theo dõi đơn hàng ở đâu",
                   "đơn của mình giao chưa", "sao đơn chưa tới", "hủy đơn hàng vừa đặt", "xem lịch sử mua hàng",
                   "đơn mình đặt hôm qua đến đâu rồi", "làm sao hủy đơn", "tình trạng đơn hàng của mình", "đơn hàng bị trễ",
                   "đơn hàng chưa thấy giao", "kiểm tra giúp đơn đặt hôm qua", "muốn xem các đơn đã đặt", "hủy giúp mình đơn vừa đặt",
                   "đơn bị giao sai hàng", "theo dõi vận chuyển đơn của mình", "shipper chưa gọi mình",
                   "shipper chưa liên hệ với mình", "đơn đặt rồi mà chưa thấy ai giao", "đơn mình đang ở đâu rồi"],
    "out_of_scope": ["thời tiết hôm nay thế nào", "kể chuyện cười đi", "giá bitcoin hôm nay", "viết giúp mình bài thơ",
                     "giải bài toán này giúp mình", "tỉ số bóng đá tối qua", "hôm nay là thứ mấy", "dịch giúp mình câu này sang tiếng anh",
                     "cách đầu tư chứng khoán", "bạn thích màu gì", "viết code python giúp mình", "đặt vé máy bay",
                     "phim nào hay", "tin tức hôm nay", "kể chuyện ma đi", "ai là tổng thống mỹ", "cách chữa đau đầu",
                     "học tiếng nhật thế nào", "sửa giúp mình cái điện thoại", "bạn bao nhiêu tuổi",
                     "nên mua cổ phiếu nào", "dự đoán xổ số hôm nay", "bài hát nào đang hot", "hướng dẫn cài windows",
                     "cách làm bài tập toán lớp 5", "trường đại học nào tốt", "xin lời khuyên chuyện tình cảm",
                     "nên đi du lịch ở đâu", "thủ đô của nước pháp là gì", "bây giờ là mấy giờ", "tính giúp mình 25 nhân 36",
                     "cách học tiếng anh nhanh", "xe máy nào chạy bền", "bạn có người yêu chưa", "giá vàng hôm nay",
                     "viết giúp mình bài văn tả mẹ", "lịch thi đấu giải bóng đá", "cách tăng chiều cao", "làm sao để giảm cân nhanh",
                     "tử vi hôm nay thế nào", "tìm việc làm ở đâu", "bạn ăn cơm chưa", "kể một câu chuyện cổ tích", "đọc thơ đi",
                     "hát một bài đi", "nói chuyện với mình đi", "mình buồn quá", "sao hôm nay chán thế",
                     "lập trình web học từ đâu", "cách sửa lỗi máy tính", "đổi đô la sang tiền việt", "giải thích thuyết tương đối",
                     "làm cv xin việc thế nào", "nên chọn laptop nào", "mưa có kéo dài không", "ai thắng trận đấu hôm qua",
                     "thuê nhà giá rẻ ở đâu", "cách viết email cho sếp", "hôm nay có tin gì mới",
                     "trời nóng quá có mưa không nhỉ", "bạn có biết chơi game không", "soạn giúp mình đơn xin nghỉ học",
                     "đội nào vô địch năm ngoái", "viết giúp mình lời chúc sinh nhật sếp", "dự báo thời tiết cuối tuần"],
}
SENTENCE_INTENTS = {"greeting", "about_bot", "thanks", "goodbye", "out_of_scope"}  # không có lời đệm đầu câu

PREFIX = ["", "", "", "cho mình hỏi ", "bạn ơi ", "shop ơi ", "xin hỏi ", "ê ", "mình muốn hỏi ", "dạ ", "alo shop ", "hỏi chút nè "]
SUFFIX = ["", "", "", " nhé", " ạ", " giúp mình với", " nha", " đi bạn", " với ạ", " nhanh giúp mình", " được không", " thế"]
PRICES = ["100k", "50k", "200k", "30k", "20k", "100 nghìn", "50 ngàn", "200.000đ", "1 triệu", "500k", "70 nghìn", "150k",
          "300 nghìn đồng", "80k", "40.000đ", "2 triệu"]
SLANG = [("không", ["ko", "k", "hông", "hok"]), ("được", ["đc", "dc"]), ("mình", ["mk", "mik"]), ("bao nhiêu", ["bn", "bao nhiu"]),
         ("giá", ["gia", "giá"]), ("cho", ["cho"]), ("shop", ["sốp", "shop"]), ("với", ["vs"])]
NUMBERS = {2: "hai", 3: "ba", 4: "bốn", 5: "năm", 6: "sáu"}


def typo(word, rng):
    if len(word) < 4:
        return word
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(["drop", "dup", "swap"])
    if kind == "drop":
        return word[:i] + word[i + 1:]
    if kind == "dup":
        return word[:i] + word[i] + word[i:]
    return word[:i] + word[i + 1] + word[i] + word[i + 2:] if i + 2 <= len(word) else word


def noisy(text, rng):
    words = text.split()
    for i, w in enumerate(words):  # viết tắt
        for full, alts in SLANG:
            if w == full and rng.random() < .25:
                words[i] = rng.choice(alts)
    if rng.random() < .15 and words:  # gõ sai một từ
        j = rng.randrange(len(words))
        words[j] = typo(words[j], rng)
    text = " ".join(words)
    if rng.random() < .35:  # nhiều khách gõ không dấu
        text = strip_accents(text)
    return text


def split_pool(items, rng, test_frac=.25):
    items = list(items)
    rng.shuffle(items)
    k = max(2, int(len(items) * test_frac))
    return items[k:], items[:k]


def generate(per_intent_train=700, per_intent_test=150, seed=5):
    rng = random.Random(seed)
    dishes = {d["name"]: d for d in DISHES}
    dish_phrases = [(p, d["name"]) for d in DISHES for p in [d["name"]] + d["aliases"]]
    prod_train, prod_test = split_pool(PRODUCT_ALIASES.items(), rng)
    dish_train, dish_test = split_pool(dish_phrases, rng)
    data = {"train": [], "test": []}
    stopwords = set()
    for intent, templates in TEMPLATES.items():
        tpl_train, tpl_test = split_pool(templates, rng)
        for part, tpls, prods, dshs, count in (("train", tpl_train, prod_train, dish_train, per_intent_train),
                                               ("test", tpl_test, prod_test, dish_test, per_intent_test)):
            for _ in range(count):
                tpl = rng.choice(tpls)
                row = {"intent": intent}
                text = tpl
                if "{prod}" in tpl:
                    phrase, skus = rng.choice(prods)
                    text = text.replace("{prod}", phrase)
                    row["product"] = phrase
                    row["skus"] = sorted(skus)
                if "{dish}" in tpl:
                    phrase, canon = rng.choice(dshs)
                    text = text.replace("{dish}", phrase)
                    row["dish"] = canon
                if "{n}" in tpl:
                    n = rng.choice([2, 3, 4, 5, 6])
                    text = text.replace("{n}", rng.choice([str(n), str(n), NUMBERS[n]]))
                    row["servings"] = n
                if "{price}" in tpl:
                    price = rng.choice(PRICES)
                    text = text.replace("{price}", price)
                    row["price"] = price
                if intent not in SENTENCE_INTENTS:
                    text = rng.choice(PREFIX) + text + rng.choice(SUFFIX)
                row["text"] = noisy(text.strip(), rng)
                data[part].append(row)
    # từ "khung câu": từ lời đệm/viết tắt dùng chung cho mọi ý định, và từ trong mẫu câu của TỪNG ý định.
    # Tách theo ý định vì "kèm" -> "kem" trùng với sản phẩm "kem đánh răng": chỉ bỏ "kem" khi ý định là mua kèm.
    def frame(text):
        return set(strip_accents(text.replace("{prod}", " ").replace("{dish}", " ").replace("{n}", " ").replace("{price}", " ")).split())
    shared = set()
    for s in PREFIX + SUFFIX:
        shared |= frame(s)
    for _, alts in SLANG:
        for a in alts:
            shared |= frame(a)
    by_intent = {}
    for intent, tpls in TEMPLATES.items():
        words = set()
        for t in tpls:
            words |= frame(t)
        by_intent[intent] = sorted(w for w in words - shared if not w.isdigit())
    stopwords = {"shared": sorted(w for w in shared if not w.isdigit()), "by_intent": by_intent}
    return data, stopwords, dishes


if __name__ == "__main__":
    data, stopwords, _ = generate()
    out = os.path.join(os.path.dirname(__file__), "data", "utterances.json")
    json.dump({"seed": 5, "train": data["train"], "test": data["test"], "stopwords": stopwords}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"{len(data['train'])} câu huấn luyện, {len(data['test'])} câu kiểm tra, {len(stopwords['shared'])} từ đệm dùng chung -> {out}")
    for r in random.Random(1).sample(data["test"], 8):
        print("  ", r["intent"].ljust(16), r["text"])
