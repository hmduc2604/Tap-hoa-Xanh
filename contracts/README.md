# Hợp đồng dịch vụ (Service Contracts)

| File | Nội dung |
|---|---|
| `openapi/<service>.json` | Hợp đồng OpenAPI 3.0.3 đầy đủ của từng service, kể cả API nội bộ (`x-access: internal`) |
| `openapi/api-gateway.json` | Các endpoint riêng của tầng tích hợp (health, dashboard, registry, contracts, SOAP) |
| `wsdl/catalog.wsdl` | WSDL 1.1 của CatalogService (SOAP document/literal) |

Hợp đồng được **sinh từ code** (`common/contract.py`): summary từ docstring, quyền từ decorator, tham số từ route,
lớp dịch vụ (`x-service-layer`) từ cấu hình service. Khi đang chạy, mỗi service phục vụ hợp đồng tại `GET /contract`,
gateway công bố bản công khai tại `/api/contracts/<service>`.

```bash
python scripts/export_contracts.py          # sinh lại các file trong thư mục này
python scripts/export_contracts.py --check  # báo lỗi nếu code đã đổi mà hợp đồng chưa cập nhật
```

Mỗi thao tác có `x-access`: `public`, `authenticated`, `roles:admin,staff` hoặc `internal`.
