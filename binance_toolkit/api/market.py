"""市场数据 API.

文档参考: https://binance-docs.github.io/apidocs/spot/en/#market-data-endpoints
"""

from __future__ import annotations

from typing import Any, Optional

from .base import BaseAPI


class MarketAPI(BaseAPI):
    """市场数据相关接口 (无需签名)."""

    # ---- 通用 / 连通性 ----

    def ping(self) -> dict:
        """测试 API 连通性."""
        return self._client.get("/api/v3/ping")

    def server_time(self) -> dict:
        """获取服务器时间."""
        return self._client.get("/api/v3/time")

    # ---- 交易所信息 ----

    def exchange_info(
        self,
        symbol: str | None = None,
        symbols: list[str] | None = None,
    ) -> dict:
        """获取交易所交易规则和交易对信息.

        Args:
            symbol:  单个交易对，如 "BNBBTC".
            symbols: 多个交易对，如 ["BTCUSDT", "ETHUSDT"].
        """
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        elif symbols:
            params["symbols"] = str(symbols)
        return self._client.get("/api/v3/exchangeInfo", params=params)

    # ---- K 线 ----

    def klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list:
        """获取 K 线 / 烛台数据.

        Args:
            symbol:     交易对, 如 "BTCUSDT".
            interval:   K 线间隔, 如 "1m", "1h", "1d".
            start_time: 起始时间 (毫秒时间戳).
            end_time:   结束时间 (毫秒时间戳).
            limit:      返回条数, 默认 500, 最大 1000.
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._client.get("/api/v3/klines", params=params)

    def ui_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list:
        """获取 UI 优化的 K 线数据."""
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._client.get("/api/v3/uiKlines", params=params)

    # ---- 价格 / Ticker ----

    def ticker_price(self, symbol: str | None = None) -> dict | list:
        """获取最新价格.

        Args:
            symbol: 交易对。省略则返回所有交易对价格。
        """
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._client.get("/api/v3/ticker/price", params=params)

    def ticker_book(self, symbol: str | None = None) -> dict | list:
        """获取最佳挂单价格 (买一/卖一)."""
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._client.get("/api/v3/ticker/bookTicker", params=params)

    def ticker_24hr(self, symbol: str | None = None) -> dict | list:
        """获取 24 小时价格变动统计."""
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._client.get("/api/v3/ticker/24hr", params=params)

    # ---- 深度 ----

    def depth(self, symbol: str, *, limit: int = 100) -> dict:
        """获取订单簿深度.

        Args:
            symbol: 交易对.
            limit:  深度条数 (5, 10, 20, 50, 100, 500, 1000, 5000).
        """
        return self._client.get(
            "/api/v3/depth",
            params={"symbol": symbol, "limit": limit},
        )

    # ---- 最近成交 ----

    def recent_trades(self, symbol: str, *, limit: int = 500) -> list:
        """获取最近成交记录."""
        return self._client.get(
            "/api/v3/trades",
            params={"symbol": symbol, "limit": limit},
        )

    def historical_trades(self, symbol: str, *, limit: int = 500, from_id: int | None = None) -> list:
        """获取历史成交记录 (需要 API Key，但不需要签名)."""
        params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        if from_id is not None:
            params["fromId"] = from_id
        return self._client.get("/api/v3/historicalTrades", params=params)

    def agg_trades(
        self,
        symbol: str,
        *,
        from_id: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list:
        """获取近期归集成交记录."""
        params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        if from_id is not None:
            params["fromId"] = from_id
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._client.get("/api/v3/aggTrades", params=params)

    # ---- 均价 ----

    def avg_price(self, symbol: str) -> dict:
        """获取当前平均价格."""
        return self._client.get("/api/v3/avgPrice", params={"symbol": symbol})
