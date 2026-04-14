"""现货 WebSocket 交易集成测试.

测试流程:
  1. 下限价单  (price 远低于市价, 不会真正成交)
  2. 查询该订单
  3. 撤销订单
  4. 撤销全部订单 (验证空订单情况)
  每步结果均写入 Kafka Topic: binance.trade.spot

运行前置条件:
  - config.json 中配置好 api_key / secret_key (现货交易权限)
  - config.json 中配置好 kafka_bootstrap_servers
  - Kafka 服务可访问

运行方式:
  cd /warehouse/GitRepos/biannce-api
  python -m tests.test_spot_trade

  或者直接运行:
  python tests/test_spot_trade.py
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
logger = logging.getLogger("test_spot_trade")

# ---------- 路径修正 ----------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from binance_toolkit.config import BinanceConfig
from binance_toolkit.exceptions import BinanceAPIError
from binance_toolkit.storage.kafka import KafkaStorage
from binance_toolkit.ws.spot_trade_ws import SpotTradeWsClient

# ─────────────────────────────────────────
# 测试参数（按需修改）
# ─────────────────────────────────────────
SYMBOL = "BTCUSDT"
SIDE = "BUY"
ORDER_TYPE = "LIMIT"
QUANTITY = "0.005"      # 最小下单量 (根据交易对调整)
PRICE = "74320"          # 远低于市价，不会成交
TIME_IN_FORCE = "GTC"

# 是否执行各测试步骤 (可单独开关)
ENABLE_NEW_ORDER = True
ENABLE_QUERY_ORDER = True
ENABLE_CANCEL_ORDER = True
ENABLE_CANCEL_ALL = False  # 慎用：会撤销该交易对所有挂单
# ─────────────────────────────────────────


def _print_order(label: str, result: dict) -> None:
    """格式化打印订单信息."""
    logger.info(
        "%-14s | orderId=%-12s status=%-12s price=%-12s qty=%-10s executedQty=%s",
        label,
        result.get("orderId", ""),
        result.get("status", ""),
        result.get("price", ""),
        result.get("origQty", ""),
        result.get("executedQty", ""),
    )


def _separator(title: str) -> None:
    logger.info("─" * 70)
    logger.info("  %s", title)
    logger.info("─" * 70)


def run_test() -> None:
    # 1. 加载配置
    config = BinanceConfig.from_json()
    logger.info("配置加载完毕:")
    logger.info("  base_url     = %s", config.base_url)
    logger.info("  spot_ws_url  = %s", config.spot_ws_url)
    logger.info("  kafka_topic  = %s", config.kafka_topic_spot_trade)

    # 2. 初始化 Kafka（写入交易结果）
    kafka: KafkaStorage | None = None
    if config.kafka_bootstrap_servers:
        kafka = KafkaStorage(config)
        logger.info("Kafka 连接成功: %s", config.kafka_bootstrap_servers)
    else:
        logger.warning("未配置 Kafka，交易结果不会写入 Kafka")

    order_id: int | None = None

    try:
        with SpotTradeWsClient(
            config,
            kafka_storage=kafka,
            kafka_topic=config.kafka_topic_spot_trade,
            request_timeout=15,
        ) as client:

            # ── Step 1: 下限价单 ────────────────────────────
            if ENABLE_NEW_ORDER:
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
                logger.info("✅ 下单成功，orderId=%s", order_id)

            # ── Step 2: 查询订单 ────────────────────────────
            if ENABLE_QUERY_ORDER and order_id:
                _separator("Step 2: 查询订单")
                status = client.query_order(symbol=SYMBOL, order_id=order_id)
                _print_order("query_order", status)
                logger.info("✅ 查询成功，当前状态=%s", status.get("status"))

            # ── Step 3: 撤销订单 ────────────────────────────
            if ENABLE_CANCEL_ORDER and order_id:
                _separator("Step 3: 撤销订单")
                cancel = client.cancel_order(symbol=SYMBOL, order_id=order_id)
                _print_order("cancel_order", cancel)
                logger.info("✅ 撤单成功，状态=%s", cancel.get("status"))
                order_id = None  # 已撤销，无需再次清理

            # ── Step 4: 撤销全部订单 ────────────────────────
            if ENABLE_CANCEL_ALL:
                _separator("Step 4: 撤销全部订单")
                results = client.cancel_all_orders(symbol=SYMBOL)
                logger.info("✅ 撤销全部订单完成，共 %d 个", len(results))
                for r in results:
                    _print_order("cancel_all", r)

            _separator("测试完成")
            logger.info("🎉 所有测试步骤执行成功！")

    except BinanceAPIError as exc:
        logger.error("❌ Binance API 错误: code=%s  msg=%s", exc.error_code, exc)
        # 若下单成功但后续步骤失败，尝试撤单避免挂单留存
        if order_id is not None:
            _try_cancel(kafka, config, order_id)
        raise

    except Exception as exc:
        logger.error("❌ 未预期异常: %s", exc)
        if order_id is not None:
            _try_cancel(kafka, config, order_id)
        raise

    finally:
        if kafka:
            kafka.close()
            logger.info("Kafka 已关闭")
        logger.info("测试结束")


def _try_cancel(kafka: KafkaStorage | None, config: BinanceConfig, order_id: int) -> None:
    """异常发生时尝试撤销残留挂单."""
    logger.warning("⚠️ 尝试撤销残留挂单 orderId=%s ...", order_id)
    try:
        with SpotTradeWsClient(
            config,
            kafka_storage=kafka,
            kafka_topic=config.kafka_topic_spot_trade,
        ) as c:
            result = c.cancel_order(symbol=SYMBOL, order_id=order_id)
            logger.info("撤单成功: status=%s", result.get("status"))
    except Exception as e:
        logger.error("撤单失败: %s", e)


def test_market_order() -> None:
    """测试市价单（小额测试，会真正成交！）.
    
    ⚠️ 警告：此测试会真正执行交易，请确保:
      1. 账户有足够余额
      2. 使用极小金额测试
    """
    config = BinanceConfig.from_json()
    kafka = KafkaStorage(config) if config.kafka_bootstrap_servers else None

    try:
        with SpotTradeWsClient(config, kafka_storage=kafka) as client:
            _separator("市价单测试 (quoteOrderQty)")
            # 用 11 USDT 买入 BTC（最小金额，实际成交）
            order = client.new_order(
                symbol="BTCUSDT",
                side="BUY",
                order_type="MARKET",
                quote_order_qty="11",  # 用 11 USDT 买入
            )
            _print_order("market_order", order)
            logger.info("✅ 市价单成功，成交量=%s，成交金额=%s",
                        order.get("executedQty"), order.get("cummulativeQuoteQty"))
    finally:
        if kafka:
            kafka.close()


def test_stop_loss_limit() -> None:
    """测试止损限价单."""
    config = BinanceConfig.from_json()
    kafka = KafkaStorage(config) if config.kafka_bootstrap_servers else None

    try:
        with SpotTradeWsClient(config, kafka_storage=kafka) as client:
            _separator("止损限价单测试")
            # 当价格跌至 55000 时，以 54900 的限价卖出
            order = client.new_order(
                symbol="BTCUSDT",
                side="SELL",
                order_type="STOP_LOSS_LIMIT",
                quantity="0.0001",
                price="54900",
                stop_price="55000",
                time_in_force="GTC",
            )
            _print_order("stop_loss_limit", order)
            order_id = order["orderId"]
            logger.info("✅ 止损限价单创建成功")

            # 撤销测试订单
            cancel = client.cancel_order(symbol="BTCUSDT", order_id=order_id)
            logger.info("✅ 已撤销止损单，status=%s", cancel.get("status"))
    finally:
        if kafka:
            kafka.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="现货 WebSocket 交易测试")
    parser.add_argument(
        "--test",
        choices=["basic", "market", "stop_loss"],
        default="basic",
        help="测试类型: basic=基础流程, market=市价单(会成交!), stop_loss=止损限价单",
    )
    args = parser.parse_args()

    if args.test == "basic":
        run_test()
    elif args.test == "market":
        logger.warning("⚠️ 市价单测试会真正成交，按 Ctrl+C 取消...")
        input("按 Enter 确认执行...")
        test_market_order()
    elif args.test == "stop_loss":
        test_stop_loss_limit()
