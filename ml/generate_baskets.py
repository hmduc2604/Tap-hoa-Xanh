"""Sinh dữ liệu giỏ hàng để huấn luyện mô hình gợi ý "thường mua cùng".

Cửa hàng demo chưa có nhiều đơn thật, nên giỏ hàng được MÔ PHỎNG theo các "nhiệm vụ mua sắm" (nấu cơm, ăn sáng, tiệc
bia, giặt giũ, làm bánh, chăm bé...). Mỗi nhiệm vụ là danh sách NHÓM HÀNG kèm xác suất xuất hiện (nhóm hàng của từng SKU
lấy từ common/catalog: nước mắm, bia, dầu gội...). Khi giỏ cần một nhóm, chọn ĐÚNG MỘT sản phẩm trong nhóm đó nên các
sản phẩm thay thế nhau (hai hãng nước mắm) không bao giờ nằm chung giỏ vì "nhu cầu".

Để mô hình có thứ để học ở mức sản phẩm chứ không chỉ mức nhóm hàng:
  - mỗi sản phẩm có độ phổ biến riêng (hàng bán chạy được chọn nhiều hơn, thùng/bình lớn ít hơn);
  - "trung thành thương hiệu": đã có hàng của một hãng trong giỏ thì dễ chọn tiếp hãng đó ở nhóm khác
    (Vinamilk với Vinamilk, Pulppy với Pulppy...).
Thêm nhiễu: món mua ngẫu nhiên ngoài nhiệm vụ, chọn đều theo nhóm hàng để mọi sản phẩm đều xuất hiện.

Khi có đơn thật, dùng dữ liệu đơn thật để huấn luyện lại (xem ml/README.md).

    python ml/generate_baskets.py            # ghi ml/data/baskets.json (30000 giỏ, cố định seed)
"""
import json
import math
import os
import random
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from common.seed_data import BASE_PRODUCTS, KIND_OF, PRODUCTS  # noqa: E402
from common.utils import strip_accents  # noqa: E402

SKUS = [p[1] for p in PRODUCTS]
BESTSELLERS = {p[1] for p in BASE_PRODUCTS}  # 55 sản phẩm gốc là hàng quen của cửa hàng demo: bán chạy hơn

# Mục trong nhiệm vụ: "nhóm" | "nhóm:từ khóa tên" (chỉ lấy sản phẩm có từ khóa) | (mục, mục, ...) = chọn một trong các mục
# Nhiệm vụ: (tên, trọng số xuất hiện, [(mục, xác suất)])
NOODLES = ("mi_goi", "pho_an_lien")
DRINKS = ("nuoc_ngot", "tra", "nuoc_trai_cay", "nuoc_tang_luc")
MILKS = ("sua_tuoi", "sua_hat")
SWEETS = ("banh_ngot", "banh_quy", "socola")
MISSIONS = [
    ("nấu cơm hằng ngày", 14, [("gao", .55), ("nuoc_mam", .6), ("hat_nem", .45), ("dau_an", .4), ("thit_heo:ba roi", .3),
                                ("trung:ga", .35), ("rau_la", .5), ("cu_qua", .4), ("muoi", .15), ("thit_ga_vit", .15)]),
    ("canh chua cá", 4, [("ca_tuoi", .9), ("cu_qua:ca chua", .85), ("nuoc_mam", .7), ("duong", .5), ("hat_nem", .35),
                         ("trai_cay:thom", .4), ("rau_thom", .5), ("rau_la", .25), ("gao", .3)]),
    ("thịt kho trứng", 4, [("thit_heo:ba roi", .95), ("trung:ga", .8), ("nuoc_mam", .8), ("duong", .7), ("nuoc_tuong", .45),
                           ("hat_nem", .3), ("tuong_ot", .15), ("tieu_gia_vi", .3), ("rau_thom", .4), ("gao", .4)]),
    ("gà luộc / chiên", 4, [("thit_ga_vit", .9), ("nuoc_tuong", .4), ("hat_nem", .45), ("muoi", .35), ("cu_qua:khoai tay", .3),
                            ("dau_an", .35), ("rau_thom", .5), ("tieu_gia_vi", .3)]),
    ("khoai tây chiên", 2, [("cu_qua:khoai tay", .9), ("dau_an", .85), ("muoi", .6), ("tuong_ot", .6), ("trung:ga", .4)]),
    ("hải sản", 4, [("hai_san", .9), ("muoi", .4), ("nuoc_mam", .45), ("tuong_ot", .3), ("rau_thom", .5), ("dau_an", .3),
                    ("bia", .15), ("tieu_gia_vi", .3)]),
    ("bún / phở tự nấu", 4, [("bun_pho_kho", .65), ("nuoc_mam", .5), ("thit_heo", .3), ("thit_bo", .3), ("nam_kho", .2),
                             ("rau_la", .4), ("rau_thom", .5), ("tuong_ot", .35), ("tieu_gia_vi", .3), ("hat_nem", .3)]),
    ("mì ăn liền", 8, [(NOODLES, .95), ("trung:ga", .5), ("tuong_ot", .3), ("nuoc_suoi", .3), ("xuc_xich", .2),
                       (("thit_hop", "ca_hop"), .1), ("rau_la", .15)]),
    ("bữa sáng", 7, [(("ngu_coc", "yen_mach"), .6), (MILKS, .85), ("trai_cay", .5), ("trung:ga", .35), ("sua_chua", .3),
                     ("banh_ngot", .25)]),
    ("cà phê sáng", 5, [("ca_phe", .95), ("sua_dac", .6), ("banh_quy", .35), ("duong", .3), ("banh_ngot", .2)]),
    ("ăn vặt cho bé", 6, [(SWEETS, .8), ("keo", .4), ("sua_chua", .5), ("sua_tuoi", .5), ("snack", .35), ("banh_gao", .35),
                          ("trai_cay", .25)]),
    ("tiệc bia bạn bè", 5, [("bia", .95), ("snack", .6), ("nuoc_ngot", .3), ("nuoc_suoi", .3), ("hat_say", .35),
                            ("hai_san_kho", .3), ("do_an_vat_khac", .2), ("hai_san", .15), ("tuong_ot", .15)]),
    ("giải khát", 4, [(DRINKS, .95), ("snack", .35), ("banh_quy", .15), ("nuoc_dien_giai", .1)]),
    ("xôi / chè", 2, [("gao_nep", .95), ("duong", .6), ("sua_dac", .45), ("muoi", .25), ("dau_hat", .55),
                      ("giam_nuoc_cot", .4), ("trai_cay:chuoi", .2)]),
    ("trái cây", 4, [("trai_cay", .9), ("trai_cay", .6), ("sua_chua", .2)]),
    ("giặt giũ, nhà cửa", 7, [("giat_giu", .7), ("xa_vai", .5), ("rua_chen", .55), ("lau_san", .35), ("giay", .4),
                              ("tui_mang_boc", .25), ("diet_con_trung", .15)]),
    ("chăm sóc cá nhân", 5, [("dau_goi", .6), ("sua_tam", .6), ("kem_danh_rang", .7), ("cham_soc_ca_nhan", .3), ("giay", .3)]),
    ("bánh mì pate", 2, [("thit_hop", .6), ("cu_qua:ca chua", .3), ("trung:ga", .4), ("tuong_ot", .35), ("pho_mai_bo", .3),
                         ("rau_thom", .3), ("xuc_xich", .3), ("cu_qua:dua leo", .3)]),
    ("miến / món chay", 2, [("mien", .9), ("nam_kho", .8), ("nuoc_tuong", .6), ("rau_la", .4), ("cu_qua", .4), ("dau_an", .3)]),
    ("cơm với cá hộp", 2, [("ca_hop", .9), ("gao", .5), ("rau_la", .5), ("tuong_ot", .25)]),
    ("phô mai, sữa", 2, [("pho_mai_bo", .8), (MILKS, .5), ("banh_quy", .3)]),
    ("nấu lẩu", 3, [("thit_bo", .6), ("hai_san", .5), ("rau_la", .8), ("nam_kho", .4), ("mien", .4), ("mi_goi", .3),
                    ("nuoc_ngot", .4), ("bia", .3), ("tuong_ot:sa te", .3), ("do_dong_lanh", .5), ("rau_thom", .4)]),
    ("nướng cuối tuần", 3, [("thit_heo", .6), ("thit_bo", .5), ("thit_ga_vit", .4), ("tieu_gia_vi", .6), ("bia", .5),
                            ("nuoc_ngot", .4), ("rau_la", .4), ("tuong_ot", .4), ("cu_qua", .3)]),
    ("gà rán", 2, [("thit_ga_vit", .9), ("bot:chien gion", .8), ("trung:ga", .5), ("dau_an", .8), ("tuong_ot", .5),
                   ("cu_qua:khoai tay", .4)]),
    ("làm bánh", 2, [("bot", .95), ("trung:ga", .8), ("duong", .7), ("pho_mai_bo", .6), (MILKS, .5), ("socola", .3),
                     ("hat_say", .3)]),
    ("mì Ý", 2, [("mi_y", .95), ("thit_bo:xay", .7), ("tuong_ot:sot ca", .7), ("pho_mai_bo", .5), ("cu_qua:hanh tay", .5)]),
    ("nấu canh rau", 4, [("rau_la", .7), ("cu_qua", .6), ("thit_heo", .4), ("hat_nem", .6), ("nuoc_mam", .3), ("muoi", .2)]),
    ("kho cá", 2, [("ca_tuoi", .9), ("nuoc_mam", .7), ("duong", .6), ("tieu_gia_vi", .5), ("rau_thom", .5), ("gao", .3)]),
    ("ăn dặm cho bé", 3, [("an_dam", .8), ("sua_bot_tre_em", .5), ("ta_bim", .6), ("do_dung_be", .3), ("trai_cay:chuoi", .3),
                          ("sua_chua", .3)]),
    ("đồ cho bé", 3, [("ta_bim", .8), ("sua_bot_tre_em", .6), ("an_dam", .4), ("do_dung_be", .4), ("giay:khan uot", .4)]),
    ("ăn kèm dưa muối", 1, [("do_ngam_chua", .9), ("thit_heo", .4), ("gao", .4), ("nuoc_mam", .3)]),
    ("uống trà trò chuyện", 2, [("tra", .8), ("banh_quy", .6), ("keo", .4), ("hat_say", .4), ("trai_cay", .3)]),
    ("quà biếu", 2, [("ruou", .6), ("socola", .5), ("hat_say", .6), ("banh_quy", .5), ("keo", .5), ("tra", .4), ("sua_hat", .3)]),
    ("đồ dùng trong nhà", 2, [("pin_den", .6), ("do_dung_bep", .6), ("tui_mang_boc", .5), ("giay", .3)]),
    ("đồ nhậu khô", 2, [("hai_san_kho", .8), ("bia", .7), ("hat_say", .5), ("banh_trang", .3), ("do_an_vat_khac", .4)]),
    ("ăn lành mạnh", 3, [("gao:lut", .5), ("trung:ga", .5), ("thit_ga_vit", .7), ("cu_qua", .8), ("rau_la", .7), ("trai_cay", .5),
                         ("sua_chua", .4), ("yen_mach", .4), ("dau_an:o liu", .3), ("sua_hat", .3)]),
    ("đồ đông lạnh tiện lợi", 3, [("do_dong_lanh", .8), ("xuc_xich", .5), ("kem", .3), ("mi_goi", .2), ("nuoc_ngot", .3)]),
    ("dọn dẹp bếp", 3, [("tui_mang_boc", .8), ("rua_chen", .5), ("giay", .5), ("do_dung_bep", .3), ("lau_san", .3)]),
    ("giải nhiệt", 2, [("kem", .8), ("nuoc_ngot", .4), ("trai_cay", .3), ("nuoc_dien_giai", .2)]),
    ("rượu bia, đồ nhắm", 1, [("ruou", .7), ("hat_say", .5), ("pho_mai_bo", .3), ("socola", .2)]),
    ("cháo gà", 2, [("gao", .7), ("thit_ga_vit", .8), ("rau_thom", .6), ("nuoc_mam", .5), ("hat_nem", .4), ("trung:ga", .3)]),
]


class Catalog:
    """Ứng viên cho từng "mục" (nhóm hàng, có thể lọc theo từ khóa tên) cùng độ phổ biến của từng SKU."""

    def __init__(self, seed=42):
        rng = random.Random(seed)
        self.by_kind = defaultdict(list)
        self.brand = {}
        self.name = {}
        self.pop = {}
        for p in PRODUCTS:
            sku, name, brand, unit = p[1], p[3], p[4], p[5]
            self.by_kind[KIND_OF[sku]].append(sku)
            self.brand[sku] = brand
            self.name[sku] = strip_accents(name)
            w = min(2.5, max(.35, math.exp(rng.gauss(0, .5))))
            if sku in BESTSELLERS:
                w *= 2.5
            if "thùng" in unit or "bình" in unit or "vỉ 30" in unit:
                w *= .3  # mua số lượng lớn ít gặp hơn
            self.pop[sku] = w
        self._cache = {}

    def candidates(self, spec):
        if spec in self._cache:
            return self._cache[spec]
        kind, _, kw = spec.partition(":")
        pool = self.by_kind[kind]
        if kw:
            tokens = strip_accents(kw).split()
            pool = [s for s in pool if all(t in self.name[s] for t in tokens)]
        if not pool:
            raise KeyError(f"mục '{spec}' không có sản phẩm nào")
        self._cache[spec] = pool
        return pool

    def pick(self, spec, rng, brands):
        """Chọn một SKU: theo độ phổ biến, ưu tiên (x4) thương hiệu đã có trong giỏ."""
        pool = self.candidates(spec)
        weights = [self.pop[s] * (4.0 if self.brand[s] in brands else 1.0) for s in pool]
        return rng.choices(pool, weights=weights)[0]


def make_baskets(n=30000, seed=42):
    rng = random.Random(seed)
    cat = Catalog(seed)
    kinds = sorted(cat.by_kind)
    for _, _, items in MISSIONS:  # kiểm tra mọi mục đều có sản phẩm
        for spec, _ in items:
            for s in (spec if isinstance(spec, tuple) else (spec,)):
                cat.candidates(s)
    weights = [m[1] for m in MISSIONS]
    baskets = []
    while len(baskets) < n:
        basket, brands = set(), set()
        for mission in rng.choices(MISSIONS, weights=weights, k=rng.choices([1, 2, 3], weights=[58, 32, 10])[0]):
            for spec, prob in mission[2]:
                if rng.random() < prob:
                    chosen = rng.choice(spec) if isinstance(spec, tuple) else spec
                    sku = cat.pick(chosen, rng, brands)
                    basket.add(sku)
                    brands.add(cat.brand[sku])
        for _ in range(rng.choices([0, 1, 2], weights=[40, 35, 25])[0]):  # món mua thêm ngoài nhiệm vụ
            if rng.random() < .6:
                basket.add(rng.choice(SKUS))  # chọn đều theo sản phẩm: hàng ít người mua vẫn có mặt trong dữ liệu
            else:
                basket.add(cat.pick(rng.choice(kinds), rng, brands))
        if len(basket) >= 2:
            baskets.append(sorted(basket))
    return baskets


if __name__ == "__main__":
    data = make_baskets()
    out = os.path.join(os.path.dirname(__file__), "data", "baskets.json")
    json.dump({"source": "synthetic", "seed": 42, "baskets": data}, open(out, "w"), ensure_ascii=False)
    sizes = [len(b) for b in data]
    seen = {s for b in data for s in b}
    print(f"{len(data)} giỏ hàng, trung bình {sum(sizes) / len(sizes):.1f} món/giỏ, "
          f"{len(seen)}/{len(SKUS)} SKU xuất hiện -> {out}")
