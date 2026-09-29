"""业务异常与错误码 — 对照 sdk-contract.md 第九节"""
from __future__ import annotations


class NiuDunError(Exception):
    """业务异常（code != 0 或响应验签失败时抛出）

    :ivar code: 平台业务状态码，见 ErrorCode
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"


class ErrorCode:
    """对接高频错误码（对照契约第九节）"""

    SUCCESS = 0
    FAIL = 1
    AUTH_FAIL = 10401
    NONCE_MISSING = 10408
    NONCE_INVALID = 10409
    TIMESTAMP_EXPIRED = 10410
    PARAM_PARSE_ERROR = 10505
    PARAM_VALIDATION_ERROR = 10506
    TRADE_NOT_EXIST = 20041
    TRADE_CLOSED = 20042
    TRADE_PROCESSING = 20043
    TRADE_STATUS_ERROR = 20044
    SIGN_VERIFY_FAILED = 20052
    SYSTEM_UNKNOWN = 30000
