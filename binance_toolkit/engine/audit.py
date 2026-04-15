"""Kafka audit publishing for strategy engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..storage.kafka import KafkaStorage
from .models import TradingSignal


class EngineAuditLogger:
    """Publish engine audit events to Kafka."""

    def __init__(self, storage: KafkaStorage, topic: str):
        self._storage = storage
        self._topic = topic

    def emit(
        self,
        event_type: str,
        *,
        signal_item: TradingSignal | None = None,
        status: str | None = None,
        reason: str | None = None,
        metrics: dict[str, int] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "event_type": event_type,
            "status": status,
            "reason": reason,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if signal_item is not None:
            record.update(
                {
                    "signal_id": signal_item.signal_id,
                    "strategy_id": signal_item.strategy_id,
                    "symbol": signal_item.symbol,
                    "action": signal_item.action,
                    "signal_ts_ms": signal_item.signal_ts_ms,
                    "priority": signal_item.priority,
                }
            )
        if metrics is not None:
            record["metrics"] = dict(metrics)
        if payload:
            record.update(payload)

        key = signal_item.signal_id if signal_item is not None else event_type
        self._storage.write_engine_event(record, topic=self._topic, key=key)
