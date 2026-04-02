"""现货交易 API.

文档参考: https://binance-docs.github.io/apidocs/spot/en/#spot-account-trade
"""

from __future__ import annotations

from typing import Any

from .base import BaseAPI


class TradeAPI(BaseAPI):
    """现货交易相关接口 (需要签名)."""

    def new_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        *,
        time_in_force: str | None = None,
        quantity: str | None = None,
        quote_order_qty: str | None = None,
        price: str | None = None,
        stop_price: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """下单.

        Args:
            symbol:          交易对, 如 "BTCUSDT".
            side:            方向, "BUY" 或 "SELL".
            order_type:      订单类型, "LIMIT", "MARKET" 等.
            time_in_force:   有效方式, "GTC", "IOC", "FOK".
            quantity:        数量.
            quote_order_qty: 报价资产数量 (市价单使用).
            price:           价格 (限价单使用).
            stop_price:      止损价.
            **kwargs:        其他可选参数.
        """
        data: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        if time_in_force:
            data["timeInForce"] = time_in_force
        if quantity:
            data["quantity"] = quantity
        if quote_order_qty:
            data["quoteOrderQty"] = quote_order_qty
        if price:
            data["price"] = price
        if stop_price:
            data["stopPrice"] = stop_price
        data.update(kwargs)
        return self._client.post("/api/v3/order", data=data, signed=True)

    def new_order_test(self, **kwargs: Any) -> dict:
        """测试下单 (不会真正下单)."""
        data = dict(kwargs)
        return self._client.post("/api/v3/order/test", data=data, signed=True)

    def get_order(self, symbol: str, *, order_id: int | None = None, orig_client_order_id: str | None = None) -> dict:
        """查询订单."""
        params: dict[str, Any] = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        return self._client.get("/api/v3/order", params=params, signed=True)

    def cancel_order(self, symbol: str, *, order_id: int | None = None, orig_client_order_id: str | None = None) -> dict:
        """撤销订单."""
        params: dict[str, Any] = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        return self._client.delete("/api/v3/order", params=params, signed=True)

    def open_orders(self, symbol: str | None = None) -> list:
        """查看当前全部挂单."""
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._client.get("/api/v3/openOrders", params=params, signed=True)

    def all_orders(self, symbol: str, *, limit: int = 500) -> list:
        """查询所有订单 (含历史)."""
        return self._client.get(
            "/api/v3/allOrders",
            params={"symbol": symbol, "limit": limit},
            signed=True,
        )
