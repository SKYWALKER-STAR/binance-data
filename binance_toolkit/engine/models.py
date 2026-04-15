"""Data models for strategy signals and execution results."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

_FINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}
_SUPPORTED_ACTIONS = {"PLACE_ORDER", "CANCEL_ORDER", "CANCEL_ALL_ORDERS"}


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip() == "":
        return default
    return int(value)


def _to_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


@dataclass(frozen=True)
class TradingSignal:
    """Normalized signal pulled from ClickHouse."""

    signal_id: str
    strategy_id: str
    symbol: str
    action: str
    signal_ts_ms: int
    ttl_ms: int
    priority: int

    side: str | None = None
    order_type: str | None = None
    quantity: str | None = None
    price: str | None = None
    time_in_force: str | None = None
    position_side: str | None = None
    reduce_only: str | None = None
    close_position: str | None = None
    order_id: int | None = None
    orig_client_order_id: str | None = None

    @property
    def expires_at_ms(self) -> int:
        if self.ttl_ms <= 0:
            return 2**63 - 1
        return self.signal_ts_ms + self.ttl_ms

    @property
    def is_final_candidate(self) -> bool:
        return self.action in _SUPPORTED_ACTIONS

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "TradingSignal":
        signal_id = _to_str(row.get("signal_id"))
        if not signal_id:
            raise ValueError("signal_id 不能为空")

        action = _to_str(row.get("action")).upper()
        if action == "CANCEL_ALL":
            action = "CANCEL_ALL_ORDERS"
        if action not in _SUPPORTED_ACTIONS:
            raise ValueError(f"不支持的 action: {action}")

        symbol = _to_str(row.get("symbol")).upper()
        if not symbol:
            raise ValueError("symbol 不能为空")

        return cls(
            signal_id=signal_id,
            strategy_id=_to_str(row.get("strategy_id"), "default"),
            symbol=symbol,
            action=action,
            signal_ts_ms=_to_int(row.get("signal_ts_ms")),
            ttl_ms=_to_int(row.get("ttl_ms"), 0),
            priority=_to_int(row.get("priority"), 0),
            side=_to_str(row.get("side")).upper() or None,
            order_type=_to_str(row.get("order_type")).upper() or None,
            quantity=_to_str(row.get("quantity")) or None,
            price=_to_str(row.get("price")) or None,
            time_in_force=_to_str(row.get("time_in_force")).upper() or None,
            position_side=_to_str(row.get("position_side")).upper() or None,
            reduce_only=_to_str(row.get("reduce_only")).lower() or None,
            close_position=_to_str(row.get("close_position")).lower() or None,
            order_id=_to_int(row.get("order_id"), 0) or None,
            orig_client_order_id=_to_str(row.get("orig_client_order_id")) or None,
        )

    def deterministic_client_order_id(self) -> str:
        """Build a deterministic clientOrderId for idempotent re-send."""
        short = hashlib.sha1(self.signal_id.encode("utf-8")).hexdigest()[:22]
        if self.action == "PLACE_ORDER":
            prefix = "so"
        elif self.action == "CANCEL_ORDER":
            prefix = "sc"
        else:
            prefix = "sa"
        strategy = hashlib.sha1(self.strategy_id.encode("utf-8")).hexdigest()[:8]
        return f"{prefix}{strategy}{short}"[:36]


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome returned by executor for one signal."""

    signal_id: str
    status: str
    message: str
    order_id: int | None = None
    client_order_id: str | None = None

    @property
    def is_final(self) -> bool:
        return self.status.upper() in _FINAL_ORDER_STATUSES
