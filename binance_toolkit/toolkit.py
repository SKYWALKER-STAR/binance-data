"""Toolkit 门面类 — 统一入口.

将所有 API 模块组合在一起，提供简洁的使用方式:

    from binance_toolkit import BinanceToolkit, BinanceConfig

    config = BinanceConfig.from_env()
    tk = BinanceToolkit(config)
    print(tk.market.ping())
    print(tk.market.ticker_price("BTCUSDT"))
"""

from __future__ import annotations

import dataclasses

from .api.account import AccountAPI
from .api.coin_futures import CoinFuturesMarketAPI
from .api.market import MarketAPI
from .api.trade import TradeAPI
from .client import BinanceClient
from .config import BinanceConfig


class BinanceToolkit:
    """Binance API 工具箱门面.

    通过属性访问各业务模块:
      - toolkit.market        → MarketAPI          (现货市场数据)
      - toolkit.trade         → TradeAPI            (现货交易)
      - toolkit.account       → AccountAPI          (账户信息)
      - toolkit.coin_futures  → CoinFuturesMarketAPI (币本位合约市场数据)

    扩展新模块只需:
      1. 在 api/ 下新建模块继承 BaseAPI
      2. 在此类中添加一个属性即可
    """

    def __init__(self, config: BinanceConfig):
        self._client = BinanceClient(config)
        self.market = MarketAPI(self._client)
        self.trade = TradeAPI(self._client)
        self.account = AccountAPI(self._client)

        # 币本位合约使用独立的 DAPI base URL
        dapi_config = dataclasses.replace(config, base_url=config.dapi_base_url)
        self._dapi_client = BinanceClient(dapi_config)
        self.coin_futures = CoinFuturesMarketAPI(self._dapi_client)

    def close(self) -> None:
        self._client.close()
        self._dapi_client.close()

    def __enter__(self) -> "BinanceToolkit":
        return self

    def __exit__(self, *args) -> None:
        self.close()
