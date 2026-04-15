"""ClickHouse pull-based signal source."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import requests

from .models import TradingSignal

logger = logging.getLogger("binance_toolkit.engine.clickhouse")


@dataclass(frozen=True)
class ClickHouseSourceConfig:
    url: str
    database: str
    table: str
    user: str | None = None
    password: str | None = None
    where_clause: str | None = None
    timeout: int = 10
    batch_size: int = 200
    startup_lookback_ms: int = 5 * 60 * 1000


class ClickHouseSignalSource:
    """Pull signals from ClickHouse HTTP interface."""

    def __init__(self, config: ClickHouseSourceConfig):
        if not config.url:
            raise ValueError("clickhouse_signal_url 未配置")
        self._config = config
        self._session = requests.Session()

    def fetch(self, *, after_ts_ms: int) -> list[TradingSignal]:
        sql = self._build_query(after_ts_ms=after_ts_ms)
        rows = self._execute_sql(sql)
        signals: list[TradingSignal] = []
        for row in rows:
            try:
                signals.append(TradingSignal.from_row(row))
            except Exception as exc:
                logger.warning("忽略非法信号行: %s; row=%s", exc, row)
        signals.sort(key=lambda s: (s.signal_ts_ms, -s.priority, s.signal_id))
        return signals

    def close(self) -> None:
        self._session.close()

    def _build_query(self, *, after_ts_ms: int) -> str:
        where_parts = [f"signal_ts_ms > {int(after_ts_ms)}"]
        if self._config.where_clause:
            where_parts.append(f"({self._config.where_clause})")

        where = " AND ".join(where_parts)
        cols = ", ".join(
            [
                "signal_id",
                "strategy_id",
                "symbol",
                "action",
                "signal_ts_ms",
                "ttl_ms",
                "priority",
                "side",
                "order_type",
                "quantity",
                "price",
                "time_in_force",
                "position_side",
                "reduce_only",
                "close_position",
                "order_id",
                "orig_client_order_id",
            ]
        )
        return (
            f"SELECT {cols} "
            f"FROM {self._config.table} "
            f"WHERE {where} "
            "ORDER BY signal_ts_ms ASC, priority DESC, signal_id ASC "
            f"LIMIT {int(self._config.batch_size)}"
        )

    def _execute_sql(self, sql: str) -> list[dict]:
        logger.debug("ClickHouse pull sql: %s", sql)
        auth = None
        if self._config.user:
            auth = (self._config.user, self._config.password or "")

        resp = self._session.post(
            self._config.url,
            params={"database": self._config.database},
            data=f"{sql} FORMAT JSONEachRow",
            auth=auth,
            timeout=self._config.timeout,
        )
        resp.raise_for_status()

        rows: list[dict] = []
        for line in resp.text.splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows
