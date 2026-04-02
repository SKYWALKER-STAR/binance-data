"""API 模块基类."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import BinanceClient


class BaseAPI:
    """所有 API 模块的基类.

    每个业务模块（market、trade、account …）继承此类，
    通过 self._client 访问底层 HTTP 客户端。
    """

    def __init__(self, client: "BinanceClient"):
        self._client = client
