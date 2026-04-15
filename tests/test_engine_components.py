"""Strategy engine component tests."""

from __future__ import annotations

import socket
import time
import urllib.request
import json

from binance_toolkit.engine.health import EngineHealthServer
from binance_toolkit.engine.models import TradingSignal
from binance_toolkit.engine.risk import RiskConfig, RiskGuard
from binance_toolkit.engine.state_store import EngineStateStore, SignalStatus


def test_signal_parse_and_client_order_id() -> None:
    row = {
        "signal_id": "sig-1",
        "strategy_id": "s1",
        "symbol": "btcusdt",
        "action": "place_order",
        "signal_ts_ms": 1700000000000,
        "ttl_ms": 1000,
        "priority": 1,
        "side": "buy",
        "order_type": "limit",
        "quantity": "0.01",
        "price": "60000",
    }
    signal = TradingSignal.from_row(row)
    assert signal.symbol == "BTCUSDT"
    assert signal.action == "PLACE_ORDER"

    cid = signal.deterministic_client_order_id()
    assert cid
    assert len(cid) <= 36


def test_risk_guard_ttl_and_rate_limit() -> None:
    now_ms = int(time.time() * 1000)
    guard = RiskGuard(RiskConfig(max_actions_per_minute_per_symbol=1))

    signal_ok = TradingSignal.from_row(
        {
            "signal_id": "sig-ok",
            "strategy_id": "s1",
            "symbol": "BTCUSDT",
            "action": "PLACE_ORDER",
            "signal_ts_ms": now_ms,
            "ttl_ms": 10_000,
            "priority": 1,
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "0.01",
            "price": "1000",
        }
    )

    ok, _ = guard.check(signal_ok, now_ms=now_ms)
    assert ok

    signal_rate_limited = TradingSignal.from_row(
        {
            "signal_id": "sig-rate",
            "strategy_id": "s1",
            "symbol": "BTCUSDT",
            "action": "CANCEL_ORDER",
            "signal_ts_ms": now_ms,
            "ttl_ms": 10_000,
            "priority": 1,
            "order_id": 123,
        }
    )
    ok2, reason2 = guard.check(signal_rate_limited, now_ms=now_ms)
    assert not ok2
    assert "rate limit" in reason2

    signal_expired = TradingSignal.from_row(
        {
            "signal_id": "sig-expired",
            "strategy_id": "s1",
            "symbol": "BTCUSDT",
            "action": "CANCEL_ORDER",
            "signal_ts_ms": now_ms - 10_000,
            "ttl_ms": 100,
            "priority": 1,
            "order_id": 100,
        }
    )
    ok3, reason3 = guard.check(signal_expired, now_ms=now_ms)
    assert not ok3
    assert reason3 == "signal expired"


def test_state_store_cursor_and_status(tmp_path) -> None:
    db_path = tmp_path / "engine.db"
    store = EngineStateStore(str(db_path))

    signal = TradingSignal.from_row(
        {
            "signal_id": "sig-2",
            "strategy_id": "s1",
            "symbol": "BTCUSDT",
            "action": "CANCEL_ORDER",
            "signal_ts_ms": 1700000000000,
            "ttl_ms": 1000,
            "priority": 1,
            "order_id": 1,
        }
    )

    store.save_received(signal)
    assert store.get_signal_status("sig-2") == SignalStatus.RECEIVED

    store.update_status("sig-2", status=SignalStatus.CANCELED, reason="ok", order_id=1)
    assert store.is_final("sig-2")

    store.set_cursor_ms(1700000000123)
    assert store.get_cursor_ms() == 1700000000123

    store.close()


def test_cancel_all_alias_is_normalized() -> None:
    signal = TradingSignal.from_row(
        {
            "signal_id": "sig-cancel-all",
            "strategy_id": "s1",
            "symbol": "BTCUSDT",
            "action": "cancel_all",
            "signal_ts_ms": 1700000000000,
            "ttl_ms": 1000,
            "priority": 1,
        }
    )
    assert signal.action == "CANCEL_ALL_ORDERS"


def test_health_server_exposes_health_and_metrics() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

    server = EngineHealthServer(
        host,
        port,
        lambda: {
            "status": "running",
            "metrics": {"pulled": 1, "accepted": 2},
        },
    )
    server.start()
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["status"] == "running"

        with urllib.request.urlopen(f"http://{host}:{port}/metrics", timeout=2) as resp:
            metrics_text = resp.read().decode("utf-8")
        assert "binance_engine_pulled 1" in metrics_text
        assert "binance_engine_accepted 2" in metrics_text
    finally:
        server.stop()
