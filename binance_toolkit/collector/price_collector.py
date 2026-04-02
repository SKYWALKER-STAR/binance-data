"""价格采集器 — 常驻进程, 定时获取价格并写入 InfluxDB."""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Any

from ..config import BinanceConfig
from ..storage.influxdb import InfluxDBStorage
from ..toolkit import BinanceToolkit

logger = logging.getLogger("binance_toolkit.collector")


class PriceCollector:
    """定时采集指定交易对的最新价格, 写入 InfluxDB.

    特性:
      - 可配置采集间隔 (默认 60 秒)
      - 可同时采集多个交易对
      - 优雅停止 (SIGINT / SIGTERM)
      - 单次采集失败不会中断进程, 仅记录日志

    用法:
        config = BinanceConfig.from_env()
        collector = PriceCollector(config, symbols=["BTCUSDT"], interval=60)
        collector.run()  # 阻塞运行, Ctrl+C 停止
    """

    def __init__(
        self,
        config: BinanceConfig,
        *,
        symbols: list[str] | None = None,
        interval: int = 60,
    ):
        """
        Args:
            config:   Binance 配置 (含 InfluxDB 配置).
            symbols:  要采集的交易对列表, 默认 ["BTCUSDT"].
            interval: 采集间隔 (秒), 默认 60.
        """
        self._config = config
        self._symbols = symbols or ["BTCUSDT"]
        self._interval = interval
        self._stop_event = threading.Event()
        self._toolkit: BinanceToolkit | None = None
        self._storage: InfluxDBStorage | None = None

    def run(self) -> None:
        """启动采集循环 (阻塞).

        通过 SIGINT (Ctrl+C) 或 SIGTERM 优雅退出.
        """
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            "价格采集器启动: symbols=%s, interval=%ds",
            self._symbols,
            self._interval,
        )

        self._toolkit = BinanceToolkit(self._config)
        self._storage = InfluxDBStorage(self._config)

        try:
            while not self._stop_event.is_set():
                self._collect_once()
                # 使用 Event.wait 替代 time.sleep, 以便能立即响应停止信号
                self._stop_event.wait(timeout=self._interval)
        finally:
            self._cleanup()

    def stop(self) -> None:
        """请求停止采集."""
        logger.info("收到停止信号, 正在优雅退出...")
        self._stop_event.set()

    def _collect_once(self) -> None:
        """执行一次采集: 获取所有交易对的价格并写入 InfluxDB."""
        assert self._toolkit is not None
        assert self._storage is not None

        for symbol in self._symbols:
            try:
                data = self._toolkit.market.ticker_price(symbol=symbol)
                price = float(data.get("price", 0))
                self._storage.write_price(symbol, price)
                logger.info("✓ %s = %.4f", symbol, price)
            except Exception:
                logger.exception("✗ 采集 %s 失败", symbol)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s", sig_name)
        self.stop()

    def _cleanup(self) -> None:
        if self._storage:
            self._storage.close()
        if self._toolkit:
            self._toolkit.close()
        logger.info("采集器已停止")
