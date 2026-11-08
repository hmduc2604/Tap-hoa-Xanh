"""Hợp đồng dịch vụ (Service Contract) dạng OpenAPI 3.0.

Hợp đồng được sinh trực tiếp từ route của Flask app nên luôn khớp với code:
- summary / description lấy từ docstring của hàm xử lý
- quyền truy cập lấy từ decorator (@require_auth, @require_roles, @internal_only)
- tham số đường dẫn lấy từ khai báo route (<int:id> -> integer)
Mỗi service phục vụ hợp đồng tại GET /contract; gateway công bố bản công khai
(bỏ API nội bộ) tại GET /api/contracts/<service>.
"""
import inspect
import re

PARAM_RE = re.compile(r"<(?:(\w+):)?(\w+)>")
PARAM_TYPES = {"int": "integer", "float": "number"}
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "example": "OUT_OF_STOCK"},
                "message": {"type": "string", "example": "Không đủ hàng: Pate gan Hạ Long 150g (còn 0)"},
                "details": {},
            },
            "required": ["code", "message"],
        }
    },
}


def _path(rule):
    params = []

    def repl(m):
        params.append((m.group(2), PARAM_TYPES.get(m.group(1) or "", "string")))
        return "{" + m.group(2) + "}"

    return PARAM_RE.sub(repl, rule), params


def _tag(path):
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "operations"
    if parts[0] == "internal":
        return "internal"
    if parts[0] == "api" and len(parts) > 1:
        return parts[1]
    return parts[0] if parts[0] not in ("health", "contract") else "operations"


def build_openapi(app, service, version="1.0.0", layer="entity", description="", include_internal=True):
    paths, tags = {}, set()
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint == "static" or rule.rule in ("/internal/events",):
            continue
        internal = rule.rule.startswith("/internal") or rule.rule.startswith("/registry")
        if internal and not include_internal:
            continue
        if not include_internal and rule.rule in ("/health", "/contract"):
            continue
        view = app.view_functions[rule.endpoint]
        doc = inspect.getdoc(view) or ""
        summary, _, detail = doc.partition("\n")
        path, params = _path(rule.rule)
        tag = _tag(rule.rule)
        tags.add(tag)
        auth = getattr(view, "_auth", None)
        for method in [m for m in METHODS if m in rule.methods]:
            op = {
                "operationId": rule.endpoint if len(rule.methods - {"HEAD", "OPTIONS"}) == 1 else f"{rule.endpoint}_{method.lower()}",
                "summary": summary.strip() or rule.endpoint.replace("_", " "),
                "tags": [tag],
                "responses": {"200": {"description": "Thành công", "content": {"application/json": {"schema": {"type": "object"}}}}},
            }
            if detail.strip():
                op["description"] = detail.strip()
            if params:
                op["parameters"] = [{"name": n, "in": "path", "required": True, "schema": {"type": t}} for n, t in params]
            if method in ("POST", "PUT", "PATCH"):
                op["requestBody"] = {"required": False, "content": {"application/json": {"schema": {"type": "object"}}}}
                if method == "POST":
                    op["responses"]["201"] = {"description": "Tạo thành công", "content": {"application/json": {"schema": {"type": "object"}}}}
            op["responses"]["4XX"] = {"$ref": "#/components/responses/ClientError"}
            if auth and auth["type"] == "internal":
                op["security"] = [{"internalToken": []}]
                op["x-access"] = "internal"
            elif auth and auth["type"] == "roles":
                op["security"] = [{"bearerAuth": []}]
                op["x-access"] = "roles:" + ",".join(auth["roles"])
                op["description"] = (op.get("description", "") + f"\n\nVai trò được phép: {', '.join(auth['roles'])}").strip()
            elif auth and auth["type"] == "user":
                op["security"] = [{"bearerAuth": []}]
                op["x-access"] = "authenticated"
            else:
                op["security"] = []
                op["x-access"] = "public"
            paths.setdefault(path, {})[method.lower()] = op
    return {
        "openapi": "3.0.3",
        "info": {
            "title": f"{service} — hợp đồng dịch vụ",
            "version": version,
            "description": description,
            "x-service-name": service,
            "x-service-layer": layer,
        },
        "servers": [{"url": "/"}],
        "tags": [{"name": t} for t in sorted(tags)],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                               "description": "JWT do auth-service phát hành, kiểm tra tại API Gateway"},
                "internalToken": {"type": "apiKey", "in": "header", "name": "X-Internal-Token",
                                  "description": "Khóa nội bộ cho lời gọi service-to-service"},
            },
            "schemas": {"Error": ERROR_SCHEMA},
            "responses": {"ClientError": {"description": "Lỗi phía client (400, 401, 403, 404, 409...)",
                                          "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}},
        },
    }
