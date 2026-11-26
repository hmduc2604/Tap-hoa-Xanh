"""Client mỏng gọi API mô hình ngôn ngữ bằng `requests`, không cần SDK. Hỗ trợ hai nhà cung cấp:

    gemini     Google Gemini (generativelanguage.googleapis.com, :generateContent)
    anthropic  Anthropic Messages API

Phần còn lại của service (app.py) chỉ làm việc với MỘT định dạng thống nhất, là định dạng của Anthropic Messages
(khối `text` / `tool_use` / `tool_result`, `stop_reason`, `usage.input_tokens`...). Với Gemini, lớp này tự dịch
yêu cầu sang `generateContent` và dịch phản hồi ngược lại, nên đổi nhà cung cấp không phải sửa chỗ khác.

Cấu hình qua biến môi trường:
    AI_API_KEY       khóa API (hoặc ANTHROPIC_API_KEY / GEMINI_API_KEY). Để trống = tắt AI, service dùng phương án dự phòng
    AI_PROVIDER      gemini | anthropic. Bỏ trống = tự nhận theo tên model, địa chỉ API hoặc dạng khóa
    AI_MODEL         tên model. Mặc định: gemini-3-flash-preview (Gemini) hoặc claude-haiku-5-5 (Anthropic)
    AI_FALLBACK_MODELS  model dự phòng, cách nhau dấu phẩy, thử lần lượt khi model chính báo bận/không có.
                     Mặc định với Gemini: gemini-3.1-flash-lite
    AI_API_URL       địa chỉ API; có thể chứa {model}. Mặc định theo nhà cung cấp (đổi được để trỏ vào bản giả khi test)
    AI_TIMEOUT_SECONDS  thời gian chờ mỗi lượt gọi (mặc định 20)
    AI_THINKING      mức "suy nghĩ" của Gemini 3 (minimal|low|medium|high), mặc định low; off = không gửi
"""
import logging
import time
import uuid

import requests

from common.config import env, env_int
from common.errors import ApiError

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_FALLBACKS = "gemini-3.1-flash-lite"
ANTHROPIC_MODEL = "claude-haiku-5-5"
RETRY_STATUS = {429, 500, 502, 503, 504}      # lỗi tạm thời: thử lại / chuyển model dự phòng
SKIP_MODEL_STATUS = {400, 404}                # model không tồn tại hoặc không hỗ trợ tham số: chuyển model khác
# Gemini chỉ nhận một phần của JSON Schema; các khóa khác bị loại khi dịch công cụ
SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable"}


def detect_provider(explicit, model, url, key):
    explicit = (explicit or "").strip().lower()
    if explicit in ("gemini", "anthropic"):
        return explicit
    if "generativelanguage" in (url or "") or "gemini" in (model or "").lower() or (key or "").startswith(("AIza", "AQ.")):
        return "gemini"
    return "anthropic"


class AIClient:
    def __init__(self):
        self.api_key = env("AI_API_KEY") or env("GEMINI_API_KEY") or env("ANTHROPIC_API_KEY") or ""
        url, model = env("AI_API_URL"), env("AI_MODEL")
        self.provider = detect_provider(env("AI_PROVIDER"), model, url, self.api_key)
        gemini = self.provider == "gemini"
        self.model = model or (GEMINI_MODEL if gemini else ANTHROPIC_MODEL)
        self.url = url or (GEMINI_URL if gemini else ANTHROPIC_URL)
        default_fallbacks = GEMINI_FALLBACKS if gemini else ""
        self.fallbacks = [m.strip() for m in (env("AI_FALLBACK_MODELS", default_fallbacks) or "").split(",")
                          if m.strip() and m.strip() != self.model]
        self.timeout = env_int("AI_TIMEOUT_SECONDS", 20)
        thinking = (env("AI_THINKING", "low") or "").strip().lower()
        self.thinking = None if thinking in ("off", "none", "0", "false") else thinking
        self._no_thinking = set()   # model đã từ chối tham số thinkingLevel: không gửi lại ở các lần sau

    @property
    def enabled(self):
        return bool(self.api_key)

    # ------------------------------------------------------------------ giao diện chung
    def messages(self, system, messages, tools=None, max_tokens=700, timeout=None):
        """Gọi một lượt hội thoại. Trả về phản hồi theo định dạng Anthropic Messages (kèm `model` đã thực sự trả lời);
        ném ApiError(503) nếu AI không dùng được. Với lỗi tạm thời sẽ thử lại một lần rồi chuyển sang model dự phòng."""
        if not self.enabled:
            raise ApiError(503, "Tính năng AI chưa được cấu hình", code="AI_DISABLED")
        per_call = timeout or self.timeout
        budget_end = time.time() + per_call + 10   # tổng thời gian cho cả việc thử lại, không kéo dài vô hạn
        last_status = None
        for model in [self.model] + self.fallbacks:
            for attempt in range(2):
                left = budget_end - time.time()
                if left < 2:
                    break
                status, data = self._once(model, system, messages, tools, max_tokens, max(2, min(per_call, left)))
                if status == 200:
                    data["model"] = data.get("model") or model
                    return data
                last_status = status
                if status in (401, 403):   # sai khóa/không có quyền: đổi model cũng vô ích
                    log.warning("API AI từ chối khóa (HTTP %s)", status)
                    raise ApiError(503, "Trợ lý AI đang bận, vui lòng thử lại sau", code="AI_UNAVAILABLE",
                                   details={"upstream_status": status})
                if status in RETRY_STATUS and attempt == 0:
                    time.sleep(0.7)
                    continue
                break  # hết lượt thử cho model này (hoặc model không dùng được): sang model dự phòng
        raise ApiError(503, "Trợ lý AI đang bận, vui lòng thử lại sau", code="AI_UNAVAILABLE",
                       details={"upstream_status": last_status})

    def _once(self, model, system, messages, tools, max_tokens, timeout):
        """Một lần gọi HTTP. Trả về (mã trạng thái, json); mã 0 = lỗi mạng/hết giờ, mã -1 = phản hồi không đọc được.
        Không bao giờ ghi khóa hoặc nội dung phản hồi vào log, chỉ ghi mã trạng thái."""
        gemini = self.provider == "gemini"
        if gemini:
            payload = to_gemini_request(system, messages, tools, max_tokens, None if model in self._no_thinking else self.thinking)
            headers = {"x-goog-api-key": self.api_key, "content-type": "application/json"}
        else:
            payload = {"model": model, "max_tokens": max_tokens, "system": system, "messages": strip_private(messages)}
            if tools:
                payload["tools"] = tools
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        url = self.url.replace("{model}", model)
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=(3, timeout))
        except requests.RequestException as exc:
            log.warning("Gọi API AI (%s) thất bại: %s", model, exc.__class__.__name__)
            return 0, {}
        if resp.status_code == 400 and gemini and "thinkingConfig" in payload.get("generationConfig", {}):
            # model này không nhận mức suy nghĩ đã chọn: thử lại không kèm tham số đó
            payload["generationConfig"].pop("thinkingConfig", None)
            self._no_thinking.add(model)
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=(3, timeout))
            except requests.RequestException as exc:
                log.warning("Gọi API AI (%s) thất bại: %s", model, exc.__class__.__name__)
                return 0, {}
        if resp.status_code != 200:
            log.warning("API AI (%s) trả về HTTP %s", model, resp.status_code)
            return resp.status_code, {}
        try:
            data = resp.json()
        except ValueError:
            log.warning("API AI (%s) trả về dữ liệu không đọc được", model)
            return -1, {}
        return 200, (from_gemini_response(data, model) if gemini else data)


# ====================================================================== dịch qua lại định dạng Gemini
def strip_private(messages):
    """Bỏ các khóa nội bộ (bắt đầu bằng _) khỏi khối nội dung trước khi gửi cho Anthropic."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = [{k: v for k, v in b.items() if not k.startswith("_")} if isinstance(b, dict) else b for b in c]
        out.append({"role": m["role"], "content": c})
    return out


def clean_schema(schema):
    """JSON Schema của công cụ -> phần Gemini hiểu được."""
    if isinstance(schema, list):
        return [clean_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k == "properties" and isinstance(v, dict):
            out[k] = {name: clean_schema(sub) for name, sub in v.items()}
        elif k in SCHEMA_KEYS:
            out[k] = clean_schema(v)
    return out


def to_gemini_request(system, messages, tools, max_tokens, thinking):
    names = {}  # tool_use_id -> tên công cụ (Gemini cần tên khi gửi kết quả công cụ)
    for m in messages:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    names[b.get("id")] = b.get("name")
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        c = m.get("content")
        parts = []
        if isinstance(c, str):
            if c.strip():
                parts.append({"text": c})
        else:
            for b in c or []:
                kind = b.get("type")
                if kind == "text":
                    if b.get("_part"):
                        parts.append(b["_part"])
                    elif (b.get("text") or "").strip():
                        parts.append({"text": b["text"]})
                elif kind == "tool_use":
                    # giữ nguyên phần Gemini trả về (kèm thoughtSignature) để model nhớ mạch suy luận ở vòng sau
                    parts.append(b.get("_part") or {"functionCall": {"name": b.get("name"), "args": b.get("input") or {}}})
                elif kind == "tool_result":
                    out = b.get("content")
                    resp = {"error": out} if b.get("is_error") else {"result": out}
                    fr = {"name": names.get(b.get("tool_use_id")) or "search_products", "response": resp}
                    if b.get("tool_use_id") and not str(b["tool_use_id"]).startswith("gem_"):
                        fr["id"] = b["tool_use_id"]
                    parts.append({"functionResponse": fr})
        if parts:
            contents.append({"role": role, "parts": parts})
    gen = {"maxOutputTokens": int(max_tokens) + 1024}   # chừa chỗ cho token suy nghĩ, tránh bị cắt giữa câu
    if thinking:
        gen["thinkingConfig"] = {"thinkingLevel": thinking}
    payload = {"contents": contents, "generationConfig": gen}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        payload["tools"] = [{"functionDeclarations": [
            {"name": t["name"], "description": t.get("description", ""), "parameters": clean_schema(t.get("input_schema") or {"type": "object"})}
            for t in tools]}]
    return payload


def from_gemini_response(data, model):
    """Phản hồi generateContent -> định dạng Anthropic Messages (giữ phần gốc trong `_part`)."""
    cands = data.get("candidates") or []
    cand = cands[0] if cands else {}
    blocks, has_call = [], False
    for part in (cand.get("content") or {}).get("parts") or []:
        if part.get("thought"):
            continue
        if "functionCall" in part:
            fc = part["functionCall"]
            has_call = True
            blocks.append({"type": "tool_use", "id": fc.get("id") or f"gem_{uuid.uuid4().hex[:10]}", "name": fc.get("name"),
                           "input": fc.get("args") or {}, "_part": part})
        elif part.get("text"):
            blocks.append({"type": "text", "text": part["text"], "_part": part})
    finish = cand.get("finishReason")
    stop = "tool_use" if has_call else ("max_tokens" if finish == "MAX_TOKENS" else "end_turn")
    um = data.get("usageMetadata") or {}
    usage = {"input_tokens": int(um.get("promptTokenCount") or 0),
             "output_tokens": int(um.get("candidatesTokenCount") or 0) + int(um.get("thoughtsTokenCount") or 0)}
    return {"content": blocks, "stop_reason": stop, "usage": usage, "model": data.get("modelVersion") or model,
            "finish_reason": finish}


def text_of(response):
    """Ghép các khối văn bản trong phản hồi."""
    return "".join(b.get("text", "") for b in response.get("content", []) if b.get("type") == "text").strip()


def usage_of(response):
    u = response.get("usage") or {}
    return int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
