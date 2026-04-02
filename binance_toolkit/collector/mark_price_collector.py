"""币本位合约标记价格/指数价格采集器 — 常驻进程, 定时获取数据并写入 InfluxDB."""

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


class MarkPriceCollector:
    """定时采集币本位合约的标记价格和指数价格, 写入 InfluxDB.

    特性:
      - 可配置采集间隔 (默认 60 秒)
      - 可同时采集多个合约交易对
      - 优雅停止 (SIGINT / SIGTERM)
      - 单次采集失败不会中断进程, 仅记录日志

    用法:
        config = BinanceConfig.from_env()
        collector = MarkPriceCollector(config, symbols=["BTCUSD_PERP"], interval=60)
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
            symbols:  要采集的合约交易对列表, 默认 ["BTCUSD_PERP"]。
                      传入 None 或空列表时, 每次采集全部永续合约。
            interval: 采集间隔 (秒), 默认 60.
        """
        self._config = config
        self._symbols = symbols or ["BTCUSD_PERP"]
        self._interval = interval
        self._stop_event = threading.Event()
        self._toolkit: BinanceToolkit | None = None
        self._storage: InfluxDBStorage | None = None

    def run(self) -> None:
        """启动采集循环 (阻塞).

        通过 SIGINT (Ctrl+C) 或 SIGTERM 优雅退出.
        """
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            "标记价格采集器启动: symbols=%s, interval=%ds",
            self._symbols,
            self._interval,
        )

        self._toolkit = BinanceToolkit(self._config)
        self._storage = InfluxDBStorage(self._config)

        try:
            while not self._stop_event.is_set():
                self._collect_once()
                self._stop_event.wait(timeout=self._interval)
        finally:
            self._cleanup()

    def stop(self) -> None:
        """请求停止采集."""
        logger.info("收到停止信号, 正在优雅退出...")
        self._stop_event.set()

    def _collect_once(self) -> None:
        """执行一次采集: 获取所有指定合约的标记/指数价格并写入 InfluxDB."""
        assert self._toolkit is not None
        assert self._storage is not None

        for symbol in self._symbols:
            try:
                results = self._toolkit.coin_futures.premium_index(symbol=symbol)
                # 单个 symbol 时 API 返回 list，取第一条
                if isinstance(results, list):
                    records = results
                else:
                    records = [results]

                for record in records:
                    sym = record.get("symbol", symbol)
                    mark_price = float(record.get("markPrice", 0))
                    index_price = float(record.get("indexPrice", 0))

                    # 资金费率仅永续合约有效 (交割合约返回空字符串)
                    raw_rate = record.get("lastFundingRate", "")
                    last_funding_rate = float(raw_rate) if raw_rate else None

                    raw_nft = record.get("nextFundingTime", 0)
                    next_funding_time = int(raw_nft) if raw_nft else None

                    self._storage.write_mark_price(
                        sym,
                        mark_price,
                        index_price,
                        last_funding_rate=last_funding_rate,
                        next_funding_time=next_funding_time,
                    )
                    logger.info(
                        "✓ %s mark=%.4f index=%.4f",
                        sym, mark_price, index_price,
                    )
            except Exception:
                logger.exception("✗ 采集 %s 标记价格失败", symbol)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s", sig_name)
        self.stop()

    def _cleanup(self) -> None:
        if self._storage:
            self._storage.close()
        if self._toolkit:
            self._toolkit.close()
        logger.info("标记价格采集器已停止")
