"""Tiện ích chung: thời gian, chuỗi tiếng Việt, phân trang, kiểm tra dữ liệu vào."""
import math
import random
import re
import string
import unicodedata
from datetime import datetime, timedelta, timezone

from flask import request

from common.config import TZ_OFFSET_HOURS
from common.errors import ApiError

APP_TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))


# ---------------------------------------------------------------- thời gian
def now():
    return datetime.now(APP_TZ).replace(tzinfo=None, microsecond=0)


def now_str():
    """Thời gian hiện tại theo giờ Việt Nam, dạng 'YYYY-MM-DD HH:MM:SS'."""
    return now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return now().strftime("%Y-%m-%d")


def normalize_datetime(value, end_of_day=False):
    """Chuẩn hóa '2026-11-06', '2026-11-06T10:30' ... về 'YYYY-MM-DD HH:MM:SS'."""
    if value in (None, ""):
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    try:
        day = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        raise ApiError(400, f"Ngày giờ không hợp lệ: {value}")
    return day.strftime("%Y-%m-%d") + (" 23:59:59" if end_of_day else " 00:00:00")


# ---------------------------------------------------------------- chuỗi
def strip_accents(text):
    """'Gạo ST25 Đặc biệt' -> 'gao st25 dac biet' (dùng cho tìm kiếm không dấu)."""
    if not text:
        return ""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", strip_accents(text)).strip("-") or "item"


def random_code(prefix, length=5):
    suffix = "".join(random.choices(string.digits, k=length))
    return f"{prefix}{now().strftime('%y%m%d')}{suffix}"


# ---------------------------------------------------------------- request
def get_json(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError(400, "Body phải là JSON hợp lệ")
        return {}
    if not isinstance(data, dict):
        raise ApiError(400, "Body JSON phải là một object")
    return data


def require_fields(data, fields):
    missing = [f for f in fields if data.get(f) in (None, "") or (isinstance(data.get(f), str) and not data.get(f).strip())]
    if missing:
        raise ApiError(400, "Thiếu thông tin bắt buộc: " + ", ".join(missing), details={"missing": missing})


def to_int(value, name, minimum=None, maximum=None, default=None, required=False):
    if value in (None, ""):
        if required:
            raise ApiError(400, f"Thiếu trường '{name}'")
        return default
    if isinstance(value, bool):
        raise ApiError(400, f"Trường '{name}' phải là số nguyên")
    try:
        number = int(value)
        if isinstance(value, float) and value != number:
            raise ValueError
    except (TypeError, ValueError):
        raise ApiError(400, f"Trường '{name}' phải là số nguyên")
    if minimum is not None and number < minimum:
        raise ApiError(400, f"Trường '{name}' phải >= {minimum}")
    if maximum is not None and number > maximum:
        raise ApiError(400, f"Trường '{name}' phải <= {maximum}")
    return number


def clean_str(value, max_len=500):
    if value is None:
        return None
    text = str(value).strip()
    return text[:max_len] if text else None


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def pagination(default_size=20, max_size=100):
    page = to_int(request.args.get("page"), "page", minimum=1, default=1)
    size = to_int(request.args.get("page_size"), "page_size", minimum=1, maximum=max_size, default=default_size)
    return page, size, (page - 1) * size


def paged(items, total, page, size):
    return {
        "items": items,
        "page": page,
        "page_size": size,
        "total": total,
        "total_pages": max(1, math.ceil(total / size)) if size else 1,
    }


def id_list(value):
    """'1,2,3' hoặc [1,2,3] -> [1, 2, 3] (bỏ trùng, giữ thứ tự)."""
    if value in (None, ""):
        return []
    raw = value if isinstance(value, (list, tuple)) else str(value).split(",")
    result = []
    for item in raw:
        number = to_int(item, "ids", minimum=1)
        if number not in result:
            result.append(number)
    return result
