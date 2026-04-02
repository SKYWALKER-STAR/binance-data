"""异常定义模块."""

from __future__ import annotations

from typing import Any, Optional


class BinanceAPIError(Exception):
    """Binance API 通用错误."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[int] = None,
        response: Optional[dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.error_code = error_code
        self.response = response or {}
        super().__init__(message)


class BinanceRequestError(BinanceAPIError):
    """HTTP 请求级别错误 (网络/超时等)."""


class BinanceAuthError(BinanceAPIError):
    """鉴权相关错误 (签名失败、API Key 无效等)."""


class BinanceConfigError(Exception):
    """配置错误."""
