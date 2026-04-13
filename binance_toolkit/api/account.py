"""账户 API.

文档参考: https://binance-docs.github.io/apidocs/spot/en/#spot-account-trade
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from .base import BaseAPI

AccountSnapshotType = Literal["SPOT", "MARGIN", "FUTURES"]


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

    def daily_snapshot(
        self,
        account_type: AccountSnapshotType,
        *,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 7,
    ) -> dict[str, Any]:
        """获取账户每日资产快照.

        文档: https://developers.binance.com/docs/wallet/account/daily-account-snapshoot

        约束:
            - 查询时间跨度不超过 30 天
            - 仅支持查询最近一个月数据
            - 未指定时间范围时默认返回最近 7 天
            - limit 范围 7 ~ 30

        Args:
            account_type: 账户类型，"SPOT"、"MARGIN" 或 "FUTURES"。
            start_time:   查询起始时间（毫秒时间戳），可选。
            end_time:     查询结束时间（毫秒时间戳），可选。
            limit:        返回条数，范围 7 ~ 30，默认 7。

        Returns:
            dict，含 code (200=成功)、msg、snapshotVos 三个顶级字段。
        """
        if account_type not in ("SPOT", "MARGIN", "FUTURES"):
            raise ValueError(
                f"account_type 必须为 SPOT / MARGIN / FUTURES，收到: {account_type!r}"
            )
        if not (7 <= limit <= 30):
            raise ValueError(f"limit 必须在 7 ~ 30 之间，收到: {limit}")

        params: dict[str, Any] = {"type": account_type, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        return self._client.get("/sapi/v1/accountSnapshot", params=params, signed=True)
