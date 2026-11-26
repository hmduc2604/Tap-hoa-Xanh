"""API AI giả (giống Anthropic Messages API) để kiểm thử ai-service mà không tốn tiền và không cần mạng.

    python tests/fake_llm.py            # nghe ở cổng 8999
Chạy hệ thống trỏ vào nó (định dạng Anthropic):
    AI_ENGINE=llm AI_API_KEY=test-key AI_API_URL=http://127.0.0.1:8999/v1/messages python run_local.py --reset
hoặc định dạng Gemini (model "-overloaded" luôn trả 503 để thử chuyển sang model dự phòng):
    AI_ENGINE=llm AI_PROVIDER=gemini AI_API_KEY=test-key AI_MODEL=gemini-overloaded AI_FALLBACK_MODELS=gemini-fake \\
        AI_API_URL=http://127.0.0.1:8999/v1beta/models/{model}:generateContent python run_local.py --reset
Sau đó chạy: python tests/ai_test.py

Hành vi có chủ đích (để kiểm tra ai-service phòng thủ đúng):
- chat: lượt 1 gọi công cụ search_products, lượt 2 trả lời và nhắc 1 id thật + 1 id bịa (phải bị loại)
- gợi ý: trả JSON bọc trong ```json, gồm id hợp lệ, chính sản phẩm đang xem và id bịa (phải bị loại)
- thực đơn: trả JSON có món lỗi, trường lạ (product_id, price: phải bị bỏ qua), số lượng rác và nguyên liệu cửa hàng không bán;
  yêu cầu chứa "zzzjunk" -> trả văn bản không phải JSON, "zzzempty" -> không có món nào (ai-service phải chuyển sang thực đơn cục bộ);
  khi lời nhắc báo "VƯỢT ngân sách" thì trả bản rẻ hơn (bỏ món kho)
"""
import json
import os
import re

from flask import Flask, jsonify, request

app = Flask(__name__)
FAIL = {"on": False}
STATS = {"calls": 0, "chat": 0, "recommend": 0, "meal": 0, "meal_retry": 0, "last_meal_prompt": "", "bad_key": 0, "last_system": "", "gemini": 0, "sig_replayed": 0, "overloaded": 0}
KEY = os.environ.get("FAKE_LLM_KEY", "test-key")


def meal_text(prompt):
    """Câu trả lời giả cho yêu cầu lập thực đơn (nhận biết qua dòng 'Yêu cầu của khách')."""
    STATS["meal"] += 1
    STATS["last_meal_prompt"] = prompt
    request_text = re.search(r'"""(.*?)"""', prompt, re.S).group(1).lower()
    if "zzzjunk" in request_text:
        return "Xin lỗi, mình không lập được thực đơn."
    if "zzzempty" in request_text:
        return json.dumps({"title": "Rỗng", "dishes": []})
    n = int(re.search(r"Số người ăn: (\d+)", prompt).group(1))
    cheap = "VƯỢT ngân sách" in prompt
    STATS["meal_retry"] += 1 if cheap else 0

    def ing(name, search, grams=None, pieces=None, pantry=False, **extra):
        return {"name": name, "search": search, "amount_g": grams, "pieces": pieces, "pantry": pantry, **extra}

    soup = {"name": "canh chua cá", "how": "Nấu nước me, thả cá và rau vào.", "ingredients": [
        ing("cá basa", "cá basa", 150 * n), ing("cà chua", "cà chua", 100 * n), ing("giá đỗ", "giá đỗ", 30 * n),
        ing("nấm tuyết xanh zzz", "nấm tuyết xanh zzz", 50), ing("nước mắm", "nước mắm", pantry=True)]}
    braised = {"name": "thịt kho trứng", "how": "Kho thịt với nước dừa.", "ingredients": [
        ing("thịt ba rọi", "thịt ba rọi", 150 * n, product_id=1, price=1),   # trường lạ: phải bị bỏ qua
        ing("trứng gà", "trứng gà", pieces=n),
        ing("rác", "muối", "abc", 99999),                                   # số lượng rác -> mua 1
        ing("nước mắm", "nước mắm", pantry=True), ing("đường", "đường", pantry=True)]}
    rice = {"name": "cơm trắng", "how": "Nấu cơm.", "ingredients": [ing("gạo", "gạo", 80 * n, pantry=True)]}
    broken = {"name": "món lỗi", "ingredients": "không phải danh sách"}
    dishes = [soup, rice] if cheap else [soup, braised, rice, broken]
    return "```json\n" + json.dumps({"title": "Bữa cơm thử nghiệm", "dishes": dishes}, ensure_ascii=False) + "\n```"


@app.get("/_stats")
def stats():
    return jsonify(STATS)


@app.post("/_fail")
def fail():
    """Bật/tắt chế độ giả lập API AI bị lỗi 500: {"on": true}"""
    FAIL["on"] = bool((request.get_json(silent=True) or {}).get("on"))
    return {"fail": FAIL["on"]}


@app.post("/_reset")
def reset():
    STATS.update(calls=0, chat=0, recommend=0, meal=0, meal_retry=0, bad_key=0, gemini=0, sig_replayed=0, overloaded=0)
    return {"ok": True}


@app.post("/v1/messages")
def messages():
    STATS["calls"] += 1
    if request.headers.get("x-api-key") != KEY or request.headers.get("anthropic-version") != "2023-06-01":
        STATS["bad_key"] += 1
        return jsonify({"type": "error", "error": {"type": "authentication_error"}}), 401
    if FAIL["on"]:
        return jsonify({"type": "error", "error": {"type": "api_error"}}), 500
    body = request.get_json()
    STATS["last_system"] = body.get("system", "")
    usage = {"input_tokens": 120, "output_tokens": 40}
    msgs = body["messages"]
    if body.get("tools"):  # ---- trợ lý chat
        STATS["chat"] += 1
        last = msgs[-1]
        if isinstance(last["content"], list) and last["content"][0].get("type") == "tool_result":
            try:
                found = json.loads(last["content"][0]["content"])
            except ValueError:
                found = []
            if not found:
                return jsonify({"stop_reason": "end_turn", "usage": usage,
                                "content": [{"type": "text", "text": "Cửa hàng chưa có món này."}]})
            first = found[0]
            text = f"Mình gợi ý {first['name']} [[{first['id']}]] giá {first['price']}đ, và món lạ [[99999]] nữa."
            return jsonify({"stop_reason": "end_turn", "usage": usage, "content": [{"type": "text", "text": text}]})
        question = last["content"].lower()
        if "bịa" in question and not question.startswith("(hệ thống)"):  # kể món chưa tra cứu -> ai-service phải bắt tra cứu lại
            return jsonify({"stop_reason": "end_turn", "usage": usage,
                            "content": [{"type": "text", "text": "Cửa hàng có các món:\n- Rau húng quế\n- Ngò gai"}]})
        query = "nuoc mam" if ("nước mắm" in question or "nuoc mam" in question) else ("zzzkhongco" if "zzz" in question else "gao")
        args = {"query": query, "limit": 3}
        if "rẻ nhất" in question:
            args = {"query": "mì", "sort": "price_asc", "limit": 3}
        return jsonify({"stop_reason": "tool_use", "usage": usage, "content": [
            {"type": "text", "text": "Để mình tra cứu."},
            {"type": "tool_use", "id": "toolu_fake_1", "name": "search_products", "input": args}]})
    if "Yêu cầu của khách" in str(msgs[-1]["content"]):  # ---- thực đơn
        return jsonify({"stop_reason": "end_turn", "usage": usage, "content": [{"type": "text", "text": meal_text(msgs[-1]["content"])}]})
    # ---- gợi ý mua kèm
    STATS["recommend"] += 1
    prompt = msgs[-1]["content"]
    viewing = int(re.search(r"\[(\d+)\]", prompt).group(1))
    ids = [int(m.group(1)) for m in re.finditer(r"^(\d+)\|", prompt, re.M)]
    picks = [{"id": i, "reason": "Hay dùng cùng nhau"} for i in ids[:3]]
    picks += [{"id": viewing, "reason": "chính nó"}, {"id": 99999, "reason": "id bịa"}]
    text = "Đây là gợi ý:\n```json\n" + json.dumps({"items": picks}, ensure_ascii=False) + "\n```"
    return jsonify({"stop_reason": "end_turn", "usage": usage, "content": [{"type": "text", "text": text}]})


@app.post("/v1beta/models/<model>:generateContent")
def gemini(model):
    """Giả lập Gemini generateContent: cùng hành vi như trên nhưng theo định dạng Gemini (functionCall có id + thoughtSignature)."""
    STATS["calls"] += 1
    STATS["gemini"] += 1
    if request.headers.get("x-goog-api-key") != KEY:
        STATS["bad_key"] += 1
        return jsonify({"error": {"code": 403, "status": "PERMISSION_DENIED"}}), 403
    if FAIL["on"]:
        return jsonify({"error": {"code": 500, "status": "INTERNAL"}}), 500
    if "overloaded" in model:  # model chính đang quá tải -> ai-service phải chuyển sang model dự phòng
        STATS["overloaded"] += 1
        return jsonify({"error": {"code": 503, "status": "UNAVAILABLE"}}), 503
    body = request.get_json()
    STATS["last_system"] = ((body.get("systemInstruction") or {}).get("parts") or [{}])[0].get("text", "")
    usage = {"promptTokenCount": 120, "candidatesTokenCount": 40, "thoughtsTokenCount": 10}

    def reply(parts, finish="STOP"):
        return jsonify({"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
                        "usageMetadata": usage, "modelVersion": model})

    contents = body["contents"]
    last = contents[-1]
    if body.get("tools"):  # ---- trợ lý chat
        STATS["chat"] += 1
        decl = body["tools"][0]["functionDeclarations"][0]
        assert decl["name"] == "search_products" and "additionalProperties" not in str(decl)
        resp = next((p["functionResponse"] for p in last["parts"] if "functionResponse" in p), None)
        if resp:
            # vòng 2: phải gửi lại đúng phần functionCall cũ (kèm thoughtSignature) và kết quả công cụ có tên
            if any(p.get("thoughtSignature") == "sig-fake" for c in contents if c["role"] == "model" for p in c["parts"]):
                STATS["sig_replayed"] += 1
            try:
                found = json.loads(resp["response"]["result"])
            except (ValueError, KeyError, TypeError):
                found = []
            if not found:
                return reply([{"text": "Cửa hàng chưa có món này."}])
            first = found[0]
            return reply([{"text": f"Mình gợi ý {first['name']} [[{first['id']}]] giá {first['price']}đ, và món lạ [[99999]] nữa."}])
        question = last["parts"][0]["text"].lower()
        if "bịa" in question and not question.startswith("(hệ thống)"):
            return reply([{"text": "Cửa hàng có các món:\n- Rau húng quế\n- Ngò gai"}])
        query = "nuoc mam" if ("nước mắm" in question or "nuoc mam" in question) else ("zzzkhongco" if "zzz" in question else "gao")
        args = {"query": query, "limit": 3}
        if "rẻ nhất" in question:
            args = {"query": "mì", "sort": "price_asc", "limit": 3}
        return reply([{"text": "Để mình tra cứu."},
                      {"functionCall": {"id": "call_fake_1", "name": "search_products", "args": args},
                       "thoughtSignature": "sig-fake"}])
    if "Yêu cầu của khách" in last["parts"][0].get("text", ""):  # ---- thực đơn
        return reply([{"text": meal_text(last["parts"][0]["text"])}])
    # ---- gợi ý mua kèm
    STATS["recommend"] += 1
    prompt = last["parts"][0]["text"]
    viewing = int(re.search(r"\[(\d+)\]", prompt).group(1))
    ids = [int(m.group(1)) for m in re.finditer(r"^(\d+)\|", prompt, re.M)]
    picks = [{"id": i, "reason": "Hay dùng cùng nhau"} for i in ids[:3]]
    picks += [{"id": viewing, "reason": "chính nó"}, {"id": 99999, "reason": "id bịa"}]
    return reply([{"text": "Đây là gợi ý:\n```json\n" + json.dumps({"items": picks}, ensure_ascii=False) + "\n```"}])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8999)))
