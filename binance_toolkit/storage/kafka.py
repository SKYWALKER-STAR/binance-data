"""Kafka 存储后端.

将采集到的数据发布到 Kafka Topic（使用 kafka-python 库）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import BinanceConfig

logger = logging.getLogger("binance_toolkit.storage")


class KafkaStorage:
    """Kafka 消息发布器.

    使用方式:
        storage = KafkaStorage(config)
        storage.write_mark_price_batch(points, topic="binance.mark_price.coin")
        storage.close()
    """

    def __init__(self, config: "BinanceConfig"):
        if not config.kafka_bootstrap_servers:
            raise ValueError(
                "Kafka 配置不完整, 需要设置 kafka_bootstrap_servers"
            )

        try:
            from kafka import KafkaProducer
        except ImportError as exc:
            raise ImportError(
                "缺少依赖 kafka-python, 请执行: pip install 'binance-toolkit[kafka]'"
            ) from exc

        self._producer = KafkaProducer(
            bootstrap_servers=config.kafka_bootstrap_servers.split(","),
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",
            retries=3,
            max_block_ms=10000,
        )
        logger.info("Kafka Producer 已连接: %s", config.kafka_bootstrap_servers)

    def write_mark_price_batch(self, points: list[dict[str, Any]], topic: str) -> None:
        """批量发布标记价格数据到 Kafka Topic.

        每条消息以合约 symbol 作为消息 Key，value 为 JSON 格式的标记价格数据。

        Args:
            points: 数据点列表，每个元素包含:
                - symbol:            合约交易对
                - mark_price:        标记价格
                - index_price:       指数价格
                - last_funding_rate: 资金费率 (可选)
                - next_funding_time: 下次资金费时间戳毫秒 (可选)
                - timestamp:         datetime 时间戳 (可选)
                - contract_type:     合约类型 "COIN" 或 "USDT" (可选)
            topic: 目标 Kafka Topic 名称
        """
        if not points:
            return

        for p in points:
            ts = p.get("timestamp")
            record: dict[str, Any] = {
                "symbol": p["symbol"],
                "mark_price": p["mark_price"],
                "index_price": p["index_price"],
                "contract_type": p.get("contract_type", "COIN"),
                "timestamp": ts.isoformat() if isinstance(ts, datetime) else ts,
            }
            if p.get("last_funding_rate") is not None:
                record["last_funding_rate"] = p["last_funding_rate"]
            if p.get("next_funding_time") is not None:
                record["next_funding_time"] = p["next_funding_time"]

            self._producer.send(topic, key=p["symbol"], value=record)

        # 等待所有消息发送完毕
        self._producer.flush()
        logger.debug("批量发布 %d 条标记价格到 Topic [%s] 成功", len(points), topic)

    def write_spot_pnl(self, records: list[dict[str, Any]], topic: str = "binance.pnl.spot") -> None:
        """发布现货 PnL 数据到 Kafka Topic.

        Args:
            records: PnL 记录列表，每个元素包含:
                - symbol:           交易对 (如 BTC)
                - order_id:         关联订单ID
                - buy_price:        买入均价
                - current_price:    当前价格
                - quantity:         持有数量
                - cost:             买入成本 (含手续费)
                - current_value:    当前市值
                - sell_value:       卖出后实际到账
                - unrealized_pnl:   未实现盈亏
                - unrealized_pnl_pct: 盈亏百分比
                - fee_rate:         手续费率
                - timestamp:        时间戳
            topic: 目标 Kafka Topic 名称
        """
        if not records:
            return

        for r in records:
            ts = r.get("timestamp")
            record: dict[str, Any] = {
                "symbol": r["symbol"],
                "order_id": r.get("order_id", "UNKNOWN"),
                "buy_price": r["buy_price"],
                "current_price": r["current_price"],
                "quantity": r["quantity"],
                "cost": r["cost"],
                "current_value": r["current_value"],
                "sell_value": r["sell_value"],
                "unrealized_pnl": r["unrealized_pnl"],
                "unrealized_pnl_pct": r["unrealized_pnl_pct"],
                "fee_rate": r.get("fee_rate", 0.0002),
                "timestamp": ts.isoformat() if isinstance(ts, datetime) else ts,
            }

            self._producer.send(topic, key=r["symbol"], value=record)

        self._producer.flush()
        logger.debug("发布 %d 条现货 PnL 到 Topic [%s]", len(records), topic)

    def write_futures_pnl(self, records: list[dict[str, Any]], topic: str = "binance.pnl.futures") -> None:
        """发布合约 PnL 数据到 Kafka Topic.

        Args:
            records: PnL 记录列表，每个元素包含:
                - symbol:              合约交易对 (如 BTCUSDT)
                - order_id:            关联订单ID
                - side:                方向 (LONG/SHORT)
                - margin_type:         保证金类型 (USDT/COIN)
                - leverage:            杠杆倍数
                - entry_price:         开仓均价
                - mark_price:          标记价格
                - index_price:         指数价格
                - quantity:            持仓数量
                - margin:              保证金
                - notional_value:      名义价值
                - unrealized_pnl:      未实现盈亏
                - unrealized_pnl_with_fee: 含手续费盈亏
                - roe:                 ROE 百分比
                - funding_rate:        资金费率
                - fee_rate:            手续费率
                - timestamp:           时间戳
            topic: 目标 Kafka Topic 名称
        """
        if not records:
            return

        for r in records:
            ts = r.get("timestamp")
            record: dict[str, Any] = {
                "symbol": r["symbol"],
                "order_id": r.get("order_id", "UNKNOWN"),
                "side": r["side"],
                "margin_type": r.get("margin_type", "USDT"),
                "leverage": r["leverage"],
                "entry_price": r["entry_price"],
                "mark_price": r["mark_price"],
                "index_price": r.get("index_price", 0.0),
                "quantity": r["quantity"],
                "margin": r["margin"],
                "notional_value": r["notional_value"],
                "unrealized_pnl": r["unrealized_pnl"],
                "unrealized_pnl_with_fee": r.get("unrealized_pnl_with_fee", r["unrealized_pnl"]),
                "roe": r["roe"],
                "funding_rate": r.get("funding_rate", 0.0),
                "fee_rate": r.get("fee_rate", 0.0004),
                "timestamp": ts.isoformat() if isinstance(ts, datetime) else ts,
            }

            self._producer.send(topic, key=r["symbol"], value=record)

        self._producer.flush()
        logger.debug("发布 %d 条合约 PnL 到 Topic [%s]", len(records), topic)

    def write_account_snapshot(
        self,
        snapshots: list[dict[str, Any]],
        topic: str = "binance.account.snapshot",
    ) -> None:
        """发布账户每日快照数据到 Kafka Topic.

        每条消息以 "{type}:{updateTime}" 作为消息 Key，value 为 JSON 格式的快照数据。
        下游 ClickHouse 可通过 Kafka 引擎表消费并按账户类型写入对应分区。

        Args:
            snapshots: snapshotVos 列表，API 原始返回，每个元素含:
                - type:       账户类型 ("spot" / "margin" / "futures")
                - updateTime: 快照时间戳（毫秒）
                - data:       账户数据（结构因类型而异）
            topic: 目标 Kafka Topic，默认 "binance.account.snapshot"。
        """
        if not snapshots:
            return

        for snap in snapshots:
            acct_type = snap.get("type", "unknown")
            update_time = snap.get("updateTime", 0)
            ts_iso = datetime.fromtimestamp(update_time / 1000).isoformat() if update_time else None
            record: dict[str, Any] = {
                "type": acct_type,
                "updateTime": update_time,
                "timestamp": ts_iso,
                "data": snap.get("data", {}),
            }
            key = f"{acct_type}:{update_time}"
            self._producer.send(topic, key=key, value=record)

        self._producer.flush()
        logger.debug("发布 %d 条账户快照到 Topic [%s]", len(snapshots), topic)

    def close(self) -> None:
        self._producer.close()
        logger.info("Kafka Producer 已关闭")

    def __enter__(self) -> "KafkaStorage":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
