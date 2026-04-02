"""账户 API.

文档参考: https://binance-docs.github.io/apidocs/spot/en/#spot-account-trade
"""

from __future__ import annotations

from typing import Any

from .base import BaseAPI


class AccountAPI(BaseAPI):
    """账户信息相关接口 (需要签名)."""

    def info(self) -> dict:
        """获取账户信息 (余额等)."""
        return self._client.get("/api/v3/account", signed=True)

    def my_trades(self, symbol: str, *, limit: int = 500) -> list:
        """获取账户成交记录."""
        return self._client.get(
            "/api/v3/myTrades",
            params={"symbol": symbol, "limit": limit},
            signed=True,
        )
