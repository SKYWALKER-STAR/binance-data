"""合约未实现盈亏计算模块.

通过 WebSocket 实时获取 mark price，计算合约持仓的未实现盈亏。

用法:
    python -m binance_toolkit futures-pnl
"""

from __future__ import annotations

import json
import logging
import signal
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

import websocket

if TYPE_CHECKING:
    from ..config import BinanceConfig
    from ..storage.kafka import KafkaStorage

logger = logging.getLogger("binance_toolkit.pnl")

# WebSocket 基础地址
FAPI_WS_BASE_URL = "wss://fstream.binance.com/ws"  # USDT 本位
DAPI_WS_BASE_URL = "wss://dstream.binance.com/ws"  # 币本位

# 默认交易手续费率
DEFAULT_FEE_RATE = 0.0004  # 0.04% (Maker: 0.02%, Taker: 0.04%)


class PositionSide(Enum):
    """持仓方向."""
    
    LONG = "LONG"
    SHORT = "SHORT"


class MarginType(Enum):
    """保证金类型."""
    
    USDT = "USDT"  # USDT 本位
    COIN = "COIN"  # 币本位


@dataclass
class FuturesPosition:
    """合约持仓信息."""
    
    symbol: str  # 交易对，如 BTCUSDT 或 BTCUSD_PERP
    side: PositionSide  # 多/空
    entry_price: float = 0.0  # 开仓均价
    quantity: float = 0.0  # 持仓数量 (合约张数或币数量)
    leverage: int = 1  # 杠杆倍数
    margin_type: MarginType = MarginType.USDT  # 保证金类型
    fee_rate: float = DEFAULT_FEE_RATE  # 手续费率
    order_id: str = "TEST_ORDER_001"  # 关联订单ID (实验阶段固定值)
    
    # 实时数据 (由计算器更新)
    mark_price: float = field(default=0.0, repr=False)
    index_price: float = field(default=0.0, repr=False)
    funding_rate: float = field(default=0.0, repr=False)
    last_update: datetime | None = field(default=None, repr=False)
    
    @property
    def side_sign(self) -> int:
        """方向符号: 多头 +1, 空头 -1."""
        return 1 if self.side == PositionSide.LONG else -1
    
    @property
    def side_str(self) -> str:
        """方向字符串."""
        return "多" if self.side == PositionSide.LONG else "空"
    
    @property
    def notional_value(self) -> float:
        """名义价值 (开仓时)."""
        return self.entry_price * self.quantity
    
    @property
    def current_notional(self) -> float:
        """当前名义价值."""
        return self.mark_price * self.quantity
    
    @property
    def margin(self) -> float:
        """保证金 (初始保证金)."""
        return self.notional_value / self.leverage
    
    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏.
        
        多头: (当前价格 - 开仓价格) × 数量
        空头: (开仓价格 - 当前价格) × 数量
        """
        if self.mark_price <= 0:
            return 0.0
        
        price_diff = self.mark_price - self.entry_price
        return price_diff * self.quantity * self.side_sign
    
    @property
    def unrealized_pnl_with_fee(self) -> float:
        """未实现盈亏 (含开平仓手续费估算).
        
        手续费 = 开仓名义价值 × 费率 + 平仓名义价值 × 费率
        """
        if self.mark_price <= 0:
            return 0.0
        
        open_fee = self.notional_value * self.fee_rate
        close_fee = self.current_notional * self.fee_rate
        return self.unrealized_pnl - open_fee - close_fee
    
    @property
    def unrealized_pnl_pct(self) -> float:
        """未实现盈亏百分比 (相对于保证金)."""
        if self.margin <= 0:
            return 0.0
        return (self.unrealized_pnl / self.margin) * 100
    
    @property
    def roe(self) -> float:
        """ROE (收益率，相对于保证金，含手续费)."""
        if self.margin <= 0:
            return 0.0
        return (self.unrealized_pnl_with_fee / self.margin) * 100
    
    @property
    def price_change_pct(self) -> float:
        """价格涨跌幅百分比."""
        if self.entry_price <= 0:
            return 0.0
        return ((self.mark_price - self.entry_price) / self.entry_price) * 100
    
    @property
    def liquidation_price_estimate(self) -> float:
        """估算强平价格 (简化计算，不考虑维持保证金率).
        
        多头: 开仓价 × (1 - 1/杠杆)
        空头: 开仓价 × (1 + 1/杠杆)
        """
        if self.leverage <= 0:
            return 0.0
        
        if self.side == PositionSide.LONG:
            return self.entry_price * (1 - 1 / self.leverage)
        else:
            return self.entry_price * (1 + 1 / self.leverage)


class FuturesPnLCalculator:
    """合约未实现盈亏计算器.
    
    通过 WebSocket 订阅 markPrice 流，实时计算合约持仓的未实现盈亏。
    
    用法:
        positions = [
            FuturesPosition("BTCUSDT", PositionSide.LONG, entry_price=60000, quantity=0.1, leverage=10),
            FuturesPosition("ETHUSDT", PositionSide.SHORT, entry_price=3000, quantity=1.0, leverage=5),
        ]
        calculator = FuturesPnLCalculator(positions)
        calculator.run()  # 阻塞运行，Ctrl+C 停止
    """
    
    def __init__(
        self,
        positions: list[FuturesPosition],
        *,
        update_speed: str = "1s",
        print_interval: float = 1.0,
        config: "BinanceConfig | None" = None,
        write_kafka: bool = False,
        kafka_topic: str = "binance.pnl.futures",
        enable_print: bool = True,
    ):
        """
        Args:
            positions:      持仓列表。
            update_speed:   WebSocket 更新速度，"1s" 或 "3s"。
            print_interval: 打印间隔秒数。
            config:         配置对象 (写 Kafka 时需要)。
            write_kafka:    是否写入 Kafka。
            kafka_topic:    Kafka Topic 名称。
            enable_print:   是否打印到控制台。
        """
        self._positions = {p.symbol: p for p in positions}
        self._update_speed = update_speed
        self._print_interval = print_interval
        self._enable_print = enable_print
        
        # Kafka 配置
        self._write_kafka = write_kafka
        self._kafka_topic = kafka_topic
        self._kafka: "KafkaStorage | None" = None
        if write_kafka and config:
            from ..storage.kafka import KafkaStorage
            self._kafka = KafkaStorage(config)
        
        self._stop_event = threading.Event()
        self._ws_usdt: websocket.WebSocketApp | None = None
        self._ws_coin: websocket.WebSocketApp | None = None
        self._last_print_time = 0.0
        self._last_kafka_time = 0.0
        
        # 按保证金类型分组
        self._usdt_symbols = [
            s for s, p in self._positions.items() 
            if p.margin_type == MarginType.USDT
        ]
        self._coin_symbols = [
            s for s, p in self._positions.items() 
            if p.margin_type == MarginType.COIN
        ]
    
    def _build_stream_url(self, symbols: list[str], base_url: str) -> str:
        """构建 WebSocket 订阅 URL."""
        suffix = "" if self._update_speed == "3s" else "@1s"
        streams = [f"{s.lower()}@markPrice{suffix}" for s in symbols]
        return f"{base_url}/{'/'.join(streams)}"
    
    def _on_ws_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket 消息回调."""
        try:
            data = json.loads(message)
            
            # 处理数组或单条消息
            items = data if isinstance(data, list) else [data]
            
            for item in items:
                symbol = item.get("s", "")
                mark_price_str = item.get("p", "")  # mark price
                index_price_str = item.get("i", "")  # index price
                funding_rate_str = item.get("r", "")  # funding rate
                
                if symbol in self._positions and mark_price_str:
                    position = self._positions[symbol]
                    position.mark_price = float(mark_price_str)
                    if index_price_str:
                        position.index_price = float(index_price_str)
                    if funding_rate_str:
                        position.funding_rate = float(funding_rate_str)
                    position.last_update = datetime.now(timezone.utc)
            
            # 周期性打印
            now = datetime.now(timezone.utc).timestamp()
            if now - self._last_print_time >= self._print_interval:
                if self._enable_print:
                    self._print_pnl()
                self._last_print_time = now
            
            # 周期性写入 Kafka
            if self._write_kafka and self._kafka:
                if now - self._last_kafka_time >= self._print_interval:
                    self._write_to_kafka()
                    self._last_kafka_time = now
                
        except json.JSONDecodeError:
            logger.warning("无法解析 WebSocket 消息: %s", message[:200])
        except Exception:
            logger.exception("处理 WebSocket 消息时出错")
    
    def _print_pnl(self) -> None:
        """打印盈亏信息."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n{'='*100}")
        print(f"[{now_str}] 合约未实现盈亏 (手续费: {DEFAULT_FEE_RATE*100:.2f}%)")
        print(f"{'='*100}")
        print(
            f"{'合约':<14} {'方向':>4} {'杠杆':>4} {'开仓价':>12} {'标记价':>12} "
            f"{'数量':>10} {'保证金':>10} {'未实盈亏':>12} {'ROE':>8} {'资金费率':>10}"
        )
        print(f"{'-'*100}")
        
        total_margin = 0.0
        total_pnl = 0.0
        total_pnl_with_fee = 0.0
        
        for symbol, pos in self._positions.items():
            if pos.mark_price > 0:
                pnl_color = "\033[32m" if pos.unrealized_pnl >= 0 else "\033[31m"
                roe_color = "\033[32m" if pos.roe >= 0 else "\033[31m"
                reset_color = "\033[0m"
                
                # 资金费率着色 (多头时正费率不利，空头时负费率不利)
                funding_unfavorable = (
                    (pos.side == PositionSide.LONG and pos.funding_rate > 0) or
                    (pos.side == PositionSide.SHORT and pos.funding_rate < 0)
                )
                funding_color = "\033[31m" if funding_unfavorable else "\033[32m"
                
                print(
                    f"{pos.symbol:<14} "
                    f"{pos.side_str:>4} "
                    f"{pos.leverage:>3}x "
                    f"{pos.entry_price:>12.2f} "
                    f"{pos.mark_price:>12.2f} "
                    f"{pos.quantity:>10.4f} "
                    f"{pos.margin:>10.2f} "
                    f"{pnl_color}{pos.unrealized_pnl:>+12.2f}{reset_color} "
                    f"{roe_color}{pos.roe:>+7.2f}%{reset_color} "
                    f"{funding_color}{pos.funding_rate*100:>+9.4f}%{reset_color}"
                )
                
                total_margin += pos.margin
                total_pnl += pos.unrealized_pnl
                total_pnl_with_fee += pos.unrealized_pnl_with_fee
        
        print(f"{'-'*100}")
        
        total_roe = (total_pnl_with_fee / total_margin * 100) if total_margin > 0 else 0.0
        pnl_color = "\033[32m" if total_pnl >= 0 else "\033[31m"
        roe_color = "\033[32m" if total_roe >= 0 else "\033[31m"
        reset_color = "\033[0m"
        
        print(
            f"{'合计':<14} "
            f"{'':>4} "
            f"{'':>4} "
            f"{'':>12} "
            f"{'':>12} "
            f"{'':>10} "
            f"{total_margin:>10.2f} "
            f"{pnl_color}{total_pnl:>+12.2f}{reset_color} "
            f"{roe_color}{total_roe:>+7.2f}%{reset_color} "
            f"{'':>10}"
        )
        
        # 额外显示含手续费的盈亏
        print(f"\n含手续费估算: {pnl_color}{total_pnl_with_fee:>+.2f} USDT{reset_color}")
    
    def _write_to_kafka(self) -> None:
        """写入 PnL 数据到 Kafka."""
        if not self._kafka:
            return
        
        now = datetime.now(timezone.utc)
        records = []
        
        for symbol, pos in self._positions.items():
            if pos.mark_price > 0:
                records.append({
                    "symbol": pos.symbol,
                    "order_id": pos.order_id,
                    "side": pos.side.value,
                    "margin_type": pos.margin_type.value,
                    "leverage": pos.leverage,
                    "entry_price": pos.entry_price,
                    "mark_price": pos.mark_price,
                    "index_price": pos.index_price,
                    "quantity": pos.quantity,
                    "margin": pos.margin,
                    "notional_value": pos.notional_value,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "unrealized_pnl_with_fee": pos.unrealized_pnl_with_fee,
                    "roe": pos.roe,
                    "funding_rate": pos.funding_rate,
                    "fee_rate": pos.fee_rate,
                    "timestamp": now,
                })
        
        if records:
            self._kafka.write_futures_pnl(records, topic=self._kafka_topic)
    
    def _on_ws_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """WebSocket 错误回调."""
        logger.error("WebSocket 错误: %s", error)
    
    def _on_ws_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """WebSocket 关闭回调."""
        logger.info("WebSocket 连接关闭: code=%s, msg=%s", close_status_code, close_msg)
    
    def _on_ws_open(self, ws: websocket.WebSocketApp) -> None:
        """WebSocket 连接建立回调."""
        logger.info("WebSocket 连接已建立，开始接收价格数据...")
    
    def _signal_handler(self, signum: int, frame: Any) -> None:
        """信号处理."""
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在关闭...", sig_name)
        self.stop()
    
    def stop(self) -> None:
        """停止计算器."""
        self._stop_event.set()
        if self._ws_usdt:
            self._ws_usdt.close()
        if self._ws_coin:
            self._ws_coin.close()
        if self._kafka:
            self._kafka.close()
    
    def _run_ws(self, symbols: list[str], base_url: str, name: str) -> None:
        """运行单个 WebSocket 连接."""
        if not symbols:
            return
        
        url = self._build_stream_url(symbols, base_url)
        logger.info("[%s] 连接 WebSocket: %s", name, url)
        
        ws = websocket.WebSocketApp(
            url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )
        
        if name == "USDT":
            self._ws_usdt = ws
        else:
            self._ws_coin = ws
        
        while not self._stop_event.is_set():
            try:
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                logger.exception("[%s] WebSocket 运行异常", name)
            
            if not self._stop_event.is_set():
                logger.info("[%s] WebSocket 断开，5 秒后重连...", name)
                self._stop_event.wait(5)
    
    def run(self) -> None:
        """启动盈亏计算 (阻塞)."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 打印初始持仓信息
        print("\n合约持仓列表:")
        for symbol, pos in self._positions.items():
            print(
                f"  {pos.symbol}: {pos.side_str} {pos.leverage}x, "
                f"开仓价 {pos.entry_price:.2f}, 数量 {pos.quantity:.4f}"
            )
        
        print(f"\n订阅合约: {', '.join(self._positions.keys())}")
        
        threads = []
        
        # USDT 本位合约
        if self._usdt_symbols:
            t = threading.Thread(
                target=self._run_ws,
                args=(self._usdt_symbols, FAPI_WS_BASE_URL, "USDT"),
                daemon=True,
            )
            t.start()
            threads.append(t)
        
        # 币本位合约
        if self._coin_symbols:
            t = threading.Thread(
                target=self._run_ws,
                args=(self._coin_symbols, DAPI_WS_BASE_URL, "COIN"),
                daemon=True,
            )
            t.start()
            threads.append(t)
        
        # 等待停止信号
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(1)
        except KeyboardInterrupt:
            pass
        
        self.stop()
        
        for t in threads:
            t.join(timeout=2)
        
        logger.info("合约盈亏计算器已停止")


def parse_futures_positions(positions_str: str, fee_rate: float = DEFAULT_FEE_RATE) -> list[FuturesPosition]:
    """解析持仓字符串.
    
    格式: SYMBOL:SIDE:ENTRY_PRICE:QUANTITY:LEVERAGE[:MARGIN_TYPE]
    示例: BTCUSDT:LONG:60000:0.1:10,ETHUSDT:SHORT:3000:1.0:5
    
    Args:
        positions_str: 持仓字符串，逗号分隔。
        fee_rate:      手续费率。
    
    Returns:
        持仓列表。
    """
    positions = []
    
    for item in positions_str.split(","):
        parts = item.strip().split(":")
        if len(parts) < 5:
            logger.warning("无效的持仓格式: %s (需要至少 5 个部分)", item)
            continue
        
        symbol = parts[0].upper()
        side_str = parts[1].upper()
        entry_price = float(parts[2])
        quantity = float(parts[3])
        leverage = int(parts[4])
        margin_type_str = parts[5].upper() if len(parts) > 5 else "USDT"
        
        try:
            side = PositionSide[side_str]
        except KeyError:
            logger.warning("无效的方向: %s (需要 LONG 或 SHORT)", side_str)
            continue
        
        try:
            margin_type = MarginType[margin_type_str]
        except KeyError:
            logger.warning("无效的保证金类型: %s (需要 USDT 或 COIN)", margin_type_str)
            margin_type = MarginType.USDT
        
        positions.append(
            FuturesPosition(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                leverage=leverage,
                margin_type=margin_type,
                fee_rate=fee_rate,
            )
        )
    
    return positions


def run_futures_pnl(
    positions: list[FuturesPosition] | None = None,
    update_speed: str = "1s",
    print_interval: float = 1.0,
    config: "BinanceConfig | None" = None,
    write_kafka: bool = False,
    kafka_topic: str = "binance.pnl.futures",
    enable_print: bool = True,
) -> None:
    """便捷函数: 启动合约盈亏计算.
    
    Args:
        positions:      持仓列表，如果为 None 则使用示例持仓。
        update_speed:   更新速度 "1s" 或 "3s"。
        print_interval: 打印间隔秒数。
        config:         配置对象 (写 Kafka 时需要)。
        write_kafka:    是否写入 Kafka。
        kafka_topic:    Kafka Topic 名称。
        enable_print:   是否打印到控制台。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # 如果没有提供持仓，使用示例数据
    if positions is None:
        positions = [
            # 示例持仓 - 请根据实际情况修改
            FuturesPosition(
                symbol="BTCUSDT",
                side=PositionSide.LONG,
                entry_price=60000.0,
                quantity=0.1,
                leverage=10,
            ),
            FuturesPosition(
                symbol="ETHUSDT",
                side=PositionSide.SHORT,
                entry_price=3000.0,
                quantity=1.0,
                leverage=5,
            ),
        ]
        logger.info("使用示例持仓数据，请使用 --positions 参数配置实际持仓")
    
    calculator = FuturesPnLCalculator(
        positions,
        update_speed=update_speed,
        print_interval=print_interval,
        config=config,
        write_kafka=write_kafka,
        kafka_topic=kafka_topic,
        enable_print=enable_print,
    )
    calculator.run()


if __name__ == "__main__":
    # 配置你的实际持仓
    MY_POSITIONS = [
        FuturesPosition(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=60000.0,
            quantity=0.1,
            leverage=10,
        ),
        FuturesPosition(
            symbol="ETHUSDT",
            side=PositionSide.SHORT,
            entry_price=3000.0,
            quantity=1.0,
            leverage=5,
        ),
        # 添加更多持仓...
    ]
    
    run_futures_pnl(MY_POSITIONS)
