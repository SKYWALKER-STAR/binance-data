"""币本位永续合约市场数据 API (DAPI).

文档参考:
  - Index Price and Mark Price: https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Index-Price-and-Mark-Price
  - Basis: https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Basis
"""

from __future__ import annotations

from typing import Any

from .base import BaseAPI


class CoinFuturesMarketAPI(BaseAPI):
    """币本位永续合约市场数据接口 (无需签名).

    所有请求发往 dapi.binance.com，与现货 API (api.binance.com) 相互独立。
    """

    # ---- 标记价格 / 指数价格 ----

    def premium_index(
        self,
        symbol: str | None = None,
        pair: str | None = None,
    ) -> list[dict] | dict:
        """查询币本位合约的标记价格和指数价格.

        GET /dapi/v1/premiumIndex  (权重: 10)

        Args:
            symbol: 合约交易对，如 "BTCUSD_PERP"。省略则返回全部。
            pair:   基础交易对，如 "BTCUSD"。省略则返回全部。

        Returns:
            单个合约时返回 dict，省略参数时返回 list[dict]。
            每条记录包含:
              - symbol             合约交易对名称
              - pair               基础交易对
              - markPrice          标记价格
              - indexPrice         指数价格
              - estimatedSettlePrice  预估结算价格 (仅在结算前最后一小时有效)
              - lastFundingRate    最近一次资金费率 (仅永续合约; 交割合约为 "")
              - interestRate       基础资产利率 (仅永续合约; 交割合约为 "")
              - nextFundingTime    下次资金费时间戳毫秒 (仅永续合约; 交割合约为 0)
              - time               数据时间戳毫秒
        """
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if pair:
            params["pair"] = pair
        return self._client.get("/dapi/v1/premiumIndex", params=params)

    # ---- 基差数据 ----

    def basis(
        self,
        pair: str,
        contract_type: str,
        period: str,
        *,
        limit: int = 30,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict]:
        """查询币本位合约基差历史数据.

        GET /futures/data/basis  (权重: 1)

        仅返回最近 30 天数据；未指定 startTime/endTime 时返回最新 limit 条。

        Args:
            pair:          基础交易对，如 "BTCUSD"（必填）。
            contract_type: 合约类型（必填）：
                             PERPETUAL         永续合约
                             CURRENT_QUARTER   当季交割合约
                             NEXT_QUARTER      次季交割合约
            period:        统计周期（必填）：
                             "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"
            limit:         返回条数，默认 30，最大 500。
            start_time:    起始时间（毫秒时间戳）。
            end_time:      结束时间（毫秒时间戳）。

        Returns:
            list[dict]，每条记录包含:
              - pair                基础交易对
              - contractType        合约类型
              - futuresPrice        合约价格
              - indexPrice          指数价格
              - basis               基差 (futuresPrice - indexPrice)
              - basisRate           基差率 (basis / indexPrice)
              - annualizedBasisRate  年化基差率
              - timestamp           数据时间戳（毫秒）
        """
        params: dict[str, Any] = {
            "pair": pair,
            "contractType": contract_type,
            "period": period,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._client.get("/futures/data/basis", params=params)
