"""现货策略引擎."""

from __future__ import annotations

from typing import Any

from ..config import BinanceConfig
from ..ws.spot_trade_ws import SpotTradeWsClient
from .base import BaseStrategyEngine, ExecutionAdapter
from .executor import ExecutionConfig, SpotExecutionAdapter


class SpotStrategyEngine(BaseStrategyEngine):
    """现货策略引擎.

    从 ClickHouse 拉取 market='spot' 的信号，通过 SpotTradeWsClient 执行交易。

    用法::

        from binance_toolkit.config import BinanceConfig
        from binance_toolkit.engine import SpotStrategyEngine

        config = BinanceConfig.from_env()
        engine = SpotStrategyEngine(config, dry_run=False)
        engine.run()  # 阻塞运行，直到收到 SIGINT/SIGTERM
    """

    def __init__(self, app_config: BinanceConfig, *, dry_run: bool = False):
        super().__init__(app_config, dry_run=dry_run, state_db_suffix="spot")

    @property
    def _market_name(self) -> str:
        return "spot"

    def _create_trade_client(self) -> Any:
        return SpotTradeWsClient(
            self._app_config,
            kafka_storage=self._kafka,
            kafka_topic=self._get_kafka_topic(),
            request_timeout=self._app_config.engine_request_timeout,
        )

    def _create_executor(self) -> ExecutionAdapter:
        return SpotExecutionAdapter(
            self._trade_client,
            ExecutionConfig(dry_run=self._dry_run),
        )

    def _get_kafka_topic(self) -> str:
        return self._app_config.kafka_topic_spot_trade
