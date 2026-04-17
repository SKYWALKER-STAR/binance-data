"""Durable engine state store backed by SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import TradingSignal
logger = logging.getLogger("binance_toolkit.engine")


class SignalStatus:
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    SENT = "SENT"
    ACKED = "ACKED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED_BY_EXCHANGE = "REJECTED_BY_EXCHANGE"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


_FINAL_STATUSES = {
    SignalStatus.REJECTED,
    SignalStatus.FILLED,
    SignalStatus.CANCELED,
    SignalStatus.REJECTED_BY_EXCHANGE,
    SignalStatus.EXPIRED,
}


class EngineStateStore:
    """Keep idempotency and recovery states in a local sqlite db."""

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_signal_status(self, signal_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT status FROM signal_state WHERE signal_id = ?", (signal_id,)).fetchone()
        return str(row["status"]) if row else None

    def is_final(self, signal_id: str) -> bool:
        status = self.get_signal_status(signal_id)
        return status in _FINAL_STATUSES if status else False

    def save_received(self, signal: TradingSignal, *, raw_row: dict[str, Any] | None = None) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO signal_state (
                    signal_id, strategy_id, symbol, action, signal_ts_ms, status,
                    reason, order_id, client_order_id, updated_at_ms, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    signal.signal_id,
                    signal.strategy_id,
                    signal.symbol,
                    signal.action,
                    signal.signal_ts_ms,
                    SignalStatus.RECEIVED,
                    "received",
                    None,
                    None,
                    now_ms,
                    json.dumps(raw_row or {}, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def update_status(
        self,
        signal_id: str,
        *,
        status: str,
        reason: str,
        order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                """
                UPDATE signal_state
                SET status = ?, reason = ?, order_id = COALESCE(?, order_id),
                    client_order_id = COALESCE(?, client_order_id),
                    updated_at_ms = ?
                WHERE signal_id = ?
                """,
                (status, reason, order_id, client_order_id, now_ms, signal_id),
            )
            self._conn.commit()

    def get_cursor_ms(self) -> int | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM engine_kv WHERE key = 'cursor_ms'").fetchone()
        if not row:
            return None
        return int(row["value"])

    def set_cursor_ms(self, cursor_ms: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO engine_kv (key, value)
                VALUES ('cursor_ms', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(cursor_ms),),
            )
            self._conn.commit()

    def list_reconcile_candidates(self, *, older_than_ms: int, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT signal_id, symbol, action, order_id, client_order_id, status, updated_at_ms
                FROM signal_state
                WHERE status IN (?, ?, ?)
                  AND updated_at_ms <= ?
                ORDER BY updated_at_ms ASC
                LIMIT ?
                """,
                (SignalStatus.SENT, SignalStatus.ACKED, SignalStatus.FAILED, older_than_ms, limit),
            ).fetchall()
        for r in rows:
            logger.debug("[reconcile] found candidate: signal_id=%s, symbol=%s, action=%s, order_id=%s, client_order_id=%s, status=%s, updated_at_ms=%s",
                r["signal_id"], r["symbol"], r["action"], r["order_id"], r["client_order_id"], r["status"], r["updated_at_ms"])
        return [dict(r) for r in rows]

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_state (
                    signal_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    signal_ts_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    order_id INTEGER,
                    client_order_id TEXT,
                    updated_at_ms INTEGER NOT NULL,
                    raw_json TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS engine_kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._conn.commit()
