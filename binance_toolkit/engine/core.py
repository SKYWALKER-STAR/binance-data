"""Strategy engine runtime loop."""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from typing import Any

from ..config import BinanceConfig
from ..storage.kafka import KafkaStorage
from ..ws.futures_trade_ws import FuturesTradeWsClient
from .audit import EngineAuditLogger
from .clickhouse_source import ClickHouseSignalSource, ClickHouseSourceConfig
from .executor import ExecutionConfig, FuturesExecutionAdapter
from .health import EngineHealthServer
from .models import TradingSignal
from .risk import RiskConfig, RiskGuard
from .state_store import EngineStateStore, SignalStatus

logger = logging.getLogger("binance_toolkit.engine").setLevel(logging.DEBUG)
if not isinstance(logger, logging.Logger):
    raise RuntimeError(
        f"logging.getLogger() returned {type(logger)!r} instead of logging.Logger. "
        "A local 'logging.py' file or 'logging/' directory is shadowing stdlib logging. "
        f"Loaded logging module from: {getattr(logging, '__file__', 'unknown')}"
    )

_FINAL_MAP = {
    "FILLED": SignalStatus.FILLED,
    "CANCELED": SignalStatus.CANCELED,
    "REJECTED": SignalStatus.REJECTED_BY_EXCHANGE,
    "EXPIRED": SignalStatus.EXPIRED,
}


@dataclass(frozen=True)
class EngineConfig:
    poll_interval_sec: float = 1.0
    reconcile_interval_sec: float = 5.0
    reconcile_lag_sec: int = 2
    reconcile_batch_size: int = 200


class StrategyEngine:
    """Event-driven strategy engine with pull source and durable state."""

    def __init__(self, app_config: BinanceConfig, *, dry_run: bool = False):
        self._dry_run = dry_run
        source_cfg = ClickHouseSourceConfig(
            url=app_config.clickhouse_signal_url or "",
            database=app_config.clickhouse_database,
            table=app_config.clickhouse_signal_table,
            user=app_config.clickhouse_user,
            password=app_config.clickhouse_password,
            where_clause=app_config.clickhouse_signal_where,
            timeout=app_config.clickhouse_timeout,
            batch_size=app_config.engine_clickhouse_batch_size,
            startup_lookback_ms=app_config.engine_startup_lookback_ms,
        )
        risk_cfg = RiskConfig(
            max_notional_per_order=app_config.engine_max_notional_per_order,
            max_actions_per_minute_per_symbol=app_config.engine_max_actions_per_min_symbol,
        )

        self._engine_cfg = EngineConfig(
            poll_interval_sec=app_config.engine_poll_interval_sec,
            reconcile_interval_sec=app_config.engine_reconcile_interval_sec,
            reconcile_lag_sec=app_config.engine_reconcile_lag_sec,
            reconcile_batch_size=app_config.engine_reconcile_batch_size,
        )

        self._source = ClickHouseSignalSource(source_cfg)
        self._startup_lookback_ms = source_cfg.startup_lookback_ms
        self._state = EngineStateStore(app_config.engine_state_db_path)
        self._risk = RiskGuard(risk_cfg)
        self._kafka: KafkaStorage | None = None
        self._audit: EngineAuditLogger | None = None
        if app_config.kafka_bootstrap_servers:
            self._kafka = KafkaStorage(app_config)
            self._audit = EngineAuditLogger(self._kafka, app_config.kafka_topic_engine_events)

        self._trade_client: FuturesTradeWsClient | None = None
        if not dry_run:
            self._trade_client = FuturesTradeWsClient(
                app_config,
                kafka_storage=self._kafka,
                kafka_topic=app_config.kafka_topic_futures_trade,
                request_timeout=app_config.engine_request_timeout,
            )
        self._executor = FuturesExecutionAdapter(
            self._trade_client,
            ExecutionConfig(dry_run=dry_run),
        )
        self._health = EngineHealthServer(
            app_config.engine_health_host,
            app_config.engine_health_port,
            self.snapshot,
        )

        self._stop = False
        self._started_at_ms = int(time.time() * 1000)
        self._last_poll_at_ms = 0
        self._last_signal_at_ms = 0
        self._last_reconcile_at_ms = 0
        self._metrics: dict[str, int] = {
            "pulled": 0,
            "accepted": 0,
            "rejected": 0,
            "executed": 0,
            "failed": 0,
            "deduplicated": 0,
            "reconciled": 0,
        }

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        cursor = self._init_cursor()
        self._health.start()
        logger.info("StrategyEngine started, cursor=%s", cursor)
        self._emit_engine_event(
            "engine_started",
            payload={
                "cursor_ms": cursor,
                "dry_run": self._dry_run,
            },
            metrics=self._metrics,
        )

        next_reconcile = time.time()
        while not self._stop:
            logger.debug("engine loop tick cursor_ms=%s", cursor)
            try:
                cursor = self._poll_once(cursor)
                if time.time() >= next_reconcile:
                    logger.debug("reconcile interval reached, starting reconcile")
                    self._reconcile_once()
                    next_reconcile = time.time() + self._engine_cfg.reconcile_interval_sec
            except Exception as exc:
                self._emit_engine_event(
                    "engine_loop_error",
                    payload={"error": str(exc)},
                    metrics=self._metrics,
                )
                logger.exception("engine loop error")

            if not self._stop:
                time.sleep(self._engine_cfg.poll_interval_sec)

        logger.info("StrategyEngine stopped metrics=%s", self._metrics)
        self._emit_engine_event(
            "engine_stopped",
            payload={"cursor_ms": cursor},
            metrics=self._metrics,
        )
        self.close()

    def close(self) -> None:
        self._health.stop()
        self._source.close()
        if self._trade_client is not None:
            self._trade_client.close()
        self._state.close()
        if self._kafka is not None:
            self._kafka.close()

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": "stopping" if self._stop else "running",
            "started_at_ms": self._started_at_ms,
            "last_poll_at_ms": self._last_poll_at_ms,
            "last_signal_at_ms": self._last_signal_at_ms,
            "last_reconcile_at_ms": self._last_reconcile_at_ms,
            "cursor_ms": self._state.get_cursor_ms(),
            "metrics": dict(self._metrics),
        }

    def _poll_once(self, cursor: int) -> int:
        logger.debug("[poll] fetching signals after cursor_ms=%s", cursor)
        self._last_poll_at_ms = int(time.time() * 1000)
        rows = self._source.fetch(after_ts_ms=cursor)
        if not rows:
            logger.debug("[poll] no new signals")
            return cursor

        logger.debug("[poll] fetched %d signal(s)", len(rows))
        self._metrics["pulled"] += len(rows)
        for signal_item in rows:
            cursor = max(cursor, signal_item.signal_ts_ms)
            self._state.set_cursor_ms(cursor)
            self._process_signal(signal_item)
        return cursor

    def _process_signal(self, signal_item: TradingSignal) -> None:
        logger.debug(
            "[signal] processing signal_id=%s action=%s symbol=%s",
            signal_item.signal_id,
            signal_item.action,
            signal_item.symbol,
        )
        self._last_signal_at_ms = int(time.time() * 1000)
        if self._state.is_final(signal_item.signal_id):
            self._metrics["deduplicated"] += 1
            self._emit_signal_event(
                signal_item,
                "signal_deduplicated",
                status="DEDUPLICATED",
                reason="already final",
            )
            logger.debug("deduplicated signal_id=%s", signal_item.signal_id)
            return

        logger.debug("[signal] saving received state signal_id=%s", signal_item.signal_id)
        self._state.save_received(signal_item, raw_row=signal_item.__dict__)
        self._emit_signal_event(
            signal_item,
            "signal_received",
            status=SignalStatus.RECEIVED,
            reason="received",
        )

        logger.debug("[signal] running risk check signal_id=%s", signal_item.signal_id)
        ok, reason = self._risk.check(signal_item)
        if not ok:
            self._metrics["rejected"] += 1
            self._state.update_status(signal_item.signal_id, status=SignalStatus.REJECTED, reason=reason)
            self._emit_signal_event(
                signal_item,
                "signal_rejected",
                status=SignalStatus.REJECTED,
                reason=reason,
            )
            logger.info("signal rejected signal_id=%s reason=%s", signal_item.signal_id, reason)
            return

        self._metrics["accepted"] += 1
        logger.debug("[signal] risk check passed, dispatching signal_id=%s", signal_item.signal_id)
        self._state.update_status(signal_item.signal_id, status=SignalStatus.SENT, reason="dispatching")
        self._emit_signal_event(
            signal_item,
            "signal_dispatched",
            status=SignalStatus.SENT,
            reason="dispatching",
        )

        try:
            logger.debug("[signal] calling executor signal_id=%s action=%s", signal_item.signal_id, signal_item.action)
            result = self._executor.execute(signal_item)
            mapped = _FINAL_MAP.get(result.status.upper())
            if mapped:
                self._state.update_status(
                    signal_item.signal_id,
                    status=mapped,
                    reason=result.message,
                    order_id=result.order_id,
                    client_order_id=result.client_order_id,
                )
                self._emit_signal_event(
                    signal_item,
                    "signal_executed",
                    status=mapped,
                    reason=result.message,
                    payload={
                        "order_id": result.order_id,
                        "client_order_id": result.client_order_id,
                    },
                )
            else:
                self._state.update_status(
                    signal_item.signal_id,
                    status=SignalStatus.ACKED,
                    reason=result.message,
                    order_id=result.order_id,
                    client_order_id=result.client_order_id,
                )
                self._emit_signal_event(
                    signal_item,
                    "signal_acked",
                    status=SignalStatus.ACKED,
                    reason=result.message,
                    payload={
                        "order_id": result.order_id,
                        "client_order_id": result.client_order_id,
                    },
                )

            self._metrics["executed"] += 1
            logger.info(
                "signal executed signal_id=%s action=%s status=%s order_id=%s",
                signal_item.signal_id,
                signal_item.action,
                result.status,
                result.order_id,
            )
        except Exception as exc:
            self._metrics["failed"] += 1
            self._state.update_status(
                signal_item.signal_id,
                status=SignalStatus.FAILED,
                reason=str(exc),
            )
            self._emit_signal_event(
                signal_item,
                "signal_failed",
                status=SignalStatus.FAILED,
                reason=str(exc),
            )
            logger.exception("signal execute failed signal_id=%s", signal_item.signal_id)

    def _reconcile_once(self) -> None:
        if self._dry_run:
            logger.debug("[reconcile] skipped (dry-run mode)")
            return

        self._last_reconcile_at_ms = int(time.time() * 1000)
        older_than_ms = int((time.time() - self._engine_cfg.reconcile_lag_sec) * 1000)
        logger.debug("[reconcile] querying candidates older_than_ms=%s", older_than_ms)
        candidates = self._state.list_reconcile_candidates(
            older_than_ms=older_than_ms,
            limit=self._engine_cfg.reconcile_batch_size,
        )
        if not candidates:
            logger.debug("[reconcile] no candidates to reconcile")
            return

        logger.debug("[reconcile] found %d candidate(s)", len(candidates))
        for row in candidates:
            signal_id = str(row["signal_id"])
            symbol = str(row["symbol"])
            logger.debug("[reconcile] querying order signal_id=%s symbol=%s", signal_id, symbol)
            try:
                result = self._executor.query_order(
                    symbol=symbol,
                    order_id=row.get("order_id"),
                    client_order_id=row.get("client_order_id"),
                )
                status = str(result.get("status", "")).upper()
                mapped = _FINAL_MAP.get(status)
                if mapped:
                    self._state.update_status(
                        signal_id,
                        status=mapped,
                        reason="reconciled",
                        order_id=result.get("orderId"),
                        client_order_id=result.get("clientOrderId"),
                    )
                    reconciled_status = mapped
                else:
                    self._state.update_status(
                        signal_id,
                        status=SignalStatus.ACKED,
                        reason="reconciled_non_final",
                        order_id=result.get("orderId"),
                        client_order_id=result.get("clientOrderId"),
                    )
                    reconciled_status = SignalStatus.ACKED
                self._metrics["reconciled"] += 1
                self._emit_engine_event(
                    "signal_reconciled",
                    payload={
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "status": reconciled_status,
                        "order_id": result.get("orderId"),
                        "client_order_id": result.get("clientOrderId"),
                    },
                    metrics=self._metrics,
                )
            except Exception as exc:
                self._emit_engine_event(
                    "signal_reconcile_failed",
                    payload={"signal_id": signal_id, "symbol": symbol, "error": str(exc)},
                    metrics=self._metrics,
                )
                logger.exception("reconcile failed signal_id=%s", signal_id)

    def _init_cursor(self) -> int:
        current = self._state.get_cursor_ms()
        if current is not None:
            return current
        lookback = int(time.time() * 1000) - self._startup_lookback_ms
        self._state.set_cursor_ms(lookback)
        return lookback

    def _handle_signal(self, signum: int, frame: Any) -> None:
        # logger may be None during interpreter shutdown
        if logger is not None:
            logger.info("received signal=%s, stopping engine", signum)
        self._stop = True

    def _emit_signal_event(
        self,
        signal_item: TradingSignal,
        event_type: str,
        *,
        status: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self._audit is None:
            return
        self._audit.emit(
            event_type,
            signal_item=signal_item,
            status=status,
            reason=reason,
            metrics=self._metrics,
            payload=payload,
        )

    def _emit_engine_event(
        self,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        metrics: dict[str, int] | None = None,
    ) -> None:
        if self._audit is None:
            return
        self._audit.emit(event_type, metrics=metrics, payload=payload)
