"""Redis position state store.

Stores latest futures positions fetched from Binance WS API.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import BinanceConfig

logger = logging.getLogger("binance_toolkit.storage.redis")


class RedisPositionStore:
    """Persist futures position snapshots into Redis.

        Key layout (prefix=binance:position:usdt_futures):
            - {prefix}:raw:snapshot:all:v1        hash[field=symbol:side, value=json]
            - {prefix}:raw:index:positions:v1     set of symbol:side keys
            - {prefix}:raw:meta:v1                hash with last_sync_ts, position_count
    """

    def __init__(self, config: "BinanceConfig") -> None:
        if not config.redis_url:
            raise ValueError("Redis 配置不完整，需要设置 redis_url")

        try:
            import redis
        except ImportError as exc:
            raise ImportError(
                "缺少依赖 redis，请执行: pip install 'binance-toolkit[redis]'"
            ) from exc

        self._prefix = config.redis_position_key_prefix
        self._snapshot_key = f"{self._prefix}:raw:snapshot:all:v1"
        self._symbols_key = f"{self._prefix}:raw:index:positions:v1"
        self._meta_key = f"{self._prefix}:raw:meta:v1"
        self._redis = redis.Redis.from_url(config.redis_url, decode_responses=True)
        self._redis.ping()
        logger.info("RedisPositionStore 已连接: %s", config.redis_url)

    @staticmethod
    def _to_iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _position_id(position: dict[str, Any]) -> str:
        symbol = str(position.get("symbol", ""))
        side = str(position.get("positionSide", "BOTH"))
        return f"{symbol}:{side}"

    @staticmethod
    def _normalize_position(position: dict[str, Any], synced_at: str) -> dict[str, Any]:
        data = dict(position)
        data["synced_at"] = synced_at
        return data

    def write_positions(self, positions: list[dict[str, Any]]) -> int:
        """Upsert positions and remove stale keys not in latest snapshot.

        Returns:
            Number of positions in the latest snapshot.
        """
        synced_at = self._to_iso_now()
        payload: dict[str, str] = {}
        latest_ids: set[str] = set()

        for p in positions:
            pid = self._position_id(p)
            latest_ids.add(pid)
            payload[pid] = json.dumps(self._normalize_position(p, synced_at), ensure_ascii=False)

        pipe = self._redis.pipeline(transaction=True)

        # Read previous symbol ids before overwrite.
        existing_ids = set(self._redis.smembers(self._symbols_key))
        stale_ids = existing_ids - latest_ids

        if payload:
            pipe.hset(self._snapshot_key, mapping=payload)

        if stale_ids:
            pipe.hdel(self._snapshot_key, *list(stale_ids))
            pipe.srem(self._symbols_key, *list(stale_ids))

        if latest_ids:
            pipe.sadd(self._symbols_key, *list(latest_ids))

        pipe.hset(
            self._meta_key,
            mapping={
                "last_sync_ts": synced_at,
                "position_count": str(len(latest_ids)),
                "source": "binance_ws_api",
            },
        )
        pipe.execute()

        return len(latest_ids)

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception:
            logger.debug("关闭 Redis 连接时出现异常", exc_info=True)
