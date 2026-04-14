"""U 本位合约 WebSocket 交易集成测试.

测试流程:
  1. 下限价单  (price 远低于市价, 不会真正成交)
  2. 查询该订单
  3. 修改订单价格
  4. 撤销订单
  每步结果均写入 Kafka Topic: binance.trade.usdt_futures

运行前置条件:
  - config.json 中配置好 api_key / secret_key (合约交易权限)
  - config.json 中配置好 kafka_bootstrap_servers
  - Kafka 服务可访问

运行方式:
  cd d:\\Data\\gitrepo\\binance-data
  python -m tests.test_futures_trade
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_futures_trade")

# ---------- 路径修正 ----------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binance_toolkit.config import BinanceConfig
from binance_toolkit.exceptions import BinanceAPIError
from binance_toolkit.storage.kafka import KafkaStorage
from binance_toolkit.ws.futures_trade_ws import FuturesTradeWsClient

# ─────────────────────────────────────────
# 测试参数（按需修改）
# ─────────────────────────────────────────
SYMBOL = "BTCUSDT"
SIDE = "BUY"
ORDER_TYPE = "LIMIT"
QUANTITY = "0.001"       # 最小下单量
PRICE = "10000"          # 远低于市价，不会成交
MODIFY_PRICE = "10100"   # 修改后的价格
TIME_IN_FORCE = "GTC"
# ─────────────────────────────────────────


def _print_order(label: str, result: dict) -> None:
    """格式化打印订单信息."""
    logger.info(
        "%-12s | orderId=%-12s status=%-10s price=%-12s avgPrice=%-12s executedQty=%s",
        label,
        result.get("orderId", ""),
        result.get("status", ""),
        result.get("price", ""),
        result.get("avgPrice", ""),
        result.get("executedQty", ""),
    )


def _separator(title: str) -> None:
    logger.info("─" * 60)
    logger.info("  %s", title)
    logger.info("─" * 60)


def run_test() -> None:
    # 1. 加载配置
    config = BinanceConfig.from_json()
    logger.info("配置加载完毕: base_url=%s  fapi_ws_url=%s", config.base_url, config.fapi_ws_url)

    # 2. 初始化 Kafka（写入交易结果）
    kafka = KafkaStorage(config)
    logger.info("Kafka 连接成功: %s  topic=%s",
                config.kafka_bootstrap_servers, config.kafka_topic_futures_trade)

    order_id: int | None = None

    try:
        with FuturesTradeWsClient(
            config,
            kafka_storage=kafka,
            kafka_topic=config.kafka_topic_futures_trade,
            request_timeout=15,
        ) as client:

            # ── Step 1: 下限价单 ────────────────────────────
            _separator("Step 1: 下限价单")
            order = client.new_order(
                symbol=SYMBOL,
                side=SIDE,
                order_type=ORDER_TYPE,
                quantity=QUANTITY,
                price=PRICE,
                time_in_force=TIME_IN_FORCE,
            )
            _print_order("new_order", order)
            order_id = order["orderId"]

            # ── Step 2: 查询订单 ────────────────────────────
            _separator("Step 2: 查询订单")
            status = client.query_order(symbol=SYMBOL, order_id=order_id)
            _print_order("query_order", status)

            # ── Step 3: 修改订单价格 ─────────────────────────
            _separator("Step 3: 修改订单价格")
            modified = client.modify_order(
                symbol=SYMBOL,
                side=SIDE,
                quantity=QUANTITY,
                price=MODIFY_PRICE,
                order_id=order_id,
            )
            _print_order("modify_order", modified)

            # ── Step 4: 再次查询确认修改 ─────────────────────
            _separator("Step 4: 再次查询确认修改")
            status2 = client.query_order(symbol=SYMBOL, order_id=order_id)
            _print_order("query_order", status2)

            # ── Step 5: 撤销订单 ────────────────────────────
            _separator("Step 5: 撤销订单")
            cancel = client.cancel_order(symbol=SYMBOL, order_id=order_id)
            _print_order("cancel_order", cancel)
            order_id = None  # 已撤销，无需再次清理

    except BinanceAPIError as exc:
        logger.error("Binance API 错误: code=%s  msg=%s", exc.error_code, exc)
        # 若下单成功但后续步骤失败，尝试撤单避免挂单留存
        if order_id is not None:
            _try_cancel(kafka, config, order_id)
        raise

    except Exception as exc:
        logger.error("未预期异常: %s", exc)
        if order_id is not None:
            _try_cancel(kafka, config, order_id)
        raise

    finally:
        kafka.close()
        logger.info("Kafka 已关闭，测试结束")


def _try_cancel(kafka: KafkaStorage, config: BinanceConfig, order_id: int) -> None:
    """异常发生时尝试撤销残留挂单."""
    logger.warning("尝试撤销残留挂单 orderId=%s ...", order_id)
    try:
        with FuturesTradeWsClient(config, kafka_storage=kafka,
                                   kafka_topic=config.kafka_topic_futures_trade) as c:
            result = c.cancel_order(symbol=SYMBOL, order_id=order_id)
            logger.info("撤单成功: status=%s", result.get("status"))
    except Exception as e:
        logger.error("撤单失败: %s", e)


if __name__ == "__main__":
    run_test()
