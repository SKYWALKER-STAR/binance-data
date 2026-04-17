"""Kafka 存储后端.

将采集到的数据发布到 Kafka Topic（使用 kafka-python 库）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
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

    def write_kline_batch(self, records: list[dict[str, Any]], topic: str) -> None:
        """批量发布 K线数据到 Kafka Topic.

        每条消息以 symbol 作为消息 Key，value 为 JSON 格式的 K线数据。

        Args:
            records: K线记录列表，每个元素包含:
                - symbol:                  合约交易对
                - interval:                K线间隔 (1d / 1h 等)
                - open_time:               K线开始时间 (ms)
                - close_time:              K线结束时间 (ms)
                - open:                    开盘价 (字符串)
                - high:                    最高价 (字符串)
                - low:                     最低价 (字符串)
                - close:                   收盘价 (字符串)
                - volume:                  成交量 (字符串)
                - quote_volume:            成交额 (字符串)
                - trade_count:             成交笔数
                - taker_buy_volume:        主动买入成交量 (字符串)
                - taker_buy_quote_volume:  主动买入成交额 (字符串)
                - is_closed:               是否已收盘
                - event_time:              事件时间 (ms)
                - timestamp:               ISO8601 时间字符串
            topic: 目标 Kafka Topic 名称
        """
        if not records:
            return

        for r in records:
            self._producer.send(topic, key=r["symbol"], value=r)

        self._producer.flush()
        logger.debug("批量发布 %d 条 K线到 Topic [%s] 成功", len(records), topic)

    def write_oi_batch(self, records: list[dict[str, Any]], topic: str) -> None:
        """批量发布持仓量统计数据到 Kafka Topic.

        每条消息以 symbol 作为消息 Key，value 为 JSON 格式的 OI 数据。

        Args:
            records: OI 记录列表，每个元素包含:
                - symbol:                  合约交易对
                - period:                  统计周期 (1h / 1d 等)
                - sum_open_interest:       持仓量 (合约张数, 字符串)
                - sum_open_interest_value: 持仓量价值 (USDT, 字符串)
                - timestamp:               时间戳 (ms)
                - timestamp_iso:           ISO8601 时间字符串
            topic: 目标 Kafka Topic 名称
        """
        if not records:
            return

        for r in records:
            self._producer.send(topic, key=r["symbol"], value=r)

        self._producer.flush()
        logger.debug("批量发布 %d 条 OI 统计到 Topic [%s] 成功", len(records), topic)

    def write_record(self, record: dict[str, Any], *, topic: str, key: str | None = None) -> None:
        """发布一条通用 JSON 记录到 Kafka Topic."""
        self._producer.send(topic, key=key, value=record)
        self._producer.flush()
        logger.debug("发布记录到 Topic [%s] 成功 key=%s", topic, key)

    def write_engine_event(self, event: dict[str, Any], *, topic: str, key: str | None = None) -> None:
        """发布策略引擎审计事件到 Kafka Topic."""
        self.write_record(event, topic=topic, key=key)

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
        topic_prefix: str = "binance.account.snapshot",
    ) -> None:
        """将账户每日快照展平后逐行发布到对应 Kafka Topic.

        与 ClickHouse 的 Kafka 引擎表对应（JSONEachRow，每行一条余额/持仓记录）：
          {prefix}.spot             → SPOT 余额（每行一个资产）
          {prefix}.margin           → MARGIN 资产（每行一个资产）
          {prefix}.futures.asset    → FUTURES 账户资产（每行一个资产）
          {prefix}.futures.position → FUTURES 持仓（每行一个合约，仅非零持仓）

        Args:
            snapshots:     snapshotVos 列表，来自 daily_snapshot() 的原始返回。
            topic_prefix:  Topic 前缀，默认 "binance.account.snapshot"。
        """
        if not snapshots:
            return

        total = 0
        for snap in snapshots:
            acct_type: str = snap.get("type", "").lower()
            update_time: int = snap.get("updateTime", 0)
            data: dict = snap.get("data", {})
            snapshot_date = (
                datetime.fromtimestamp(update_time / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                if update_time else ""
            )
            common = {"snapshot_date": snapshot_date, "update_time": update_time}

            if acct_type == "spot":
                topic = f"{topic_prefix}.spot"
                summary = {
                    "total_asset_of_btc": data.get("totalAssetOfBtc", "0"),
                }
                for b in data.get("balances", []):
                    record = {
                        **common,
                        **summary,
                        "asset":  b.get("asset", ""),
                        "free":   b.get("free", "0"),
                        "locked": b.get("locked", "0"),
                    }
                    self._producer.send(topic, key=f"spot:{update_time}:{b.get('asset','')}", value=record)
                    total += 1

            elif acct_type == "margin":
                topic = f"{topic_prefix}.margin"
                summary = {
                    "margin_level":            data.get("marginLevel", "0"),
                    "total_asset_of_btc":      data.get("totalAssetOfBtc", "0"),
                    "total_liability_of_btc":  data.get("totalLiabilityOfBtc", "0"),
                    "total_net_asset_of_btc":  data.get("totalNetAssetOfBtc", "0"),
                }
                for a in data.get("userAssets", []):
                    record = {
                        **common,
                        **summary,
                        "asset":     a.get("asset", ""),
                        "free":      a.get("free", "0"),
                        "locked":    a.get("locked", "0"),
                        "borrowed":  a.get("borrowed", "0"),
                        "interest":  a.get("interest", "0"),
                        "net_asset": a.get("netAsset", "0"),
                    }
                    self._producer.send(topic, key=f"margin:{update_time}:{a.get('asset','')}", value=record)
                    total += 1

            elif acct_type == "futures":
                # 账户资产
                asset_topic = f"{topic_prefix}.futures.asset"
                for a in data.get("assets", []):
                    record = {
                        **common,
                        "asset":          a.get("asset", ""),
                        "wallet_balance":  a.get("walletBalance", "0"),
                        "margin_balance":  a.get("marginBalance", "0"),
                    }
                    self._producer.send(asset_topic, key=f"futures:asset:{update_time}:{a.get('asset','')}", value=record)
                    total += 1
                # 持仓（仅推送非零持仓）
                pos_topic = f"{topic_prefix}.futures.position"
                for p in data.get("position", []):
                    if float(p.get("positionAmt", 0)) == 0:
                        continue
                    record = {
                        **common,
                        "symbol":           p.get("symbol", ""),
                        "entry_price":      p.get("entryPrice", "0"),
                        "mark_price":       p.get("markPrice", "0"),
                        "position_amt":     p.get("positionAmt", "0"),
                        "unrealized_profit": p.get("unRealizedProfit", "0"),
                    }
                    self._producer.send(pos_topic, key=f"futures:pos:{update_time}:{p.get('symbol','')}", value=record)
                    total += 1

        self._producer.flush()
        logger.debug("发布 %d 条账户快照行到 Topic 前缀 [%s]", total, topic_prefix)

    def write_futures_trade(
        self,
        result: dict[str, Any],
        *,
        action: str,
        sent_at: datetime,
        filled_at: "datetime | None",
        topic: str = "binance.trade.usdt_futures",
    ) -> None:
        """发布单笔 U 本位合约交易结果到 Kafka Topic.

        每条消息以 ``symbol`` 作为 Key，包含完整的订单快照及时间戳。

        Args:
            result:    Binance WebSocket API 返回的 ``result`` 字典。
            action:    操作类型，``"new_order"`` / ``"modify_order"`` /
                       ``"cancel_order"`` / ``"query_order"``。
            sent_at:   交易发起时间（本地记录的 UTC datetime）。
            filled_at: 交易成交/更新时间（来自响应 updateTime，可为 None）。
            topic:     目标 Kafka Topic，默认 ``"binance.trade.usdt_futures"``。
        """
        symbol: str = result.get("symbol", "UNKNOWN")
        record: dict[str, Any] = {
            "action":                     action,
            "order_id":                   result.get("orderId"),
            "client_order_id":            result.get("clientOrderId"),
            "symbol":                     symbol,
            "side":                       result.get("side"),
            "position_side":              result.get("positionSide"),
            "type":                       result.get("type") or result.get("origType"),
            "time_in_force":              result.get("timeInForce"),
            "quantity":                   result.get("origQty"),
            "price":                      result.get("price"),
            "avg_price":                  result.get("avgPrice"),
            "stop_price":                 result.get("stopPrice"),
            "executed_qty":               result.get("executedQty"),
            "cum_quote":                  result.get("cumQuote"),
            "status":                     result.get("status"),
            "reduce_only":                result.get("reduceOnly"),
            "close_position":             result.get("closePosition"),
            "working_type":               result.get("workingType"),
            "price_protect":              result.get("priceProtect"),
            "price_match":                result.get("priceMatch"),
            "self_trade_prevention_mode": result.get("selfTradePreventionMode"),
            "good_till_date":             result.get("goodTillDate"),
            "activate_price":             result.get("activatePrice"),
            "price_rate":                 result.get("priceRate"),
            # 时间字段
            "sent_at":     sent_at.isoformat(),
            "filled_at":   filled_at.isoformat() if filled_at else None,
            "update_time": result.get("updateTime") or result.get("time"),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._producer.send(topic, key=symbol, value=record)
        self._producer.flush()
        logger.debug("发布 [%s] 交易结果到 Topic [%s]: orderId=%s status=%s",
                     action, topic, record["order_id"], record["status"])

    def write_spot_trade(
        self,
        result: dict[str, Any],
        *,
        action: str,
        sent_at: datetime,
        transact_at: "datetime | None",
        topic: str = "binance.trade.spot",
    ) -> None:
        """发布单笔现货交易结果到 Kafka Topic.

        每条消息以 ``symbol`` 作为 Key，包含完整的订单快照及时间戳。

        Args:
            result:      Binance WebSocket API 返回的 ``result`` 字典。
            action:      操作类型，``"new_order"`` / ``"cancel_order"`` /
                         ``"query_order"`` / ``"cancel_all_orders"``。
            sent_at:     交易发起时间（本地记录的 UTC datetime）。
            transact_at: 交易成交/更新时间（来自响应 transactTime，可为 None）。
            topic:       目标 Kafka Topic，默认 ``"binance.trade.spot"``。
        """
        symbol: str = result.get("symbol", "UNKNOWN")

        # 处理成交明细 fills（如有）
        fills: list[dict] = result.get("fills", [])
        fills_json: str | None = None
        if fills:
            import json
            fills_json = json.dumps(fills, ensure_ascii=False)

        record: dict[str, Any] = {
            "action":                     action,
            "order_id":                   result.get("orderId"),
            "order_list_id":              result.get("orderListId"),
            "client_order_id":            result.get("clientOrderId"),
            "orig_client_order_id":       result.get("origClientOrderId"),
            "symbol":                     symbol,
            "side":                       result.get("side"),
            "type":                       result.get("type"),
            "time_in_force":              result.get("timeInForce"),
            "quantity":                   result.get("origQty"),
            "quote_order_qty":            result.get("origQuoteOrderQty"),
            "price":                      result.get("price"),
            "stop_price":                 result.get("stopPrice"),
            "trailing_delta":             result.get("trailingDelta"),
            "trailing_time":              result.get("trailingTime"),
            "iceberg_qty":                result.get("icebergQty"),
            "executed_qty":               result.get("executedQty"),
            "cummulative_quote_qty":      result.get("cummulativeQuoteQty"),
            "status":                     result.get("status"),
            "working_time":               result.get("workingTime"),
            "self_trade_prevention_mode": result.get("selfTradePreventionMode"),
            "prevented_match_id":         result.get("preventedMatchId"),
            "prevented_quantity":         result.get("preventedQuantity"),
            "strategy_id":                result.get("strategyId"),
            "strategy_type":              result.get("strategyType"),
            "fills":                      fills_json,
            # 时间字段
            "sent_at":       sent_at.isoformat(),
            "transact_at":   transact_at.isoformat() if transact_at else None,
            "transact_time": result.get("transactTime") or result.get("time"),
            "recorded_at":   datetime.now(timezone.utc).isoformat(),
        }
        self._producer.send(topic, key=symbol, value=record)
        self._producer.flush()
        logger.debug("发布 [%s] 现货交易结果到 Topic [%s]: orderId=%s status=%s",
                     action, topic, record["order_id"], record["status"])

    def write_futures_position(
        self,
        positions: list[dict[str, Any]],
        *,
        queried_at: datetime,
        topic: str = "binance.position.usdt_futures",
    ) -> None:
        """发布 U 本位合约持仓信息到 Kafka Topic.

        每条消息以 ``symbol:positionSide`` 作为 Key，包含完整的持仓快照。

        Args:
            positions: Binance WebSocket API 返回的持仓信息列表（仅有效持仓）。
            queried_at: 查询发起时间（本地记录的 UTC datetime）。
            topic:     目标 Kafka Topic，默认 ``"binance.position.usdt_futures"``。
        """
        if not positions:
            return

        for pos in positions:
            symbol: str = pos.get("symbol", "UNKNOWN")
            position_side: str = pos.get("positionSide", "BOTH")

            # 计算更新时间
            update_time_ms: int | None = pos.get("updateTime")
            updated_at: datetime | None = None
            if update_time_ms:
                updated_at = datetime.fromtimestamp(update_time_ms / 1000, tz=timezone.utc)

            record: dict[str, Any] = {
                "symbol":                  symbol,
                "position_side":           position_side,
                "position_amt":            pos.get("positionAmt"),
                "entry_price":             pos.get("entryPrice"),
                "break_even_price":        pos.get("breakEvenPrice"),
                "mark_price":              pos.get("markPrice"),
                "unrealized_profit":       pos.get("unRealizedProfit"),
                "liquidation_price":       pos.get("liquidationPrice"),
                "isolated_margin":         pos.get("isolatedMargin"),
                "notional":                pos.get("notional"),
                "margin_asset":            pos.get("marginAsset"),
                "isolated_wallet":         pos.get("isolatedWallet"),
                "initial_margin":          pos.get("initialMargin"),
                "maint_margin":            pos.get("maintMargin"),
                "position_initial_margin": pos.get("positionInitialMargin"),
                "open_order_initial_margin": pos.get("openOrderInitialMargin"),
                "adl":                     pos.get("adl"),
                "bid_notional":            pos.get("bidNotional"),
                "ask_notional":            pos.get("askNotional"),
                # 时间字段
                "update_time":             update_time_ms,
                "updated_at":              updated_at.isoformat() if updated_at else None,
                "queried_at":              queried_at.isoformat(),
                "recorded_at":             datetime.now(timezone.utc).isoformat(),
            }

            key = f"{symbol}:{position_side}"
            self._producer.send(topic, key=key, value=record)

        self._producer.flush()
        logger.debug("发布 %d 条持仓信息到 Topic [%s]", len(positions), topic)

    def close(self) -> None:
        self._producer.close()
        logger.info("Kafka Producer 已关闭")

    def __enter__(self) -> "KafkaStorage":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
