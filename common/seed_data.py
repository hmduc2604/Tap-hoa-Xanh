"""Dữ liệu mẫu (chỉ dùng để khởi tạo demo).

Gồm 55 sản phẩm gốc ngay trong file này (BASE_PRODUCTS, id 1..55) và ~540 sản phẩm bổ sung sinh từ common/catalog/
(EXTRA_PRODUCTS, nối tiếp phía sau). product-service tạo danh mục + sản phẩm theo đúng thứ tự PRODUCTS; khi cơ sở dữ liệu
đã có dữ liệu cũ, các sản phẩm mới được bổ sung theo SKU mà không đụng tới dữ liệu đang có (xem seed() ở từng service).
inventory-service tạo tồn kho đầu kỳ cho các sản phẩm tương ứng.
"""
from common.catalog import EXTRA_CATEGORIES, all_blocks, build

BASE_CATEGORIES = [
    # (tên, icon, mô tả)
    ("Gạo & Ngũ cốc", "🍚", "Gạo các loại, nếp, yến mạch, ngũ cốc dinh dưỡng"),
    ("Mì, Bún & Đồ khô", "🍜", "Mì gói, phở, bún khô, miến, nấm khô"),
    ("Gia vị & Nước chấm", "🧂", "Nước mắm, nước tương, hạt nêm, đường, muối"),
    ("Dầu ăn & Đồ hộp", "🥫", "Dầu ăn, cá hộp, pate, thực phẩm đóng hộp"),
    ("Sữa & Chế phẩm sữa", "🥛", "Sữa tươi, sữa chua, sữa đặc, phô mai"),
    ("Đồ uống", "🥤", "Nước ngọt, nước suối, trà, cà phê, bia"),
    ("Bánh kẹo & Snack", "🍪", "Bánh quy, snack, kẹo, bánh gạo"),
    ("Rau củ & Trái cây", "🥬", "Rau xanh, củ quả, trái cây tươi mỗi ngày"),
    ("Thịt, Trứng & Hải sản", "🥚", "Thịt heo, gà, trứng, tôm cá tươi sống"),
    ("Hóa phẩm & Vệ sinh", "🧴", "Nước giặt, nước rửa chén, dầu gội, giấy"),
]

# (chỉ số danh mục, sku, barcode, tên, thương hiệu, đơn vị, giá, giá KM, tồn đầu, tồn tối thiểu, mô tả)
BASE_PRODUCTS = [
    (0, "GAO-ST25-5", "8930000000011", "Gạo ST25 Sóc Trăng túi 5kg", "ST25", "túi 5kg", 195000, 179000, 40, 10,
     "Gạo ST25 hạt dài, dẻo thơm, từng đạt giải gạo ngon nhất thế giới."),
    (0, "GAO-JAS-5", "8930000000028", "Gạo Jasmine thơm túi 5kg", "Vinh Hiển", "túi 5kg", 135000, None, 35, 10,
     "Gạo Jasmine cơm mềm, thơm nhẹ, phù hợp bữa cơm gia đình."),
    (0, "NEP-CAI-2", "8930000000035", "Gạo nếp cái hoa vàng 2kg", "Hải Hậu", "túi 2kg", 78000, None, 20, 5,
     "Nếp cái hoa vàng hạt tròn, dẻo, dùng nấu xôi, gói bánh."),
    (0, "YM-QUAKER-500", "8930000000042", "Yến mạch nguyên hạt 500g", "Quaker", "hộp 500g", 69000, 62000, 25, 5,
     "Yến mạch cán dẹt giàu chất xơ, tốt cho bữa sáng."),
    (0, "NC-VD-500", "8930000000059", "Bột ngũ cốc dinh dưỡng 500g", "Việt Đài", "túi 500g", 65000, None, 4, 8,
     "Ngũ cốc dinh dưỡng từ đậu nành, mè đen, gạo lứt."),

    (1, "MI-HH-THUNG", "8930000000066", "Mì Hảo Hảo tôm chua cay (thùng 30 gói)", "Acecook", "thùng 30 gói", 118000, 109000, 30, 8,
     "Thùng mì ăn liền vị tôm chua cay quen thuộc."),
    (1, "MI-HH-GOI", "8930000000073", "Mì Hảo Hảo tôm chua cay gói 75g", "Acecook", "gói 75g", 4500, None, 300, 50,
     "Mì ăn liền vị tôm chua cay."),
    (1, "PHO-VIFON", "8930000000080", "Phở bò ăn liền Vifon 65g", "Vifon", "gói 65g", 9000, None, 150, 30,
     "Phở bò ăn liền sợi mềm, nước dùng đậm đà."),
    (1, "BUN-KHO-500", "8930000000097", "Bún gạo khô 500g", "Safoco", "gói 500g", 22000, None, 60, 10,
     "Bún gạo khô sợi nhỏ, dễ chế biến."),
    (1, "MIEN-DONG-200", "8930000000103", "Miến dong 200g", "Cự Đà", "gói 200g", 25000, None, 45, 10,
     "Miến dong dai ngon, không chất bảo quản."),
    (1, "NAM-HUONG-100", "8930000000110", "Nấm hương khô 100g", "Đặc sản Sapa", "gói 100g", 45000, None, 18, 5,
     "Nấm hương rừng sấy khô, thơm đậm."),

    (2, "NM-NAMNGU-750", "8930000000127", "Nước mắm Nam Ngư 750ml", "Chinsu", "chai 750ml", 42000, 38000, 80, 15,
     "Nước mắm cá cơm, vị đậm đà."),
    (2, "NM-PQ-500", "8930000000134", "Nước mắm Phú Quốc 40 độ đạm 500ml", "Hưng Thịnh", "chai 500ml", 65000, None, 30, 8,
     "Nước mắm truyền thống Phú Quốc, độ đạm cao."),
    (2, "NT-MAGGI-700", "8930000000141", "Nước tương đậu nành Maggi 700ml", "Maggi", "chai 700ml", 32000, None, 50, 10,
     "Nước tương lên men tự nhiên."),
    (2, "HN-KNORR-400", "8930000000158", "Hạt nêm Knorr thịt thăn 400g", "Knorr", "gói 400g", 39000, 35000, 70, 15,
     "Hạt nêm từ thịt thăn, xương ống và tủy."),
    (2, "BN-AJI-400", "8930000000165", "Bột ngọt Ajinomoto 400g", "Ajinomoto", "gói 400g", 34000, None, 60, 10,
     "Bột ngọt (mì chính) tinh khiết."),
    (2, "DUONG-BH-1KG", "8930000000172", "Đường tinh luyện Biên Hòa 1kg", "Biên Hòa", "túi 1kg", 28000, None, 90, 20,
     "Đường tinh luyện trắng, tinh khiết."),
    (2, "MUOI-IOT-500", "8930000000189", "Muối i-ốt 500g", "Bạc Liêu", "gói 500g", 6000, None, 120, 20,
     "Muối tinh bổ sung i-ốt."),
    (2, "TUONG-OT-250", "8930000000196", "Tương ớt Chinsu 250g", "Chinsu", "chai 250g", 15000, None, 70, 15,
     "Tương ớt cay nồng, chấm món chiên."),

    (3, "DA-NEPTUNE-1L", "8930000000202", "Dầu ăn Neptune Light 1L", "Neptune", "chai 1L", 52000, 48000, 60, 12,
     "Dầu ăn cao cấp, tốt cho tim mạch."),
    (3, "DA-SIMPLY-1L", "8930000000219", "Dầu đậu nành Simply 1L", "Simply", "chai 1L", 59000, None, 40, 10,
     "Dầu đậu nành nguyên chất."),
    (3, "CA-HOP-3CG", "8930000000226", "Cá nục sốt cà 155g", "3 Cô Gái", "hộp 155g", 22000, None, 55, 10,
     "Cá hộp sốt cà chua tiện lợi."),
    (3, "PATE-HL-150", "8930000000233", "Pate gan Hạ Long 150g", "Hạ Long", "hộp 150g", 29000, None, 0, 10,
     "Pate gan heo truyền thống."),

    (4, "SUA-VNM-1L", "8930000000240", "Sữa tươi tiệt trùng Vinamilk có đường 1L", "Vinamilk", "hộp 1L", 35000, None, 70, 15,
     "Sữa tươi tiệt trùng 100%, bổ sung vitamin."),
    (4, "SUA-TH-LOC4", "8930000000257", "Sữa tươi TH true MILK lốc 4 hộp 180ml", "TH true MILK", "lốc 4 hộp", 36000, 33000, 90, 20,
     "Sữa tươi sạch nguyên chất."),
    (4, "SC-VNM-LOC4", "8930000000264", "Sữa chua Vinamilk lốc 4 hộp", "Vinamilk", "lốc 4 hộp", 28000, None, 6, 10,
     "Sữa chua ăn có đường, lên men tự nhiên."),
    (4, "SUA-DAC-OT", "8930000000271", "Sữa đặc Ông Thọ lon 380g", "Vinamilk", "lon 380g", 26000, None, 65, 10,
     "Sữa đặc có đường, pha cà phê, làm bánh."),
    (4, "PHOMAI-CBC", "8930000000288", "Phô mai Con Bò Cười 8 miếng", "Bel", "hộp 120g", 37000, None, 30, 8,
     "Phô mai mềm bổ sung canxi."),

    (5, "COCA-LON", "8930000000295", "Coca-Cola lon 320ml", "Coca-Cola", "lon 320ml", 10000, None, 240, 48,
     "Nước giải khát có ga."),
    (5, "COCA-THUNG", "8930000000301", "Coca-Cola thùng 24 lon 320ml", "Coca-Cola", "thùng 24 lon", 220000, 199000, 20, 5,
     "Thùng 24 lon tiết kiệm."),
    (5, "AQUA-500", "8930000000318", "Nước suối Aquafina 500ml", "Aquafina", "chai 500ml", 5000, None, 300, 48,
     "Nước uống tinh khiết."),
    (5, "TRA-0DO", "8930000000325", "Trà xanh Không Độ 455ml", "Tân Hiệp Phát", "chai 455ml", 10000, None, 150, 24,
     "Trà xanh chiết xuất từ lá trà tươi."),
    (5, "CF-G7-18", "8930000000332", "Cà phê hòa tan G7 3in1 hộp 18 gói", "Trung Nguyên", "hộp 18 gói", 56000, 52000, 45, 10,
     "Cà phê hòa tan đậm vị."),
    (5, "BIA-SG-LON", "8930000000349", "Bia Saigon Special lon 330ml", "Sabeco", "lon 330ml", 17000, None, 200, 48,
     "Bia lager. Không bán cho người dưới 18 tuổi."),

    (6, "CHOCOPIE-12", "8930000000356", "Bánh Chocopie Orion hộp 12 cái", "Orion", "hộp 396g", 55000, 49000, 40, 10,
     "Bánh xốp phủ socola nhân marshmallow."),
    (6, "LAYS-52", "8930000000363", "Snack khoai tây Lay's vị tự nhiên 52g", "Lay's", "gói 52g", 12000, None, 100, 20,
     "Snack khoai tây giòn rụm."),
    (6, "COSY-BO-300", "8930000000370", "Bánh quy bơ Cosy 300g", "Kinh Đô", "hộp 300g", 39000, None, 35, 8,
     "Bánh quy bơ thơm ngon."),
    (6, "KEO-ALPEN", "8930000000387", "Kẹo sữa Alpenliebe gói 120g", "Alpenliebe", "gói 120g", 22000, None, 50, 10,
     "Kẹo sữa caramel."),
    (6, "BANHGAO-ONE", "8930000000394", "Bánh gạo One One vị ngọt 150g", "Want Want", "gói 150g", 25000, None, 3, 10,
     "Bánh gạo nướng giòn."),

    (7, "RAU-MUONG", "8930000000400", "Rau muống bó 500g", "Nông trại Xanh", "bó 500g", 12000, None, 30, 10,
     "Rau muống tươi thu hoạch trong ngày."),
    (7, "CA-CHUA-1KG", "8930000000417", "Cà chua Đà Lạt 1kg", "Nông trại Xanh", "kg", 28000, None, 40, 10,
     "Cà chua chín đỏ, mọng nước."),
    (7, "KHOAI-TAY-1KG", "8930000000424", "Khoai tây Đà Lạt 1kg", "Nông trại Xanh", "kg", 32000, None, 35, 10,
     "Khoai tây ruột vàng, bở."),
    (7, "CHUOI-1KG", "8930000000431", "Chuối già Nam Mỹ 1kg", "Nông trại Xanh", "kg", 30000, 26000, 25, 8,
     "Chuối chín vàng tự nhiên."),
    (7, "TAO-ENVY-1KG", "8930000000448", "Táo Envy New Zealand 1kg", "Envy", "kg", 159000, 139000, 15, 5,
     "Táo nhập khẩu giòn ngọt."),
    (7, "CAM-SANH-1KG", "8930000000455", "Cam sành 1kg", "Vĩnh Long", "kg", 35000, None, 30, 8,
     "Cam sành mọng nước, nhiều vitamin C."),

    (8, "TRUNG-GA-10", "8930000000462", "Trứng gà ta hộp 10 quả", "Ba Huân", "hộp 10 quả", 38000, None, 60, 15,
     "Trứng gà sạch, đạt chuẩn VietGAP."),
    (8, "BA-ROI-500", "8930000000479", "Thịt ba rọi heo 500g", "Meat Deli", "khay 500g", 85000, None, 20, 6,
     "Thịt heo tươi mát, đóng khay hút chân không."),
    (8, "UC-GA-500", "8930000000486", "Ức gà phi lê 500g", "CP", "khay 500g", 55000, 49000, 25, 6,
     "Ức gà phi lê giàu đạm, ít béo."),
    (8, "TOM-THE-500", "8930000000493", "Tôm thẻ tươi 500g", "Hải sản Biển Đông", "khay 500g", 120000, None, 12, 5,
     "Tôm thẻ tươi size 40-50 con/kg."),
    (8, "CA-BASA-500", "8930000000509", "Cá basa phi lê 500g", "Hải sản Biển Đông", "khay 500g", 49000, None, 18, 5,
     "Cá basa phi lê không xương."),

    (9, "OMO-36", "8930000000516", "Nước giặt OMO Matic cửa trên 3.6kg", "OMO", "túi 3.6kg", 189000, 169000, 25, 6,
     "Nước giặt cho máy giặt cửa trên, sạch bẩn vượt trội."),
    (9, "SUNLIGHT-750", "8930000000523", "Nước rửa chén Sunlight chanh 750g", "Sunlight", "chai 750g", 32000, None, 55, 10,
     "Nước rửa chén hương chanh, sạch bóng dầu mỡ."),
    (9, "CLEAR-630", "8930000000530", "Dầu gội Clear mát lạnh 630g", "Clear", "chai 630g", 165000, None, 20, 5,
     "Dầu gội sạch gàu, mát lạnh."),
    (9, "PS-230", "8930000000547", "Kem đánh răng P/S bảo vệ 123 230g", "P/S", "tuýp 230g", 35000, None, 45, 10,
     "Kem đánh răng ngừa sâu răng."),
    (9, "GIAY-VS-10", "8930000000554", "Giấy vệ sinh 3 lớp lốc 10 cuộn", "Pulppy", "lốc 10 cuộn", 75000, None, 30, 8,
     "Giấy vệ sinh mềm mịn, không bụi giấy."),
]


# nhóm hàng của 55 sản phẩm gốc (nhóm của sản phẩm bổ sung nằm trong common/catalog/)
_BASE_KIND = {
    "GAO-ST25-5": "gao", "GAO-JAS-5": "gao", "NEP-CAI-2": "gao_nep", "YM-QUAKER-500": "yen_mach", "NC-VD-500": "ngu_coc",
    "MI-HH-THUNG": "mi_goi", "MI-HH-GOI": "mi_goi", "PHO-VIFON": "pho_an_lien", "BUN-KHO-500": "bun_pho_kho",
    "MIEN-DONG-200": "mien", "NAM-HUONG-100": "nam_kho", "NM-NAMNGU-750": "nuoc_mam", "NM-PQ-500": "nuoc_mam",
    "NT-MAGGI-700": "nuoc_tuong", "HN-KNORR-400": "hat_nem", "BN-AJI-400": "hat_nem", "DUONG-BH-1KG": "duong",
    "MUOI-IOT-500": "muoi", "TUONG-OT-250": "tuong_ot", "DA-NEPTUNE-1L": "dau_an", "DA-SIMPLY-1L": "dau_an",
    "CA-HOP-3CG": "ca_hop", "PATE-HL-150": "thit_hop", "SUA-VNM-1L": "sua_tuoi", "SUA-TH-LOC4": "sua_tuoi",
    "SC-VNM-LOC4": "sua_chua", "SUA-DAC-OT": "sua_dac", "PHOMAI-CBC": "pho_mai_bo", "COCA-LON": "nuoc_ngot",
    "COCA-THUNG": "nuoc_ngot", "AQUA-500": "nuoc_suoi", "TRA-0DO": "tra", "CF-G7-18": "ca_phe", "BIA-SG-LON": "bia",
    "CHOCOPIE-12": "banh_ngot", "LAYS-52": "snack", "COSY-BO-300": "banh_quy", "KEO-ALPEN": "keo", "BANHGAO-ONE": "banh_gao",
    "RAU-MUONG": "rau_la", "CA-CHUA-1KG": "cu_qua", "KHOAI-TAY-1KG": "cu_qua", "CHUOI-1KG": "trai_cay",
    "TAO-ENVY-1KG": "trai_cay", "CAM-SANH-1KG": "trai_cay", "TRUNG-GA-10": "trung", "BA-ROI-500": "thit_heo",
    "UC-GA-500": "thit_ga_vit", "TOM-THE-500": "hai_san", "CA-BASA-500": "ca_tuoi", "OMO-36": "giat_giu",
    "SUNLIGHT-750": "rua_chen", "CLEAR-630": "dau_goi", "PS-230": "kem_danh_rang", "GIAY-VS-10": "giay",
}

EXTRA_PRODUCTS, _EXTRA_KIND, KINDS = build(all_blocks(), first_category_index=len(BASE_CATEGORIES), start_seq=0)

CATEGORIES = BASE_CATEGORIES + EXTRA_CATEGORIES
PRODUCTS = BASE_PRODUCTS + EXTRA_PRODUCTS
KIND_OF = {**_BASE_KIND, **_EXTRA_KIND}

assert len({p[1] for p in PRODUCTS}) == len(PRODUCTS), "SKU bị trùng"
assert len({p[2] for p in PRODUCTS}) == len(PRODUCTS), "mã vạch bị trùng"
assert len({p[3] for p in PRODUCTS}) == len(PRODUCTS), "tên sản phẩm bị trùng"
assert set(KIND_OF) == {p[1] for p in PRODUCTS}, "thiếu nhóm hàng cho sản phẩm"
