"""ClickHouse 直写存储模块 - 当前持仓全量替换."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger("binance_toolkit.storage.clickhouse")


class ClickHousePositionStorage:
    """直接通过 ClickHouse HTTP 接口写入当前持仓，实现 TRUNCATE + INSERT 的全量替换语义.

    每次调用 write_current_positions():
      1. TRUNCATE TABLE —— 清空表（含空仓情况）
      2. INSERT 活跃持仓（positionAmt != 0）——— 空仓时跳过 INSERT，表保持空

    不依赖 Kafka 管道，结果立即可查，无 merge 延迟。
    """

    def __init__(
        self,
        url: str,
        *,
        database: str = "default",
        table: str = "current_futures_position",
        user: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        if not url:
            raise ValueError(
                "ClickHouse URL 未配置，请在 config.json 中设置 clickhouse_signal_url"
            )
        self._url = url.rstrip("/")
        self._database = database
        self._table = table
        self._auth = (user, password or "") if user else None
        self._timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def write_current_positions(
        self,
        positions: list[dict[str, Any]],
        queried_at: datetime,
    ) -> None:
        """全量替换当前持仓：先清空表，再写入活跃持仓.

        Args:
            positions:  Binance 返回的持仓列表（全量，含 positionAmt=0）。
            queried_at: 查询时间（UTC）。
        """
        active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]

        # Step 1: 清空
        self._execute(f"TRUNCATE TABLE {self._table}")

        # Step 2: 写入活跃持仓
        if active:
            rows = [self._to_row(pos, queried_at) for pos in active]
            body = (
                f"INSERT INTO {self._table} FORMAT JSONEachRow\n"
                + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
            )
            self._execute(body)
            logger.info(
                "写入 %d 条活跃持仓到 ClickHouse %s (queried_at=%s)",
                len(active),
                self._table,
                queried_at.isoformat(),
            )
        else:
            logger.info(
                "当前无活跃持仓，已清空 ClickHouse %s (queried_at=%s)",
                self._table,
                queried_at.isoformat(),
            )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "ClickHousePositionStorage":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _to_row(self, pos: dict[str, Any], queried_at: datetime) -> dict[str, Any]:
        update_time_ms: int | None = pos.get("updateTime")
        updated_at: Optional[datetime] = None
        if update_time_ms:
            updated_at = datetime.fromtimestamp(update_time_ms / 1000, tz=timezone.utc)

        return {
            "symbol":                    pos.get("symbol", ""),
            "position_side":             pos.get("positionSide", "BOTH"),
            "position_amt":              pos.get("positionAmt", "0"),
            "entry_price":               pos.get("entryPrice", "0"),
            "break_even_price":          pos.get("breakEvenPrice", "0"),
            "mark_price":                pos.get("markPrice", "0"),
            "unrealized_profit":         pos.get("unRealizedProfit", "0"),
            "liquidation_price":         pos.get("liquidationPrice", "0"),
            "isolated_margin":           pos.get("isolatedMargin", "0"),
            "notional":                  pos.get("notional", "0"),
            "margin_asset":              pos.get("marginAsset", ""),
            "isolated_wallet":           pos.get("isolatedWallet", "0"),
            "initial_margin":            pos.get("initialMargin", "0"),
            "maint_margin":              pos.get("maintMargin", "0"),
            "position_initial_margin":   pos.get("positionInitialMargin", "0"),
            "open_order_initial_margin": pos.get("openOrderInitialMargin", "0"),
            "adl":                       pos.get("adl", 0),
            "bid_notional":              pos.get("bidNotional", "0"),
            "ask_notional":              pos.get("askNotional", "0"),
            "update_time":               update_time_ms or 0,
            "updated_at":                (
                updated_at.isoformat() if updated_at else queried_at.isoformat()
            ),
            "queried_at":                queried_at.isoformat(),
        }

    def _execute(self, sql: str) -> None:
        resp = self._session.post(
            self._url,
            params={"database": self._database},
            data=sql.encode("utf-8"),
            auth=self._auth,
            timeout=self._timeout,
        )
        resp.raise_for_status()
