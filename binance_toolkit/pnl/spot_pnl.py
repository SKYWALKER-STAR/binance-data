"""现货未实现盈亏计算模块.

通过 WebSocket 实时获取 index 价格，计算现货持仓的未实现盈亏。

用法:
    python -m binance_toolkit spot-pnl
"""

from __future__ import annotations

import json
import logging
import signal
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import websocket

if TYPE_CHECKING:
    from ..config import BinanceConfig
    from ..storage.kafka import KafkaStorage

logger = logging.getLogger("binance_toolkit.pnl")

# U本位合约 WebSocket 基础地址 (用于获取 index 价格)
FAPI_WS_BASE_URL = "wss://fstream.binance.com/ws"

# 默认交易手续费率
DEFAULT_FEE_RATE = 0.0002  # 0.02%


@dataclass
class SpotPosition:
    """现货持仓信息."""
    
    symbol: str  # 交易对，如 BTC
    quote: str = "USDT"  # 计价货币
    buy_price: float = 0.0  # 买入均价
    quantity: float = 0.0  # 持有数量
    fee_rate: float = DEFAULT_FEE_RATE  # 手续费率
    order_id: str = "TEST_ORDER_001"  # 关联订单ID (实验阶段固定值)
    
    # 实时数据 (由计算器更新)
    current_price: float = field(default=0.0, repr=False)
    last_update: datetime | None = field(default=None, repr=False)
    
    @property
    def full_symbol(self) -> str:
        """完整交易对，如 BTCUSDT."""
        return f"{self.symbol}{self.quote}"
    
    @property
    def cost(self) -> float:
        """买入成本 (含手续费)."""
        raw_cost = self.buy_price * self.quantity
        fee = raw_cost * self.fee_rate
        return raw_cost + fee
    
    @property
    def current_value(self) -> float:
        """当前市值."""
        return self.current_price * self.quantity
    
    @property
    def sell_value(self) -> float:
        """卖出后实际到账 (扣除手续费)."""
        raw_value = self.current_value
        fee = raw_value * self.fee_rate
        return raw_value - fee
    
    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏 (含手续费)."""
        if self.current_price <= 0:
            return 0.0
        return self.sell_value - self.cost
    
    @property
    def unrealized_pnl_pct(self) -> float:
        """未实现盈亏百分比."""
        if self.cost <= 0:
            return 0.0
        return (self.unrealized_pnl / self.cost) * 100
    
    @property
    def price_change_pct(self) -> float:
        """价格涨跌幅百分比."""
        if self.buy_price <= 0:
            return 0.0
        return ((self.current_price - self.buy_price) / self.buy_price) * 100


class SpotPnLCalculator:
    """现货未实现盈亏计算器.
    
    通过 WebSocket 订阅 U 本位合约的 markPrice 流，
    使用其中的 index_price 作为现货参考价格。
    
    用法:
        positions = [
            SpotPosition("BTC", buy_price=60000, quantity=0.1),
            SpotPosition("ETH", buy_price=3000, quantity=1.5),
        ]
        calculator = SpotPnLCalculator(positions)
        calculator.run()  # 阻塞运行，Ctrl+C 停止
    """
    
    def __init__(
        self,
        positions: list[SpotPosition],
        *,
        update_speed: str = "1s",
        print_interval: float = 1.0,
        config: "BinanceConfig | None" = None,
        write_kafka: bool = False,
        kafka_topic: str = "binance.pnl.spot",
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
        self._positions = {p.full_symbol: p for p in positions}
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
        self._ws: websocket.WebSocketApp | None = None
        self._last_print_time = 0.0
        self._last_kafka_time = 0.0
        
        # 需要订阅的合约列表
        self._symbols = list(self._positions.keys())
    
    def _build_stream_url(self) -> str:
        """构建 WebSocket 订阅 URL."""
        suffix = "" if self._update_speed == "3s" else "@1s"
        streams = [f"{s.lower()}@markPrice{suffix}" for s in self._symbols]
        return f"{FAPI_WS_BASE_URL}/{'/'.join(streams)}"
    
    def _on_ws_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket 消息回调."""
        try:
            data = json.loads(message)
            
            # 处理数组或单条消息
            items = data if isinstance(data, list) else [data]
            
            for item in items:
                symbol = item.get("s", "")
                index_price_str = item.get("i", "")  # index price
                
                if symbol in self._positions and index_price_str:
                    position = self._positions[symbol]
                    position.current_price = float(index_price_str)
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
        
        print(f"\n{'='*80}")
        print(f"[{now_str}] 现货未实现盈亏 (手续费: {DEFAULT_FEE_RATE*100:.2f}%)")
        print(f"{'='*80}")
        print(f"{'币种':<10} {'买入价':>12} {'现价':>12} {'数量':>10} {'成本':>12} {'市值':>12} {'盈亏':>12} {'盈亏%':>8}")
        print(f"{'-'*80}")
        
        total_cost = 0.0
        total_value = 0.0
        total_pnl = 0.0
        
        for symbol, pos in self._positions.items():
            if pos.current_price > 0:
                pnl_color = "\033[32m" if pos.unrealized_pnl >= 0 else "\033[31m"
                reset_color = "\033[0m"
                
                print(
                    f"{pos.symbol:<10} "
                    f"{pos.buy_price:>12.2f} "
                    f"{pos.current_price:>12.2f} "
                    f"{pos.quantity:>10.4f} "
                    f"{pos.cost:>12.2f} "
                    f"{pos.sell_value:>12.2f} "
                    f"{pnl_color}{pos.unrealized_pnl:>+12.2f}{reset_color} "
                    f"{pnl_color}{pos.unrealized_pnl_pct:>+7.2f}%{reset_color}"
                )
                
                total_cost += pos.cost
                total_value += pos.sell_value
                total_pnl += pos.unrealized_pnl
        
        print(f"{'-'*80}")
        
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
        pnl_color = "\033[32m" if total_pnl >= 0 else "\033[31m"
        reset_color = "\033[0m"
        
        print(
            f"{'合计':<10} "
            f"{'':>12} "
            f"{'':>12} "
            f"{'':>10} "
            f"{total_cost:>12.2f} "
            f"{total_value:>12.2f} "
            f"{pnl_color}{total_pnl:>+12.2f}{reset_color} "
            f"{pnl_color}{total_pnl_pct:>+7.2f}%{reset_color}"
        )
    
    def _write_to_kafka(self) -> None:
        """写入 PnL 数据到 Kafka."""
        if not self._kafka:
            return
        
        now = datetime.now(timezone.utc)
        records = []
        
        for symbol, pos in self._positions.items():
            if pos.current_price > 0:
                records.append({
                    "symbol": pos.symbol,
                    "order_id": pos.order_id,
                    "buy_price": pos.buy_price,
                    "current_price": pos.current_price,
                    "quantity": pos.quantity,
                    "cost": pos.cost,
                    "current_value": pos.current_value,
                    "sell_value": pos.sell_value,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                    "fee_rate": pos.fee_rate,
                    "timestamp": now,
                })
        
        if records:
            self._kafka.write_spot_pnl(records, topic=self._kafka_topic)
    
    def _on_ws_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """WebSocket 错误回调."""
        logger.error("WebSocket 错误: %s", error)
    
    def _on_ws_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """WebSocket 关闭回调."""
        logger.info("WebSocket 连接关闭: code=%s, msg=%s", close_status_code, close_msg)
    
    def _on_ws_open(self, ws: websocket.WebSocketApp) -> None:
        """WebSocket 连接建立回调."""
        logger.info("WebSocket 连接已建立，开始接收价格数据...")
        print(f"\n订阅合约: {', '.join(self._symbols)}")
    
    def _signal_handler(self, signum: int, frame: Any) -> None:
        """信号处理."""
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在关闭...", sig_name)
        self.stop()
    
    def stop(self) -> None:
        """停止计算器."""
        self._stop_event.set()
        if self._ws:
            self._ws.close()
        if self._kafka:
            self._kafka.close()
    
    def run(self) -> None:
        """启动盈亏计算 (阻塞)."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        url = self._build_stream_url()
        logger.info("连接 WebSocket: %s", url)
        
        # 打印初始持仓信息
        print("\n持仓列表:")
        for symbol, pos in self._positions.items():
            print(f"  {pos.symbol}: 买入价 {pos.buy_price:.2f}, 数量 {pos.quantity:.4f}")
        
        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )
        
        while not self._stop_event.is_set():
            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                logger.exception("WebSocket 运行异常")
            
            if not self._stop_event.is_set():
                logger.info("WebSocket 断开，5 秒后重连...")
                self._stop_event.wait(5)
        
        logger.info("盈亏计算器已停止")


def run_spot_pnl(
    positions: list[SpotPosition] | None = None,
    update_speed: str = "1s",
    print_interval: float = 1.0,
    config: "BinanceConfig | None" = None,
    write_kafka: bool = False,
    kafka_topic: str = "binance.pnl.spot",
    enable_print: bool = True,
) -> None:
    """便捷函数: 启动现货盈亏计算.
    
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
            SpotPosition("BTC", buy_price=60000.0, quantity=0.1),
            SpotPosition("ETH", buy_price=3000.0, quantity=1.0),
        ]
        logger.info("使用示例持仓数据，请在代码中配置实际持仓")
    
    calculator = SpotPnLCalculator(
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
        SpotPosition("BTC", buy_price=60000.0, quantity=0.1),
        SpotPosition("ETH", buy_price=3000.0, quantity=1.0),
        # 添加更多持仓...
    ]
    
    run_spot_pnl(MY_POSITIONS)
