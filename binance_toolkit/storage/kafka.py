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

    def close(self) -> None:
        self._producer.close()
        logger.info("Kafka Producer 已关闭")

    def __enter__(self) -> "KafkaStorage":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
