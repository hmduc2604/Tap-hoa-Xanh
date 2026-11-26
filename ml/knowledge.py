"""Kiến thức nền cho trợ lý mua sắm: món ăn -> nguyên liệu, câu hỏi thường gặp, cách gọi sản phẩm.

Nguyên liệu ghi bằng TỪ KHÓA không dấu ("ca basa"), KHÔNG gắn cứng id sản phẩm. Khi trả lời, ai-service tra từ khóa
trong danh mục đang bán, nên thêm/đổi sản phẩm không phải huấn luyện lại. Nguyên liệu không tìm thấy trong cửa hàng
được báo rõ là "cần mua thêm ở nơi khác" thay vì bịa ra sản phẩm.

Trường của nguyên liệu: kw (từ khóa), g (gam mỗi người, để tính số lượng), pcs (số cái mỗi người), pantry=True
(đồ dùng sẵn trong bếp, chỉ cần 1 đơn vị và hiển thị sau cùng).
"""

# tên hiển thị, [cách gọi khác], [bữa], [nguyên liệu]
DISHES = [
    {"name": "canh chua cá", "aliases": ["canh chua", "canh chua cá basa", "canh chua cá lóc"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "ca basa", "g": 150}, {"kw": "ca chua", "g": 100}, {"kw": "dua", "missing": True},
                     {"kw": "gia do", "missing": True}, {"kw": "me", "missing": True},
                     {"kw": "nuoc mam", "pantry": True}, {"kw": "duong", "pantry": True}, {"kw": "hat nem", "pantry": True}]},
    {"name": "thịt kho trứng", "aliases": ["thịt kho tàu", "thịt kho", "thịt heo kho", "thịt kho nước dừa"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "ba roi", "g": 150}, {"kw": "trung ga", "pcs": 2}, {"kw": "nuoc mam", "pantry": True},
                     {"kw": "duong", "pantry": True}, {"kw": "nuoc tuong", "pantry": True},
                     {"kw": "nuoc dua", "missing": True}, {"kw": "hanh", "missing": True}, {"kw": "toi", "missing": True}]},
    {"name": "cá kho tộ", "aliases": ["cá kho", "cá basa kho", "cá kho tiêu"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "ca basa", "g": 150}, {"kw": "nuoc mam", "pantry": True}, {"kw": "duong", "pantry": True},
                     {"kw": "tuong ot", "pantry": True}, {"kw": "hanh", "missing": True}, {"kw": "tieu", "missing": True}]},
    {"name": "gà luộc", "aliases": ["gà luộc lá chanh", "ức gà luộc", "gà hấp"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "uc ga", "g": 150}, {"kw": "muoi", "pantry": True}, {"kw": "nuoc tuong", "pantry": True},
                     {"kw": "hat nem", "pantry": True}, {"kw": "chanh", "missing": True}, {"kw": "gung", "missing": True}]},
    {"name": "gà xào", "aliases": ["gà xào sả ớt", "gà áp chảo", "gà chiên", "gà rang", "ức gà xào"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "uc ga", "g": 150}, {"kw": "dau an", "pantry": True}, {"kw": "nuoc tuong", "pantry": True},
                     {"kw": "hat nem", "pantry": True}, {"kw": "duong", "pantry": True}, {"kw": "sa", "missing": True},
                     {"kw": "toi", "missing": True}]},
    {"name": "tôm rim", "aliases": ["tôm rang", "tôm rim mặn ngọt", "tôm chiên", "tôm xào"], "meals": ["trua", "toi", "nhau"],
     "ingredients": [{"kw": "tom", "g": 120}, {"kw": "nuoc mam", "pantry": True}, {"kw": "duong", "pantry": True},
                     {"kw": "dau an", "pantry": True}, {"kw": "tuong ot", "pantry": True}, {"kw": "hanh", "missing": True}]},
    {"name": "rau muống xào tỏi", "aliases": ["rau muống xào", "rau muống luộc", "xào rau muống"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "rau muong", "g": 150}, {"kw": "dau an", "pantry": True}, {"kw": "hat nem", "pantry": True},
                     {"kw": "toi", "missing": True}]},
    {"name": "cà chua xào trứng", "aliases": ["trứng xào cà chua", "cà chua trứng", "trứng cà chua"], "meals": ["trua", "toi", "sang"],
     "ingredients": [{"kw": "ca chua", "g": 120}, {"kw": "trung ga", "pcs": 2}, {"kw": "dau an", "pantry": True},
                     {"kw": "muoi", "pantry": True}, {"kw": "hat nem", "pantry": True}, {"kw": "hanh la", "missing": True}]},
    {"name": "trứng chiên", "aliases": ["trứng ốp la", "trứng rán", "trứng chiên nước mắm", "trứng tráng"], "meals": ["sang", "trua", "toi"],
     "ingredients": [{"kw": "trung ga", "pcs": 2}, {"kw": "dau an", "pantry": True}, {"kw": "nuoc mam", "pantry": True},
                     {"kw": "muoi", "pantry": True}]},
    {"name": "khoai tây chiên", "aliases": ["khoai chiên", "khoai tây chiên giòn", "khoai tây rán"], "meals": ["vat", "nhau", "toi"],
     "ingredients": [{"kw": "khoai tay", "g": 200}, {"kw": "dau an", "pantry": True}, {"kw": "muoi", "pantry": True},
                     {"kw": "tuong ot", "pantry": True}]},
    {"name": "cơm chiên trứng", "aliases": ["cơm chiên", "cơm rang", "cơm rang trứng", "cơm chiên dương châu"], "meals": ["trua", "toi", "sang"],
     "ingredients": [{"kw": "gao", "g": 100}, {"kw": "trung ga", "pcs": 1}, {"kw": "dau an", "pantry": True},
                     {"kw": "hat nem", "pantry": True}, {"kw": "nuoc tuong", "pantry": True}, {"kw": "hanh la", "missing": True}]},
    {"name": "bữa cơm gia đình", "aliases": ["cơm gia đình", "cơm nhà", "mâm cơm", "cơm tối", "cơm trưa", "mâm cơm cuối tuần"],
     "meals": ["trua", "toi"],
     "ingredients": [{"kw": "gao", "g": 100}, {"kw": "ba roi", "g": 120}, {"kw": "rau muong", "g": 100}, {"kw": "ca chua", "g": 60},
                     {"kw": "trung ga", "pcs": 1}, {"kw": "nuoc mam", "pantry": True}, {"kw": "hat nem", "pantry": True},
                     {"kw": "dau an", "pantry": True}]},
    {"name": "mì xào trứng", "aliases": ["mì trứng", "mì gói nấu trứng", "mì tôm trứng", "mì xào", "mì ăn liền"], "meals": ["sang", "khuya", "vat"],
     "ingredients": [{"kw": "mi", "pcs": 1, "unit_pcs": 1}, {"kw": "trung ga", "pcs": 1}, {"kw": "tuong ot", "pantry": True},
                     {"kw": "rau cai", "missing": True}]},
    {"name": "phở", "aliases": ["phở bò", "phở ăn liền", "ăn phở", "nấu phở"], "meals": ["sang", "toi"],
     "ingredients": [{"kw": "pho", "pcs": 1, "unit_pcs": 1}, {"kw": "trung ga", "pcs": 1}, {"kw": "tuong ot", "pantry": True},
                     {"kw": "hanh la", "missing": True}, {"kw": "rau thom", "missing": True}]},
    {"name": "bún thịt xào", "aliases": ["bún nước mắm", "bún trộn", "bún xào", "bún mắm"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "bun", "g": 100}, {"kw": "ba roi", "g": 100}, {"kw": "nuoc mam", "pantry": True},
                     {"kw": "duong", "pantry": True}, {"kw": "rau muong", "g": 50}, {"kw": "dua leo", "missing": True},
                     {"kw": "hanh phi", "missing": True}]},
    {"name": "miến gà", "aliases": ["miến xào", "miến xào gà", "miến nấu gà", "miến trộn"], "meals": ["trua", "toi", "sang"],
     "ingredients": [{"kw": "mien", "g": 50}, {"kw": "uc ga", "g": 100}, {"kw": "nam huong", "g": 10},
                     {"kw": "nuoc tuong", "pantry": True}, {"kw": "dau an", "pantry": True}, {"kw": "hanh", "missing": True}]},
    {"name": "món chay nấm hương", "aliases": ["đồ chay", "món chay", "nấm hương xào", "nấu chay", "ăn chay"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "nam huong", "g": 15}, {"kw": "mien", "g": 40}, {"kw": "rau muong", "g": 100},
                     {"kw": "nuoc tuong", "pantry": True}, {"kw": "dau an", "pantry": True}]},
    {"name": "cháo gà", "aliases": ["cháo", "cháo trắng", "cháo ức gà", "nấu cháo"], "meals": ["sang", "toi"],
     "ingredients": [{"kw": "gao", "g": 40}, {"kw": "uc ga", "g": 100}, {"kw": "nuoc mam", "pantry": True},
                     {"kw": "hat nem", "pantry": True}, {"kw": "gung", "missing": True}, {"kw": "hanh la", "missing": True}]},
    {"name": "xôi", "aliases": ["xôi ngọt", "xôi mặn", "nấu xôi", "đồ xôi", "xôi nếp"], "meals": ["sang"],
     "ingredients": [{"kw": "nep", "g": 100}, {"kw": "duong", "pantry": True}, {"kw": "muoi", "pantry": True},
                     {"kw": "dau xanh", "missing": True}, {"kw": "dua nao", "missing": True}]},
    {"name": "chè chuối nếp", "aliases": ["chè", "chè chuối", "nấu chè", "chè nếp", "chè ngọt"], "meals": ["vat"],
     "ingredients": [{"kw": "nep", "g": 40}, {"kw": "chuoi", "g": 150}, {"kw": "duong", "pantry": True},
                     {"kw": "sua dac", "pantry": True}, {"kw": "muoi", "pantry": True}, {"kw": "nuoc cot dua", "missing": True}]},
    {"name": "bánh mì pate", "aliases": ["bánh mì", "bánh mì pate trứng", "bánh mì kẹp", "sandwich"], "meals": ["sang"],
     "ingredients": [{"kw": "pate", "pcs": 0.3}, {"kw": "ca chua", "g": 50}, {"kw": "trung ga", "pcs": 1},
                     {"kw": "tuong ot", "pantry": True}, {"kw": "banh mi", "missing": True}, {"kw": "dua leo", "missing": True}]},
    {"name": "bữa sáng nhanh gọn", "aliases": ["bữa sáng", "ăn sáng", "đồ ăn sáng", "sáng nay ăn gì", "bữa sáng dinh dưỡng", "bữa sáng cho bé"],
     "meals": ["sang"],
     "ingredients": [{"kw": "yen mach", "g": 40}, {"kw": "sua tuoi", "pcs": 1}, {"kw": "chuoi", "g": 100},
                     {"kw": "trung ga", "pcs": 1}, {"kw": "sua chua", "pcs": 0.5}]},
    {"name": "cà phê sữa", "aliases": ["cà phê", "cafe sữa", "pha cà phê", "cà phê sáng", "cafe"], "meals": ["sang", "vat"],
     "ingredients": [{"kw": "ca phe", "pcs": 2, "unit_pcs": 1}, {"kw": "sua dac", "pantry": True}, {"kw": "duong", "pantry": True},
                     {"kw": "banh quy", "pcs": .3}]},
    {"name": "tiệc bia đồ nhắm", "aliases": ["đồ nhắm", "tiệc bia", "nhậu", "đi nhậu", "bữa nhậu", "liên hoan", "tiệc bạn bè", "tụ tập bạn bè"],
     "meals": ["nhau", "toi"],
     "ingredients": [{"kw": "bia", "pcs": 4}, {"kw": "snack", "pcs": 1}, {"kw": "nuoc suoi", "pcs": 1}, {"kw": "coca", "pcs": 1},
                     {"kw": "tom", "g": 100}, {"kw": "dau phong", "missing": True}]},
    {"name": "trái cây tráng miệng", "aliases": ["trái cây", "tráng miệng", "hoa quả", "ăn vặt trái cây", "đĩa trái cây", "sinh tố"],
     "meals": ["vat"],
     "ingredients": [{"kw": "tao", "g": 150}, {"kw": "cam", "g": 150}, {"kw": "chuoi", "g": 100}, {"kw": "sua chua", "pcs": 1}]},
    {"name": "ăn vặt cho bé", "aliases": ["bánh kẹo cho bé", "ăn vặt cho trẻ", "snack cho bé", "đồ ăn cho trẻ em"], "meals": ["vat"],
     "ingredients": [{"kw": "chocopie", "pcs": 2}, {"kw": "keo", "pcs": 1}, {"kw": "sua chua", "pcs": 1}, {"kw": "snack", "pcs": 1},
                     {"kw": "banh gao", "pcs": 1}]},
    {"name": "salad khoai tây", "aliases": ["khoai tây trộn", "gỏi khoai tây"], "meals": ["trua", "toi"],
     "ingredients": [{"kw": "khoai tay", "g": 150}, {"kw": "trung ga", "pcs": 1}, {"kw": "muoi", "pantry": True},
                     {"kw": "mayonnaise", "missing": True}, {"kw": "ca rot", "missing": True}]},
]

# nhắc tới bữa nào -> mã bữa trong DISHES[*]["meals"]
MEAL_WORDS = {
    "sang": ["buoi sang", "bua sang", "an sang", "sang nay", "breakfast"],
    "trua": ["buoi trua", "bua trua", "trua nay", "an trua"],
    "toi": ["buoi toi", "bua toi", "toi nay", "an toi", "bua com", "com toi"],
    "nhau": ["nhau", "bia ruou", "tiec", "lien hoan", "tu tap"],
    "vat": ["an vat", "do an vat", "trang mieng", "an nhe"],
    "khuya": ["khuya", "dem khuya", "an dem"],
}

# câu hỏi thường gặp: từ khóa không dấu (chỉ cần khớp một) -> câu trả lời
FAQ = [
    {"id": "gio_mo_cua", "keywords": ["mo cua", "dong cua", "gio lam", "may gio", "gio hoat dong", "khi nao mo"],
     "answer": "Tạp Hóa Xanh mở cửa mỗi ngày từ 6:00 đến 22:00, kể cả cuối tuần và ngày lễ."},
    {"id": "phi_ship", "keywords": ["phi ship", "phi giao", "mien phi", "free ship", "freeship", "tien ship", "ship bao nhieu", "tien giao"],
     "answer": "Đơn từ 300.000đ được miễn phí giao hàng. Đơn nhỏ hơn có phí giao hàng nhỏ, hệ thống hiển thị rõ trước khi bạn đặt."},
    {"id": "thoi_gian_giao", "keywords": ["bao lau", "bao nhieu lau", "may tieng", "khi nao giao", "thoi gian giao", "giao nhanh", "giao trong"],
     "answer": "Cửa hàng giao hàng trong khoảng 2 giờ kể từ khi đơn được xác nhận (trong giờ mở cửa)."},
    {"id": "thanh_toan", "keywords": ["thanh toan", "tra tien", "chuyen khoan", "cod", "vi dien tu", "xanh pay", "tien mat", "visa"],
     "answer": "Có 3 cách thanh toán: tiền mặt khi nhận hàng (COD), chuyển khoản và ví Xanh Pay. Đơn trả bằng ví sẽ tự được xác nhận."},
    {"id": "doi_tra", "keywords": ["doi tra", "hoan tien", "tra hang", "hang loi", "hu hong", "bao hanh", "khieu nai"],
     "answer": "Nếu hàng lỗi hoặc giao sai, bạn báo trong ngày nhận hàng để cửa hàng đổi hoặc hoàn tiền. Đơn chưa giao có thể tự hủy trong mục Đơn hàng."},
    {"id": "dia_chi", "keywords": ["dia chi", "o dau", "cua hang o", "cho nao", "hotline", "so dien thoai", "lien he", "gan day"],
     "answer": "Cửa hàng ở TP. Thủ Đức, TP.HCM. Thông tin liên hệ có ở chân trang web. Bạn có thể đặt hàng online và nhận tại nhà."},
]

# tên hiển thị có dấu của từ khóa nguyên liệu (dùng khi báo "cần mua thêm nơi khác" hoặc "cửa hàng chưa có")
LABELS = {
    "ba roi": "thịt ba rọi", "banh gao": "bánh gạo", "banh mi": "bánh mì", "banh quy": "bánh quy", "bia": "bia", "bun": "bún khô",
    "ca basa": "cá basa", "ca chua": "cà chua", "ca phe": "cà phê", "ca rot": "cà rốt", "cam": "cam", "chanh": "chanh",
    "chocopie": "bánh Chocopie", "chuoi": "chuối", "coca": "Coca-Cola", "dau an": "dầu ăn", "dau phong": "đậu phộng",
    "dau xanh": "đậu xanh", "dua": "dưa chua", "dua leo": "dưa leo", "dua nao": "dừa nạo", "duong": "đường", "gao": "gạo",
    "gia do": "giá đỗ", "gung": "gừng", "hanh": "hành", "hanh la": "hành lá", "hanh phi": "hành phi", "hat nem": "hạt nêm",
    "keo": "kẹo", "khoai tay": "khoai tây", "mayonnaise": "sốt mayonnaise", "me": "me", "mi": "mì gói", "mien": "miến dong",
    "muoi": "muối", "nam huong": "nấm hương", "nep": "gạo nếp", "nuoc cot dua": "nước cốt dừa", "nuoc dua": "nước dừa",
    "nuoc mam": "nước mắm", "nuoc suoi": "nước suối", "nuoc tuong": "nước tương", "pate": "pate", "pho": "phở ăn liền",
    "rau cai": "rau cải", "rau muong": "rau muống", "rau thom": "rau thơm", "sa": "sả", "snack": "snack", "sua chua": "sữa chua",
    "sua dac": "sữa đặc", "sua tuoi": "sữa tươi", "tao": "táo", "tieu": "tiêu", "toi": "tỏi", "tom": "tôm",
    "trung ga": "trứng gà", "tuong ot": "tương ớt", "uc ga": "ức gà", "yen mach": "yến mạch",
}

# nhiều sản phẩm cùng khớp một nguyên liệu thì ưu tiên sản phẩm có từ này trong tên (chỉ là ưu tiên, không bắt buộc)
PREFER = {"gao": "jasmine", "pho": "vifon", "mi": "goi", "nuoc mam": "nam", "dau an": "neptune"}


# ===================================================================== MỞ RỘNG (catalog ~600 sản phẩm)
import os  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(__file__))
from common.nlp import tokens  # noqa: E402
from common.utils import strip_accents  # noqa: E402
from common.seed_data import CATEGORIES, KIND_OF, KINDS, PRODUCTS  # noqa: E402
from dishes_extra import ROWS as _EXTRA_ROWS, build as _build_dishes  # noqa: E402

LABELS.update({"hanh la": "hành lá", "hanh tim": "hành tím", "toi": "tỏi", "gung": "gừng", "sa cay": "sả", "dua leo": "dưa leo",
               "ca rot": "cà rốt", "rau thom": "rau thơm", "cai ngot": "cải ngọt", "dau phong": "đậu phộng", "dua thom": "dứa (thơm)",
               "sot mayonnaise": "sốt mayonnaise", "nuoc cot dua": "nước cốt dừa", "gia do": "giá đỗ", "banh mi sandwich": "bánh mì",
               "tieu den": "tiêu"})

# Cửa hàng nay đã bán những thứ trước đây phải "mua thêm nơi khác": đổi nguyên liệu cũ sang hàng có trong danh mục.
SOLD_NOW = {
    "hanh la": {"kw": "hanh la", "g": 10}, "hanh": {"kw": "hanh tim", "g": 10}, "toi": {"kw": "toi", "g": 5},
    "gung": {"kw": "gung", "g": 10}, "sa": {"kw": "sa cay", "g": 10}, "chanh": {"kw": "chanh", "g": 15},
    "dua leo": {"kw": "dua leo", "g": 40}, "ca rot": {"kw": "ca rot", "g": 40}, "rau thom": {"kw": "rau thom", "g": 20},
    "rau cai": {"kw": "cai ngot", "g": 50}, "dau phong": {"kw": "dau phong", "g": 10}, "dau xanh": {"kw": "dau xanh", "g": 40},
    "mayonnaise": {"kw": "sot mayonnaise", "pantry": True}, "nuoc cot dua": {"kw": "nuoc cot dua", "pantry": True},
    "gia do": {"kw": "gia do", "g": 30}, "banh mi": {"kw": "banh mi sandwich", "pcs": 0.3}, "dua": {"kw": "dua thom", "pcs": 0.3},
    "tieu": {"kw": "tieu den", "pantry": True},
}
for _dish in DISHES:
    _dish["ingredients"] = [dict(SOLD_NOW[i["kw"]]) if i.get("missing") and i["kw"] in SOLD_NOW else i for i in _dish["ingredients"]]

HOW_OLD = {
    "canh chua cá": "Nấu nước me, cho cà chua và dứa vào, nêm nước mắm, đường cho vị chua ngọt rồi thả cá basa, giá đỗ vào nấu chín tái.",
    "thịt kho trứng": "Ướp ba rọi với nước mắm, đường, kho lửa nhỏ cùng trứng luộc bóc vỏ khoảng 45 phút đến khi nước sánh.",
    "cá kho tộ": "Ướp cá basa với nước mắm, đường, tiêu, kho trong nồi đất lửa nhỏ đến khi nước kẹo lại và cá thấm vị.",
    "gà luộc": "Luộc gà với gừng, muối khoảng 20 phút, ngâm nước đá cho da giòn, chấm muối tiêu chanh hoặc nước tương.",
    "gà xào": "Ướp gà với hạt nêm, nước tương, đường, xào lửa lớn cùng sả tỏi băm đến khi thịt săn và thơm.",
    "tôm rim": "Rim tôm với nước mắm, đường, hành băm lửa vừa cho đến khi nước cạn sánh và tôm đổi màu đỏ đẹp.",
    "rau muống xào tỏi": "Phi thơm tỏi, cho rau muống vào xào lửa lớn khoảng 2 phút, nêm hạt nêm rồi tắt bếp ngay cho rau xanh giòn.",
    "cà chua xào trứng": "Xào cà chua cho ra nước sệt rồi đổ trứng đánh tan vào, đảo nhẹ đến khi trứng vừa chín, nêm nếm cho vừa.",
    "trứng chiên": "Đánh trứng với chút nước mắm, đổ vào chảo dầu nóng, chiên vàng hai mặt.",
    "khoai tây chiên": "Gọt khoai, cắt thanh, ngâm nước muối 10 phút, để ráo rồi chiên hai lần cho vàng giòn, chấm tương ớt.",
    "cơm chiên trứng": "Dùng cơm nguội, phi hành, đổ trứng vào đảo săn rồi cho cơm, nêm hạt nêm và nước tương, đảo lửa lớn.",
    "bữa cơm gia đình": "Nấu cơm, kho hoặc luộc thịt ba rọi, xào rau, chiên trứng và dọn cùng nước mắm chấm.",
    "mì xào trứng": "Chần mì cho mềm, xào cùng trứng và rau, nêm gia vị gói rồi dọn nóng.",
    "phở": "Chế nước sôi vào gói phở theo hướng dẫn, thêm trứng chần, hành lá và rau thơm cho thơm ngon.",
    "bún thịt xào": "Xào thịt ba rọi với tỏi, ăn cùng bún, rau sống, dưa leo, hành phi và chan nước mắm chua ngọt.",
    "miến gà": "Ngâm miến cho mềm, nấu nước dùng từ gà và nấm hương, cho miến vào chần chín và nêm nếm.",
    "món chay nấm hương": "Ngâm nấm hương cho nở, xào cùng rau, nêm nước tương và dầu ăn, dọn với miến hoặc cơm.",
    "cháo gà": "Nấu gạo thành cháo nhừ, luộc và xé ức gà, trộn vào cháo, nêm nước mắm, rắc gừng và hành lá.",
    "xôi": "Ngâm nếp qua đêm, trộn muối rồi hấp 30 phút; xôi ngọt thêm đường và dừa nạo.",
    "chè chuối nếp": "Nấu nếp với nước đường, cho chuối thái lát vào, nêm muối và rưới nước cốt dừa.",
    "bánh mì pate": "Phết pate lên bánh mì, thêm cà chua, trứng chiên, dưa leo và chút tương ớt.",
    "bữa sáng nhanh gọn": "Chế yến mạch với sữa nóng, thêm chuối thái lát, dùng kèm trứng luộc và sữa chua.",
    "cà phê sữa": "Pha cà phê với nước nóng, thêm sữa đặc theo khẩu vị, khuấy đều rồi đổ lên đá.",
    "tiệc bia đồ nhắm": "Chuẩn bị bia lạnh, snack, tôm luộc hoặc rang muối và nước ngọt cho bạn bè nhâm nhi.",
    "trái cây tráng miệng": "Rửa sạch, cắt miếng vừa ăn, bày đĩa và dùng kèm sữa chua.",
    "ăn vặt cho bé": "Chọn bánh quy, kẹo, sữa chua và snack ít đường cho bé, chia thành phần nhỏ.",
    "salad khoai tây": "Luộc khoai tây và trứng, cắt hạt lựu, trộn với cà rốt, mayonnaise và chút muối.",
}
for _d in DISHES:
    if _d["name"] in HOW_OLD:
        _d["how"] = HOW_OLD[_d["name"]]

DISHES += _build_dishes(_EXTRA_ROWS, LABELS)
PREFER["nep"] = "cai"


def _check_dishes():
    seen = {}
    for d in DISHES:
        for phrase in [d["name"]] + d["aliases"]:
            key = " ".join(tokens(phrase))
            if key in seen and seen[key] != d["name"]:
                raise ValueError(f"cách gọi '{phrase}' trùng giữa '{seen[key]}' và '{d['name']}'")
            seen[key] = d["name"]
    unknown = {m for d in DISHES for m in d["meals"]} - set(MEAL_WORDS)
    if unknown:
        raise ValueError(f"mã bữa không có trong MEAL_WORDS: {unknown}")


_check_dishes()

FAQ += [
    {"id": "han_su_dung", "keywords": ["han su dung", "han dung", "date", "con han", "het han", "can date", "ngay san xuat"],
     "answer": "Hàng đóng gói có hạn sử dụng in trên bao bì và cửa hàng không bán hàng đã hết hạn. Nếu nhận hàng cận date hoặc "
               "hết hạn, bạn báo trong ngày nhận để cửa hàng đổi hoặc hoàn tiền."},
    {"id": "hang_tuoi", "keywords": ["hang tuoi", "rau tuoi", "thit tuoi", "ca tuoi", "tuoi khong", "nhap hang", "hang moi", "tuoi song"],
     "answer": "Rau củ, trái cây, thịt, cá nhập mỗi ngày và được đóng gói giữ lạnh. Bạn nên đặt vào buổi sáng để nhận hàng tươi nhất trong ngày."},
    {"id": "ma_giam_gia", "keywords": ["ma giam gia", "nhap ma", "coupon", "voucher", "ma khuyen mai", "dung ma"],
     "answer": "Bạn nhập mã giảm giá ở trang Giỏ hàng, hệ thống tính lại tổng tiền ngay. Mỗi mã có điều kiện đơn tối thiểu và hạn dùng riêng."},
    {"id": "bao_quan_dong_lanh", "keywords": ["bao quan", "dong lanh", "tu lanh", "ha dong", "gia nhiet", "de duoc bao lau"],
     "answer": "Đồ đông lạnh và hàng tươi được giữ lạnh khi giao. Bạn bỏ vào tủ lạnh ngay khi nhận hàng và dùng theo hướng dẫn trên bao bì."},
    {"id": "het_hang", "keywords": ["het hang", "bao gio co hang", "khi nao co lai", "tam het", "co hang lai"],
     "answer": "Món nào hết hàng sẽ hiện \"Hết hàng\" và chưa thêm vào giỏ được. Hàng bán chạy được nhập bổ sung thường xuyên, bạn quay lại sau nhé."},
]


# ===================================================================== CÁCH KHÁCH GỌI SẢN PHẨM (sinh từ nhóm hàng)
_SIZE_WORDS = {"kg", "g", "ml", "l", "lon", "hop", "chai", "goi", "tui", "thung", "loc", "cai", "vi", "bo", "khay", "cuon", "ly", "to", "mieng"}
_FRESH_CATEGORIES = {7, 8}  # rau củ, thịt cá: khách ít gọi theo thương hiệu


def _short_name(name, limit=5):
    """'Nước mắm Chinsu cá cơm 500ml' -> 'nước mắm chinsu cá cơm' (bỏ số, quy cách; giữ dấu như khách gõ)."""
    words = []
    for w in name.replace("(", " ").replace(")", " ").replace(",", " ").split():
        plain = strip_accents(w.lower())
        if any(ch.isdigit() for ch in plain) or plain in _SIZE_WORDS or plain in ("-", "&"):
            continue
        words.append(w.lower())
    return " ".join(words[:limit])


def build_product_aliases():
    """phrase (không dấu hoặc có dấu) -> tập SKU chấp nhận được.

    Ba loại: (1) nhóm hàng ("nước mắm", "bia"); (2) nhóm + thương hiệu ("bia tiger", "sữa vinamilk");
    (3) tên sản phẩm rút gọn ("nước mắm chinsu cá cơm"). Cách gọi chung chung được thu hẹp theo từ khóa có trong tên:
    "cà rốt" chỉ ra sản phẩm có chữ cà rốt thay vì cả nhóm rau củ."""
    members = defaultdict(list)
    for p in PRODUCTS:
        members[KIND_OF[p[1]]].append(p)
    out = defaultdict(set)
    for kind, spec in KINDS.items():
        items = members[kind]
        labels = [spec["label"]] if " và " not in spec["label"] and "," not in spec["label"] else []
        for phrase in labels + spec["aliases"]:
            wanted = set(tokens(phrase))
            narrowed = [p[1] for p in items if wanted <= set(tokens(p[3])) | set(tokens(p[4]))]
            out[phrase].update(narrowed or [p[1] for p in items])
        # "nhóm + thương hiệu" chỉ có nghĩa khi tên nhóm có mặt trong phần lớn sản phẩm của nhóm ("bia Tiger" được, "tiêu Vifon" thì không)
        def coverage(alias):
            wanted = set(tokens(alias))
            return sum(wanted <= set(tokens(p[3])) for p in items) / len(items)
        heads = [a for a in spec["aliases"] if coverage(a) >= 0.6]
        by_brand = defaultdict(list)
        for p in items:
            if p[0] not in _FRESH_CATEGORIES:
                by_brand[p[4]].append(p[1])
        if heads and len(by_brand) >= 2:
            for brand, skus in by_brand.items():
                out[f"{heads[0]} {brand}"].update(skus)
    for p in PRODUCTS:
        phrase = _short_name(p[3])
        if len(phrase.split()) >= 2:
            out[phrase].add(p[1])
    return {k: v for k, v in out.items() if v}


PRODUCT_ALIASES = build_product_aliases()
