"""Futures position collector via Binance WS API -> Redis."""

from __future__ import annotations

import logging
import signal
import threading
from typing import Any, Optional

from ..config import BinanceConfig
from ..storage.redis_position import RedisPositionStore
from ..ws.futures_trade_ws import FuturesTradeWsClient

logger = logging.getLogger("binance_toolkit.collector.position_redis")


class FuturesPositionRedisCollector:
    """Periodically fetch positions via WS API and persist latest snapshot into Redis."""

    def __init__(
        self,
        config: BinanceConfig,
        *,
        symbol: Optional[str] = None,
        interval_sec: Optional[float] = None,
        enable_print: bool = True,
    ) -> None:
        self._config = config
        self._symbol = symbol.strip().upper() if symbol else None
        self._interval_sec = interval_sec or config.redis_position_sync_interval_sec
        self._enable_print = enable_print
        self._stop_event = threading.Event()

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            "启动仓位同步: symbol=%s interval=%.3fs",
            self._symbol or "ALL",
            self._interval_sec,
        )

        store = RedisPositionStore(self._config)
        client = FuturesTradeWsClient(self._config, kafka_storage=None)

        try:
            while not self._stop_event.is_set():
                positions = client.query_position(symbol=self._symbol)
                active_positions = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
                count = store.write_positions(active_positions)

                if self._enable_print:
                    print(f"同步完成: {count} 个活跃仓位")

                logger.info("仓位同步成功: active=%d", count)
                self._stop_event.wait(timeout=self._interval_sec)
        finally:
            try:
                client.close()
            except Exception:
                logger.debug("关闭 WS 客户端异常", exc_info=True)
            store.close()
            logger.info("仓位同步已停止")

    def stop(self) -> None:
        self._stop_event.set()

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在退出", sig_name)
        self.stop()
