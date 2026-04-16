"""U本位合约市场数据 API (FAPI).

文档参考:
  - Kline/Candlestick Data:
    https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data
  - Continuous Contract Kline:
    https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Continuous-Contract-Kline-Candlestick-Data
  - Open Interest Statistics:
    https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics

Base URL: https://fapi.binance.com
所有接口无需签名。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator

from .base import BaseAPI

if TYPE_CHECKING:
    from ..storage.kafka import KafkaStorage

logger = logging.getLogger("binance_toolkit.api.futures_market")

# FAPI 单次最大返回条数
_MAX_LIMIT = 1500

# OI 统计接口单次最大返回条数
_OI_MAX_LIMIT = 500

# 请求间隔 (秒)，避免触发频率限制
_REQUEST_INTERVAL = 0.2


def _row_to_record(row: list, symbol: str, interval: str) -> dict[str, Any]:
    """将 FAPI klines 原始行转换为标准 K线记录.

    FAPI 响应行结构:
      [0]  open_time               ms
      [1]  open                    str
      [2]  high                    str
      [3]  low                     str
      [4]  close                   str
      [5]  volume                  str
      [6]  close_time              ms
      [7]  quote_volume            str
      [8]  trade_count             int
      [9]  taker_buy_volume        str
      [10] taker_buy_quote_volume  str
      [11] ignore                  str
    """
    open_time_ms = int(row[0])
    return {
        "symbol": symbol,
        "interval": interval,
        "open_time": open_time_ms,
        "close_time": int(row[6]),
        "open": str(row[1]),
        "high": str(row[2]),
        "low": str(row[3]),
        "close": str(row[4]),
        "volume": str(row[5]),
        "quote_volume": str(row[7]),
        "trade_count": int(row[8]),
        "taker_buy_volume": str(row[9]),
        "taker_buy_quote_volume": str(row[10]),
        "is_closed": True,          # 历史数据全部是已收盘的 K线
        "event_time": open_time_ms,  # 历史数据没有 event_time，用 open_time 代替
        "timestamp": datetime.fromtimestamp(
            open_time_ms / 1000, tz=timezone.utc
        ).isoformat(),
    }


def _oi_row_to_record(row: dict, period: str) -> dict[str, Any]:
    """将 openInterestHist 原始行转换为标准 OI 记录.

    响应字段:
      symbol                 str
      sumOpenInterest        str  — 持仓量（合约张数）
      sumOpenInterestValue   str  — 持仓量价值（USDT）
      timestamp              str  — 毫秒时间戳（字符串）
    """
    ts = int(row["timestamp"])
    return {
        "symbol": str(row["symbol"]),
        "period": period,
        "sum_open_interest": str(row["sumOpenInterest"]),
        "sum_open_interest_value": str(row["sumOpenInterestValue"]),
        "timestamp": ts,
        "timestamp_iso": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
    }


class FuturesMarketAPI(BaseAPI):
    """U本位合约市场数据接口 (无需签名).

    所有请求发往 fapi.binance.com。
    """

    # ------------------------------------------------------------------ #
    #  基础 K线查询（单次，最多 1500 条）
    # ------------------------------------------------------------------ #

    def klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[list]:
        """查询 U本位合约 K线数据.

        GET /fapi/v1/klines  (权重: 调用时基于 limit 动态计算)

        Args:
            symbol:     合约交易对，如 "BTCUSDT"。
            interval:   K 线间隔，如 "1d" / "1h" / "15m"。
            start_time: 起始开盘时间（毫秒时间戳）。
            end_time:   截止开盘时间（毫秒时间戳）。
            limit:      返回条数，默认 500，最大 1500。

        Returns:
            list of lists，每个元素为:
              [open_time, open, high, low, close, volume,
               close_time, quote_volume, trade_count,
               taker_buy_volume, taker_buy_quote_volume, ignore]
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, _MAX_LIMIT),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._client.get("/fapi/v1/klines", params=params)

    def klines_as_records(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """查询 K线数据并返回标准化 dict 列表（与 Kafka 消息格式一致）."""
        rows = self.klines(
            symbol, interval,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        return [_row_to_record(row, symbol.upper(), interval) for row in rows]

    # ------------------------------------------------------------------ #
    #  分页拉取（历史全量或指定时间范围）
    # ------------------------------------------------------------------ #

    def iter_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        request_interval: float = _REQUEST_INTERVAL,
    ) -> Iterator[list[dict[str, Any]]]:
        """逐批次获取历史 K线（自动翻页），每批返回标准化 dict 列表.

        分页逻辑：
          每次取 _MAX_LIMIT 条，以最后一根 K线的 close_time + 1ms 作为下一页
          的 startTime，直到返回条数 < _MAX_LIMIT 或超过 end_time。

        Args:
            symbol:           合约交易对。
            interval:         K 线间隔。
            start_time:       起始时间（毫秒时间戳）。省略则从最早数据开始。
            end_time:         截止时间（毫秒时间戳）。省略则到当前时间。
            request_interval: 每次请求之间的等待秒数，默认 0.2s。

        Yields:
            每批 K线 records (list[dict])。
        """
        symbol = symbol.upper()
        cursor = start_time
        fetched = 0

        while True:
            params: dict[str, Any] = {
                "symbol": symbol,
                "interval": interval,
                "limit": _MAX_LIMIT,
            }
            if cursor is not None:
                params["startTime"] = cursor
            if end_time is not None:
                params["endTime"] = end_time

            rows: list[list] = self._client.get("/fapi/v1/klines", params=params)

            if not rows:
                break

            records = [_row_to_record(row, symbol, interval) for row in rows]
            fetched += len(records)
            logger.debug(
                "iter_klines %s %s: 本批 %d 条, 累计 %d 条, 当前 open_time=%s",
                symbol, interval, len(records), fetched,
                datetime.fromtimestamp(records[0]["open_time"] / 1000, tz=timezone.utc)
                .strftime("%Y-%m-%d"),
            )

            yield records

            if len(rows) < _MAX_LIMIT:
                # 最后一页
                break

            # 下一页从最后一根 K线的 close_time + 1ms 开始
            last_close_time = int(rows[-1][6])
            cursor = last_close_time + 1

            if end_time is not None and cursor > end_time:
                break

            if request_interval > 0:
                time.sleep(request_interval)

    def fetch_klines_range(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        write_kafka: bool = False,
        kafka_storage: "KafkaStorage | None" = None,
        kafka_topic: str = "binance.kline.usdt_futures",
        request_interval: float = _REQUEST_INTERVAL,
        enable_print: bool = True,
    ) -> list[dict[str, Any]]:
        """拉取指定时间范围内的全部历史 K线，可选写入 Kafka.

        适合一次性回填历史数据，或每天定时补全前一天的 K线。

        Args:
            symbol:           合约交易对。
            interval:         K 线间隔，如 "1d"。
            start_time:       起始时间（毫秒时间戳），省略则从最早数据开始。
            end_time:         截止时间（毫秒时间戳），省略则到当前时间。
            write_kafka:      是否写入 Kafka，需同时提供 kafka_storage。
            kafka_storage:    KafkaStorage 实例。
            kafka_topic:      目标 Kafka Topic。
            request_interval: 翻页间隔秒数。
            enable_print:     是否打印进度到控制台。

        Returns:
            所有 K线 records 汇总列表。
        """
        all_records: list[dict[str, Any]] = []

        for batch in self.iter_klines(
            symbol, interval,
            start_time=start_time,
            end_time=end_time,
            request_interval=request_interval,
        ):
            all_records.extend(batch)

            if write_kafka and kafka_storage is not None:
                kafka_storage.write_kline_batch(batch, kafka_topic)

            if enable_print:
                first_dt = datetime.fromtimestamp(
                    batch[0]["open_time"] / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d")
                last_dt = datetime.fromtimestamp(
                    batch[-1]["open_time"] / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d")
                kafka_info = f" → Kafka [{kafka_topic}]" if write_kafka else ""
                print(
                    f"  {symbol} {interval}: {first_dt} ~ {last_dt} "
                    f"({len(batch)} 条){kafka_info}"
                )

        if enable_print:
            print(f"\n共拉取 {len(all_records)} 条 K线 [{symbol} {interval}]")

        return all_records

    # ------------------------------------------------------------------ #
    #  持仓量统计（Open Interest Statistics）
    # ------------------------------------------------------------------ #

    def open_interest_hist(
        self,
        symbol: str,
        period: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """查询 U本位合约持仓量统计（单次，最多 500 条）.

        GET /futures/data/openInterestHist  (IP 限速: 1000次/5min)

        注意: Binance 仅保留最近 1 个月的数据。

        Args:
            symbol:     合约交易对，如 "BTCUSDT"。
            period:     统计周期，"5m" / "15m" / "30m" /
                        "1h" / "2h" / "4h" / "6h" / "12h" / "1d"。
            start_time: 起始时间（毫秒时间戳）。
            end_time:   截止时间（毫秒时间戳）。
            limit:      返回条数，默认 500，最大 500。

        Returns:
            list of dicts，每个元素包含:
              symbol, sumOpenInterest, sumOpenInterestValue, timestamp
        """
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "period": period,
            "limit": min(limit, _OI_MAX_LIMIT),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        return self._client.get("/futures/data/openInterestHist", params=params)

    def open_interest_hist_as_records(
        self,
        symbol: str,
        period: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """查询持仓量统计并返回标准化 dict 列表（与 Kafka 消息格式一致）."""
        rows = self.open_interest_hist(
            symbol, period,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        return [_oi_row_to_record(row, period) for row in rows]

    def iter_open_interest(
        self,
        symbol: str,
        period: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        request_interval: float = _REQUEST_INTERVAL,
    ) -> Iterator[list[dict[str, Any]]]:
        """逐批次获取历史持仓量统计（自动翻页），每批返回标准化 dict 列表.

        分页逻辑：
          每次取 _OI_MAX_LIMIT 条，以最后一条的 timestamp + 1ms 作为下一页
          的 startTime，直到返回条数 < _OI_MAX_LIMIT 或超过 end_time。

        注意: Binance 仅保留最近 1 个月的数据。

        Args:
            symbol:           合约交易对。
            period:           统计周期。
            start_time:       起始时间（毫秒时间戳）。
            end_time:         截止时间（毫秒时间戳）。
            request_interval: 每次请求之间的等待秒数，默认 0.2s。

        Yields:
            每批 OI records (list[dict])。
        """
        symbol = symbol.upper()
        cursor = start_time
        fetched = 0

        while True:
            params: dict[str, Any] = {
                "symbol": symbol,
                "period": period,
                "limit": _OI_MAX_LIMIT,
            }
            if cursor is not None:
                params["startTime"] = cursor
            if end_time is not None:
                params["endTime"] = end_time

            rows: list[dict] = self._client.get(
                "/futures/data/openInterestHist", params=params
            )

            if not rows:
                break

            records = [_oi_row_to_record(row, period) for row in rows]
            fetched += len(records)
            logger.debug(
                "iter_open_interest %s %s: 本批 %d 条, 累计 %d 条, 当前 timestamp=%s",
                symbol, period, len(records), fetched,
                datetime.fromtimestamp(records[0]["timestamp"] / 1000, tz=timezone.utc)
                .strftime("%Y-%m-%d %H:%M"),
            )

            yield records

            if len(rows) < _OI_MAX_LIMIT:
                break

            # 下一页从最后一条的 timestamp + 1ms 开始
            last_ts = int(rows[-1]["timestamp"])
            cursor = last_ts + 1

            if end_time is not None and cursor > end_time:
                break

            if request_interval > 0:
                time.sleep(request_interval)

    def fetch_oi_range(
        self,
        symbol: str,
        period: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        write_kafka: bool = False,
        kafka_storage: "KafkaStorage | None" = None,
        kafka_topic: str = "binance.oi.usdt_futures",
        request_interval: float = _REQUEST_INTERVAL,
        enable_print: bool = True,
    ) -> list[dict[str, Any]]:
        """拉取指定时间范围内的全部持仓量统计，可选写入 Kafka.

        注意: Binance 仅保留最近 1 个月的数据。

        Args:
            symbol:           合约交易对。
            period:           统计周期，如 "1h"。
            start_time:       起始时间（毫秒时间戳），省略则从最早可用数据开始。
            end_time:         截止时间（毫秒时间戳），省略则到当前时间。
            write_kafka:      是否写入 Kafka，需同时提供 kafka_storage。
            kafka_storage:    KafkaStorage 实例。
            kafka_topic:      目标 Kafka Topic。
            request_interval: 翻页间隔秒数。
            enable_print:     是否打印进度到控制台。

        Returns:
            所有 OI records 汇总列表。
        """
        all_records: list[dict[str, Any]] = []

        for batch in self.iter_open_interest(
            symbol, period,
            start_time=start_time,
            end_time=end_time,
            request_interval=request_interval,
        ):
            all_records.extend(batch)

            if write_kafka and kafka_storage is not None:
                kafka_storage.write_oi_batch(batch, kafka_topic)

            if enable_print:
                first_dt = datetime.fromtimestamp(
                    batch[0]["timestamp"] / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M")
                last_dt = datetime.fromtimestamp(
                    batch[-1]["timestamp"] / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M")
                kafka_info = f" → Kafka [{kafka_topic}]" if write_kafka else ""
                print(
                    f"  {symbol} {period}: {first_dt} ~ {last_dt} "
                    f"({len(batch)} 条){kafka_info}"
                )

        if enable_print:
            print(f"\n共拉取 {len(all_records)} 条持仓量统计 [{symbol} {period}]")

        return all_records

