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
        self._futures_measurement = config.influx_futures_measurement

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

    def write_mark_price(
        self,
        symbol: str,
        mark_price: float,
        index_price: float,
        *,
        last_funding_rate: float | None = None,
        next_funding_time: int | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """写入币本位合约的标记价格和指数价格数据点.

        Args:
            symbol:            合约交易对, 如 "BTCUSD_PERP".
            mark_price:        标记价格.
            index_price:       指数价格.
            last_funding_rate: 最近一次资金费率 (仅永续合约).
            next_funding_time: 下次资金费时间戳毫秒 (仅永续合约).
            timestamp:         时间戳, 默认当前 UTC 时间.
        """
        ts = timestamp or datetime.now(timezone.utc)

        fields: dict[str, Any] = {
            "mark_price": float(mark_price),
            "index_price": float(index_price),
        }
        if last_funding_rate is not None:
            fields["last_funding_rate"] = float(last_funding_rate)
        if next_funding_time is not None:
            fields["next_funding_time"] = int(next_funding_time)

        point = {
            "measurement": self._futures_measurement,
            "tags": {"symbol": symbol},
            "fields": fields,
            "time": ts,
        }

        try:
            self._client.write(record=point)
            logger.debug(
                "已写入 %s mark_price=%.4f index_price=%.4f @ %s",
                symbol, mark_price, index_price, ts.isoformat(),
            )
        except Exception:
            logger.exception(
                "写入 InfluxDB 失败: symbol=%s mark_price=%s index_price=%s",
                symbol, mark_price, index_price,
            )
            raise

    def write_basis(
        self,
        pair: str,
        contract_type: str,
        futures_price: float,
        index_price: float,
        basis: float,
        basis_rate: float,
        annualized_basis_rate: float,
        *,
        timestamp: datetime | None = None,
    ) -> None:
        """写入币本位合约基差数据点.

        Args:
            pair:                  基础交易对, 如 "BTCUSD".
            contract_type:         合约类型, 如 "PERPETUAL" / "CURRENT_QUARTER".
            futures_price:         合约价格.
            index_price:           指数价格.
            basis:                 基差 (futuresPrice - indexPrice).
            basis_rate:            基差率 (basis / indexPrice).
            annualized_basis_rate: 年化基差率.
            timestamp:             时间戳, 默认当前 UTC 时间.
        """
        ts = timestamp or datetime.now(timezone.utc)

        point = {
            "measurement": self._futures_measurement,
            "tags": {
                "pair": pair,
                "contract_type": contract_type,
            },
            "fields": {
                "futures_price": float(futures_price),
                "index_price": float(index_price),
                "basis": float(basis),
                "basis_rate": float(basis_rate),
                "annualized_basis_rate": float(annualized_basis_rate),
            },
            "time": ts,
        }

        try:
            self._client.write(record=point)
            logger.debug(
                "已写入 %s [%s] basis=%.6f basis_rate=%.6f @ %s",
                pair, contract_type, basis, basis_rate, ts.isoformat(),
            )
        except Exception:
            logger.exception(
                "写入 InfluxDB 失败: pair=%s contract_type=%s basis=%s",
                pair, contract_type, basis,
            )
            raise

    def close(self) -> None:
        self._client.close()
        logger.info("InfluxDB 连接已关闭")

    def __enter__(self) -> "InfluxDBStorage":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
