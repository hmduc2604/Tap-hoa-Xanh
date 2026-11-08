"""Chuẩn hóa lỗi API: mọi lỗi trả về dạng {"error": {"code", "message", "details"}}."""
import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status, message, code=None, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "UNPROCESSABLE",
            429: "TOO_MANY_REQUESTS",
            502: "BAD_GATEWAY",
            503: "SERVICE_UNAVAILABLE",
        }.get(status, "ERROR")
        self.details = details

    def to_dict(self):
        body = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def bad_request(message, details=None):
    return ApiError(400, message, details=details)


def not_found(message="Không tìm thấy dữ liệu"):
    return ApiError(404, message)


def forbidden(message="Bạn không có quyền thực hiện thao tác này"):
    return ApiError(403, message)


def conflict(message, details=None):
    return ApiError(409, message, details=details)


def register_error_handlers(app):
    from common.db import IntegrityError

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify(err.to_dict()), err.status

    @app.errorhandler(IntegrityError)
    def _integrity(err):
        log.warning("Integrity error: %s", err)
        return jsonify(ApiError(409, "Dữ liệu bị trùng hoặc vi phạm ràng buộc").to_dict()), 409

    @app.errorhandler(HTTPException)
    def _http(err):
        messages = {
            404: "Không tìm thấy đường dẫn",
            405: "Phương thức không được hỗ trợ",
            400: "Yêu cầu không hợp lệ",
        }
        api = ApiError(err.code or 500, messages.get(err.code, err.description or "Lỗi"))
        return jsonify(api.to_dict()), api.status

    @app.errorhandler(Exception)
    def _unhandled(err):
        log.exception("Unhandled error: %s", err)
        return jsonify(ApiError(500, "Lỗi hệ thống, vui lòng thử lại sau", code="INTERNAL_ERROR").to_dict()), 500
