"""Execution adapter for USDT futures and spot markets."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ..ws.futures_trade_ws import FuturesTradeWsClient
from ..ws.spot_trade_ws import SpotTradeWsClient
from .models import ExecutionResult, TradingSignal

log = logging.getLogger("binance_toolkit.engine.executor")


@dataclass(frozen=True)
class ExecutionConfig:
    dry_run: bool = False


class FuturesExecutionAdapter:
    """Map normalized signals to futures ws client calls."""

    def __init__(self, client: Optional[FuturesTradeWsClient], config: ExecutionConfig):
        self._client = client
        self._config = config

    def execute(self, signal: TradingSignal) -> ExecutionResult:
        if self._config.dry_run:
            return ExecutionResult(
                signal_id=signal.signal_id,
                status="ACKED",
                message="dry-run accepted",
                client_order_id=signal.deterministic_client_order_id(),
            )

        if self._client is None:
            raise RuntimeError("execution client is not initialized")

        if signal.action == "PLACE_ORDER":
            result = self._client.new_order(
                symbol=signal.symbol,
                side=signal.side or "",
                order_type=signal.order_type or "",
                position_side=signal.position_side,
                time_in_force=signal.time_in_force,
                quantity=signal.quantity,
                price=signal.price,
                reduce_only=signal.reduce_only,
                close_position=signal.close_position,
                new_client_order_id=signal.deterministic_client_order_id(),
                new_order_resp_type="RESULT",
            )
            log.debug("orderID=%s", result.get("orderId"))
            return ExecutionResult(
                signal_id=signal.signal_id,
                status=str(result.get("status", "ACKED")),
                message="order placed",
                order_id=result.get("orderId"),
                client_order_id=result.get("clientOrderId") or signal.deterministic_client_order_id(),
            )

        if signal.action == "CANCEL_ORDER":
            result = self._client.cancel_order(
                symbol=signal.symbol,
                order_id=signal.order_id,
                orig_client_order_id=signal.orig_client_order_id,
            )
            return ExecutionResult(
                signal_id=signal.signal_id,
                status=str(result.get("status", "CANCELED")),
                message="order canceled",
                order_id=result.get("orderId") or signal.order_id,
                client_order_id=result.get("clientOrderId") or signal.orig_client_order_id,
            )

        if signal.action == "CANCEL_ALL_ORDERS":
            result = self._client.cancel_all_orders(symbol=signal.symbol)
            return ExecutionResult(
                signal_id=signal.signal_id,
                status="CANCELED",
                message=f"cancel all processed count={len(result)}",
            )

        raise ValueError(f"unsupported action: {signal.action}")

    def query_order(self, *, symbol: str, order_id: int | None, client_order_id: str | None) -> dict:
        if self._config.dry_run:
            return {"status": "ACK"}
        if self._client is None:
            raise RuntimeError("execution client is not initialized")
        return self._client.query_order(
            symbol=symbol,
            order_id=order_id,
            orig_client_order_id=client_order_id,
        )


class SpotExecutionAdapter:
    """Map normalized signals to spot ws client calls."""

    def __init__(self, client: Optional[SpotTradeWsClient], config: ExecutionConfig):
        self._client = client
        self._config = config

    def execute(self, signal: TradingSignal) -> ExecutionResult:
        if self._config.dry_run:
            return ExecutionResult(
                signal_id=signal.signal_id,
                status="ACKED",
                message="dry-run accepted",
                client_order_id=signal.deterministic_client_order_id(),
            )

        if self._client is None:
            raise RuntimeError("execution client is not initialized")

        if signal.action == "PLACE_ORDER":
            result = self._client.new_order(
                symbol=signal.symbol,
                side=signal.side or "",
                order_type=signal.order_type or "",
                time_in_force=signal.time_in_force,
                quantity=signal.quantity,
                price=signal.price,
                new_client_order_id=signal.deterministic_client_order_id(),
                new_order_resp_type="RESULT",
            )
            log.debug("orderID=%s", result.get("orderId"))
            return ExecutionResult(
                signal_id=signal.signal_id,
                status=str(result.get("status", "ACKED")),
                message="order placed",
                order_id=result.get("orderId"),
                client_order_id=result.get("clientOrderId") or signal.deterministic_client_order_id(),
            )

        if signal.action == "CANCEL_ORDER":
            result = self._client.cancel_order(
                symbol=signal.symbol,
                order_id=signal.order_id,
                orig_client_order_id=signal.orig_client_order_id,
            )
            return ExecutionResult(
                signal_id=signal.signal_id,
                status=str(result.get("status", "CANCELED")),
                message="order canceled",
                order_id=result.get("orderId") or signal.order_id,
                client_order_id=result.get("clientOrderId") or signal.orig_client_order_id,
            )

        if signal.action == "CANCEL_ALL_ORDERS":
            result = self._client.cancel_all_orders(symbol=signal.symbol)
            return ExecutionResult(
                signal_id=signal.signal_id,
                status="CANCELED",
                message=f"cancel all processed count={len(result)}",
            )

        raise ValueError(f"unsupported action: {signal.action}")

    def query_order(self, *, symbol: str, order_id: int | None, client_order_id: str | None) -> dict:
        if self._config.dry_run:
            return {"status": "ACK"}
        if self._client is None:
            raise RuntimeError("execution client is not initialized")
        return self._client.query_order(
            symbol=symbol,
            order_id=order_id,
            orig_client_order_id=client_order_id,
        )
