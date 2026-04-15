"""Pre-trade risk checks for strategy engine."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from .models import TradingSignal


@dataclass(frozen=True)
class RiskConfig:
    max_notional_per_order: float = 0.0
    max_actions_per_minute_per_symbol: int = 0


class RiskGuard:
    """Stateful risk guard for signal admission."""

    def __init__(self, config: RiskConfig):
        self._config = config
        self._symbol_action_ts: dict[str, deque[int]] = defaultdict(deque)

    def check(self, signal: TradingSignal, *, now_ms: int | None = None) -> tuple[bool, str]:
        now = now_ms if now_ms is not None else int(time.time() * 1000)

        if now > signal.expires_at_ms:
            return False, "signal expired"

        if signal.action == "PLACE_ORDER":
            if not signal.side:
                return False, "missing side"
            if signal.side not in {"BUY", "SELL"}:
                return False, "invalid side"
            if not signal.order_type:
                return False, "missing order_type"

            qty = self._parse_positive_float(signal.quantity)
            if qty <= 0:
                return False, "invalid quantity"

            if self._config.max_notional_per_order > 0:
                px = self._parse_positive_float(signal.price)
                if px <= 0:
                    return False, "missing price for notional risk"
                notional = qty * px
                if notional > self._config.max_notional_per_order:
                    return False, "order notional exceeds limit"

        if signal.action == "CANCEL_ORDER":
            if signal.order_id is None and not signal.orig_client_order_id:
                return False, "cancel requires order_id or orig_client_order_id"

        if signal.action == "CANCEL_ALL_ORDERS":
            if not signal.symbol:
                return False, "cancel all requires symbol"

        if not self._check_rate_limit(signal, now_ms=now):
            return False, "symbol action rate limit exceeded"

        return True, "ok"

    def _check_rate_limit(self, signal: TradingSignal, *, now_ms: int) -> bool:
        limit = self._config.max_actions_per_minute_per_symbol
        if limit <= 0:
            return True

        q = self._symbol_action_ts[signal.symbol]
        window_start = now_ms - 60_000
        while q and q[0] < window_start:
            q.popleft()

        if len(q) >= limit:
            return False

        q.append(now_ms)
        return True

    @staticmethod
    def _parse_positive_float(value: str | None) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
