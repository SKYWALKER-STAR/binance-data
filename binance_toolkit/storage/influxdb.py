"""InfluxDB 存储后端.

将采集到的数据写入 InfluxDB 3.x（基于 influxdb3-python SDK）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..config import BinanceConfig

logger = logging.getLogger("binance_toolkit.storage")


class InfluxDBStorage:
    """InfluxDB 写入器.

    使用方式:
        storage = InfluxDBStorage(config)
        storage.write_price("BTCUSDT", 67123.45)
        storage.close()
    """

    def __init__(self, config: BinanceConfig):
        print(config.influx_host, config.influx_database)
        if not config.influx_host or not config.influx_database:
            raise ValueError(
                "InfluxDB 配置不完整, 需要设置 influx_host / influx_database"
            )

        self._measurement = config.influx_measurement

        try:
            from influxdb_client_3 import InfluxDBClient3, SYNCHRONOUS, WriteOptions, write_client_options
        except ImportError as exc:
            raise ImportError(
                "缺少依赖 influxdb3-python, 请执行: pip install 'influxdb3-python'"
            ) from exc

        wco = write_client_options(
            write_options=SYNCHRONOUS,
        )
        self._client = InfluxDBClient3(
            host=config.influx_host,
            database=config.influx_database,
            write_client_options=wco,
        )

    def write_price(
        self,
        symbol: str,
        price: float,
        *,
        timestamp: datetime | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """写入单条价格数据点.

        Args:
            symbol:       交易对, 如 "BTCUSDT".
            price:        当前价格.
            timestamp:    时间戳, 默认当前 UTC 时间.
            extra_fields: 额外字段 (如 volume 等).
        """
        ts = timestamp or datetime.now(timezone.utc)

        point = {
            "measurement": self._measurement,
            "tags": {"symbol": symbol},
            "fields": {"price": float(price)},
            "time": ts,
        }
        if extra_fields:
            point["fields"].update(extra_fields)

        try:
            self._client.write(record=point)
            logger.debug("已写入 %s price=%.4f @ %s", symbol, price, ts.isoformat())
        except Exception:
            logger.exception("写入 InfluxDB 失败: symbol=%s price=%s", symbol, price)
            raise

    def write_ticker(self, symbol: str, ticker_data: dict[str, Any]) -> None:
        """写入完整的 ticker 数据 (来自 /api/v3/ticker/price 或 /api/v3/ticker/24hr).

        自动提取 price 字段, 其余有意义的数字字段作为 extra_fields。
        """
        price = float(ticker_data.get("price", 0))
        extra: dict[str, Any] = {}

        # 24hr ticker 包含更多字段
        for key in ("volume", "quoteVolume", "highPrice", "lowPrice", "openPrice"):
            if key in ticker_data:
                try:
                    extra[key] = float(ticker_data[key])
                except (ValueError, TypeError):
                    pass

        self.write_price(symbol, price, extra_fields=extra or None)

    def close(self) -> None:
        self._client.close()
        logger.info("InfluxDB 连接已关闭")

    def __enter__(self) -> "InfluxDBStorage":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
