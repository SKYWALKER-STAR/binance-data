"""Base strategy engine runtime loop."""

from __future__ import annotations

import logging
import signal
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from ..config import BinanceConfig
from ..storage.kafka import KafkaStorage
from .audit import EngineAuditLogger
from .clickhouse_source import ClickHouseSignalSource, ClickHouseSourceConfig
from .health import EngineHealthServer
from .models import ExecutionResult, TradingSignal
from .risk import RiskConfig, RiskGuard
from .state_store import EngineStateStore, SignalStatus

logger = logging.getLogger("binance_toolkit.engine")


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


class ExecutionAdapter(Protocol):
    """Protocol for execution adapters (futures/spot)."""

    def execute(self, signal: TradingSignal) -> ExecutionResult:
        ...

    def query_order(self, *, symbol: str, order_id: int | None, client_order_id: str | None) -> dict:
        ...


class BaseStrategyEngine(ABC):
    """Abstract base class for strategy engines.
    
    Subclasses must implement:
        - _market_name: property returning the market identifier
        - _create_trade_client: method to create the trade WS client
        - _create_executor: method to create the execution adapter
        - _get_kafka_topic: method to get the Kafka topic for trade results
    """

    def __init__(
        self,
        app_config: BinanceConfig,
        *,
        dry_run: bool = False,
        state_db_suffix: str = "",
    ):
        self._app_config = app_config
        self._dry_run = dry_run

        # Build state db path with optional suffix for market separation
        state_db_path = app_config.engine_state_db_path
        if state_db_suffix:
            # Insert suffix before .db extension
            if state_db_path.endswith(".db"):
                state_db_path = state_db_path[:-3] + f"_{state_db_suffix}.db"
            else:
                state_db_path = f"{state_db_path}_{state_db_suffix}"

        source_cfg = ClickHouseSourceConfig(
            url=app_config.clickhouse_signal_url or "",
            database=app_config.clickhouse_database,
            table=app_config.clickhouse_signal_table,
            user=app_config.clickhouse_user,
            password=app_config.clickhouse_password,
            where_clause=app_config.clickhouse_signal_where,
            market=self._market_name,  # Filter by market type
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
        self._state = EngineStateStore(state_db_path)
        self._risk = RiskGuard(risk_cfg)
        self._kafka: KafkaStorage | None = None
        self._audit: EngineAuditLogger | None = None
        if app_config.kafka_bootstrap_servers:
            self._kafka = KafkaStorage(app_config)
            self._audit = EngineAuditLogger(self._kafka, self._get_audit_topic())

        # Create market-specific trade client and executor
        self._trade_client = None if dry_run else self._create_trade_client()
        self._executor: ExecutionAdapter = self._create_executor()

        # Health server with market-specific port offset to avoid conflicts
        health_port = self._get_health_port(app_config.engine_health_port)
        self._health = EngineHealthServer(
            app_config.engine_health_host,
            health_port,
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

    @property
    @abstractmethod
    def _market_name(self) -> str:
        """Return the market name for signal filtering (e.g., 'spot', 'futures')."""
        ...

    @abstractmethod
    def _create_trade_client(self) -> Any:
        """Create and return the market-specific trade WS client."""
        ...

    @abstractmethod
    def _create_executor(self) -> ExecutionAdapter:
        """Create and return the market-specific execution adapter."""
        ...

    @abstractmethod
    def _get_kafka_topic(self) -> str:
        """Return the Kafka topic for trade results."""
        ...

    def _get_audit_topic(self) -> str:
        """Return the Kafka topic for engine audit events. Can be overridden."""
        return self._app_config.kafka_topic_engine_events

    def _get_health_port(self, base_port: int) -> int:
        """Return the health server port with market-specific offset.
        
        To allow running multiple engines simultaneously without port conflicts:
        - futures: base_port (e.g., 8088)
        - spot: base_port + 1 (e.g., 8089)
        - Other markets: base_port + 2, 3, ...
        
        If base_port is 0 (disabled), returns 0.
        """
        if base_port == 0:
            return 0
        
        market_offsets = {
            "futures": 0,
            "spot": 1,
        }
        offset = market_offsets.get(self._market_name, 2)
        return base_port + offset

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        cursor = self._init_cursor()
        self._health.start()
        logger.info("%sStrategyEngine started, cursor=%s", self._market_name.capitalize(), cursor)
        self._emit_engine_event(
            "engine_started",
            payload={
                "cursor_ms": cursor,
                "dry_run": self._dry_run,
                "market": self._market_name,
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
                    payload={"error": str(exc), "market": self._market_name},
                    metrics=self._metrics,
                )
                logger.exception("engine loop error")

            if not self._stop:
                time.sleep(self._engine_cfg.poll_interval_sec)

        logger.info("%sStrategyEngine stopped metrics=%s", self._market_name.capitalize(), self._metrics)
        self._emit_engine_event(
            "engine_stopped",
            payload={"cursor_ms": cursor, "market": self._market_name},
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
            "market": self._market_name,
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
                        "market": self._market_name,
                    },
                    metrics=self._metrics,
                )
            except Exception as exc:
                self._emit_engine_event(
                    "signal_reconcile_failed",
                    payload={
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "error": str(exc),
                        "market": self._market_name,
                    },
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
        merged_payload = {"market": self._market_name}
        if payload:
            merged_payload.update(payload)
        self._audit.emit(
            event_type,
            signal_item=signal_item,
            status=status,
            reason=reason,
            metrics=self._metrics,
            payload=merged_payload,
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
