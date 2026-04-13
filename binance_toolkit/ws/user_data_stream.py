"""用户数据流 WebSocket 模块.

通过 WebSocket 实时接收用户账户更新、余额变动、订单状态等事件。

用法:
    python -m binance_toolkit user-data-stream
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

import websocket

if TYPE_CHECKING:
    from ..config import BinanceConfig

logger = logging.getLogger("binance_toolkit.ws")

# 现货 WebSocket 基础地址
SPOT_WS_BASE_URL = "wss://stream.binance.com:9443/ws"

# Listen Key keepalive 间隔 (30 分钟)
KEEPALIVE_INTERVAL_SECONDS = 30 * 60


class UserDataStream:
    """用户数据流 WebSocket 客户端.
    
    自动管理 Listen Key 的创建、keepalive 和关闭，
    并通过 WebSocket 接收用户数据事件。
    
    支持的事件类型:
    - outboundAccountPosition: 账户余额更新
    - balanceUpdate: 余额变动 (充值/提现/划转)
    - executionReport: 订单更新
    - listStatus: 订单列表状态 (OCO 等)
    - externalLockUpdate: 外部锁定更新
    - eventStreamTerminated: 数据流终止
    
    用法:
        from binance_toolkit.config import BinanceConfig
        from binance_toolkit.ws.user_data_stream import UserDataStream
        
        config = BinanceConfig.from_env()
        stream = UserDataStream(config)
        stream.run()  # 阻塞运行，Ctrl+C 停止
    """
    
    def __init__(
        self,
        config: "BinanceConfig",
        *,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        on_account_update: Callable[[dict[str, Any]], None] | None = None,
        on_balance_update: Callable[[dict[str, Any]], None] | None = None,
        on_order_update: Callable[[dict[str, Any]], None] | None = None,
        enable_print: bool = True,
    ):
        """
        Args:
            config:            Binance 配置 (需要 API Key)。
            on_message:        所有消息的回调函数。
            on_account_update: 账户更新回调 (outboundAccountPosition)。
            on_balance_update: 余额变动回调 (balanceUpdate)。
            on_order_update:   订单更新回调 (executionReport)。
            enable_print:      是否打印到控制台。
        """
        self._config = config
        self._on_message = on_message
        self._on_account_update = on_account_update
        self._on_balance_update = on_balance_update
        self._on_order_update = on_order_update
        self._enable_print = enable_print
        
        self._listen_key: str | None = None
        self._ws: websocket.WebSocketApp | None = None
        self._stop_event = threading.Event()
        self._keepalive_thread: threading.Thread | None = None
        
        # 导入 toolkit 用于创建/维护 listen key
        from ..toolkit import BinanceToolkit
        self._toolkit = BinanceToolkit(config)
    
    def _create_listen_key(self) -> str:
        """创建 Listen Key."""
        result = self._toolkit.user_data_stream.create_listen_key()
        listen_key = result["listenKey"]
        logger.info("已创建 Listen Key: %s...", listen_key[:20])
        return listen_key
    
    def _keepalive_listen_key(self) -> None:
        """定期延长 Listen Key 有效期."""
        while not self._stop_event.is_set():
            # 等待 30 分钟或被停止
            if self._stop_event.wait(KEEPALIVE_INTERVAL_SECONDS):
                break
            
            if self._listen_key and not self._stop_event.is_set():
                try:
                    self._toolkit.user_data_stream.keepalive_listen_key(self._listen_key)
                    logger.info("Listen Key keepalive 成功")
                except Exception:
                    logger.exception("Listen Key keepalive 失败")
    
    def _delete_listen_key(self) -> None:
        """关闭 Listen Key."""
        if self._listen_key:
            try:
                self._toolkit.user_data_stream.delete_listen_key(self._listen_key)
                logger.info("已关闭 Listen Key")
            except Exception:
                logger.exception("关闭 Listen Key 失败")
            finally:
                self._listen_key = None
    
    def _on_ws_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket 消息回调."""
        try:
            data = json.loads(message)
            event_type = data.get("e", "unknown")
            
            # 通用回调
            if self._on_message:
                self._on_message(data)
            
            # 按事件类型分发
            if event_type == "outboundAccountPosition":
                if self._enable_print:
                    self._print_account_update(data)
                if self._on_account_update:
                    self._on_account_update(data)
            
            elif event_type == "balanceUpdate":
                if self._enable_print:
                    self._print_balance_update(data)
                if self._on_balance_update:
                    self._on_balance_update(data)
            
            elif event_type == "executionReport":
                if self._enable_print:
                    self._print_order_update(data)
                if self._on_order_update:
                    self._on_order_update(data)
            
            elif event_type == "listStatus":
                if self._enable_print:
                    self._print_list_status(data)
            
            elif event_type == "eventStreamTerminated":
                logger.warning("用户数据流已终止")
                if self._enable_print:
                    print(f"\n[警告] 用户数据流已终止 (时间: {self._format_timestamp(data.get('E', 0))})")
            
            else:
                if self._enable_print:
                    print(f"\n[未知事件] {event_type}: {json.dumps(data, indent=2)}")
        
        except json.JSONDecodeError:
            logger.warning("无法解析 WebSocket 消息: %s", message[:200])
        except Exception:
            logger.exception("处理 WebSocket 消息时出错")
    
    def _format_timestamp(self, ts_ms: int) -> str:
        """格式化毫秒时间戳."""
        if not ts_ms:
            return "N/A"
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    def _print_account_update(self, data: dict[str, Any]) -> None:
        """打印账户更新事件."""
        event_time = self._format_timestamp(data.get("E", 0))
        balances = data.get("B", [])
        
        print(f"\n{'='*60}")
        print(f"[账户更新] {event_time}")
        print(f"{'='*60}")
        print(f"{'资产':<10} {'可用余额':>20} {'锁定余额':>20}")
        print(f"{'-'*60}")
        
        for b in balances:
            asset = b.get("a", "")
            free = b.get("f", "0")
            locked = b.get("l", "0")
            print(f"{asset:<10} {free:>20} {locked:>20}")
    
    def _print_balance_update(self, data: dict[str, Any]) -> None:
        """打印余额变动事件."""
        event_time = self._format_timestamp(data.get("E", 0))
        asset = data.get("a", "")
        delta = data.get("d", "0")
        clear_time = self._format_timestamp(data.get("T", 0))
        
        # 判断正负
        delta_float = float(delta)
        delta_color = "\033[32m" if delta_float >= 0 else "\033[31m"
        reset_color = "\033[0m"
        
        print(f"\n{'='*60}")
        print(f"[余额变动] {event_time}")
        print(f"{'='*60}")
        print(f"资产:     {asset}")
        print(f"变动量:   {delta_color}{delta}{reset_color}")
        print(f"清算时间: {clear_time}")
    
    def _print_order_update(self, data: dict[str, Any]) -> None:
        """打印订单更新事件."""
        event_time = self._format_timestamp(data.get("E", 0))
        
        symbol = data.get("s", "")
        side = data.get("S", "")
        order_type = data.get("o", "")
        status = data.get("X", "")
        exec_type = data.get("x", "")
        order_id = data.get("i", "")
        client_order_id = data.get("c", "")
        
        price = data.get("p", "0")
        quantity = data.get("q", "0")
        filled_qty = data.get("z", "0")
        last_filled_qty = data.get("l", "0")
        last_filled_price = data.get("L", "0")
        
        commission = data.get("n", "0")
        commission_asset = data.get("N", "")
        
        # 状态颜色
        if status in ("FILLED", "PARTIALLY_FILLED"):
            status_color = "\033[32m"  # 绿色
        elif status in ("CANCELED", "REJECTED", "EXPIRED"):
            status_color = "\033[31m"  # 红色
        else:
            status_color = "\033[33m"  # 黄色
        reset_color = "\033[0m"
        
        # 方向颜色
        side_color = "\033[32m" if side == "BUY" else "\033[31m"
        
        print(f"\n{'='*70}")
        print(f"[订单更新] {event_time}")
        print(f"{'='*70}")
        print(f"交易对:       {symbol}")
        print(f"订单ID:       {order_id} (客户端: {client_order_id})")
        print(f"方向:         {side_color}{side}{reset_color}")
        print(f"类型:         {order_type}")
        print(f"状态:         {status_color}{status}{reset_color} (执行: {exec_type})")
        print(f"价格:         {price}")
        print(f"数量:         {quantity} (已成交: {filled_qty})")
        
        if float(last_filled_qty) > 0:
            print(f"本次成交:     {last_filled_qty} @ {last_filled_price}")
        
        if commission_asset:
            print(f"手续费:       {commission} {commission_asset}")
    
    def _print_list_status(self, data: dict[str, Any]) -> None:
        """打印订单列表状态事件."""
        event_time = self._format_timestamp(data.get("E", 0))
        symbol = data.get("s", "")
        list_status = data.get("l", "")
        list_order_status = data.get("L", "")
        contingency_type = data.get("c", "")
        orders = data.get("O", [])
        
        print(f"\n{'='*60}")
        print(f"[订单列表状态] {event_time}")
        print(f"{'='*60}")
        print(f"交易对:     {symbol}")
        print(f"类型:       {contingency_type}")
        print(f"状态:       {list_status} / {list_order_status}")
        print(f"订单列表:")
        for o in orders:
            print(f"  - {o.get('s', '')} ID:{o.get('i', '')} ({o.get('c', '')})")
    
    def _on_ws_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """WebSocket 错误回调."""
        logger.error("WebSocket 错误: %s", error)
    
    def _on_ws_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """WebSocket 关闭回调."""
        logger.info("WebSocket 连接关闭: code=%s, msg=%s", close_status_code, close_msg)
    
    def _on_ws_open(self, ws: websocket.WebSocketApp) -> None:
        """WebSocket 连接建立回调."""
        logger.info("用户数据流 WebSocket 连接已建立")
        if self._enable_print:
            print("\n" + "="*60)
            print("用户数据流已连接，等待事件...")
            print("支持的事件: 账户更新、余额变动、订单更新")
            print("按 Ctrl+C 停止")
            print("="*60)
    
    def _signal_handler(self, signum: int, frame: Any) -> None:
        """信号处理."""
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在关闭...", sig_name)
        self.stop()
    
    def stop(self) -> None:
        """停止用户数据流."""
        self._stop_event.set()
        
        if self._ws:
            self._ws.close()
        
        # 等待 keepalive 线程结束
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=2)
        
        # 关闭 Listen Key
        self._delete_listen_key()
        
        # 关闭 toolkit
        self._toolkit.close()
    
    def run(self) -> None:
        """启动用户数据流 (阻塞)."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 创建 Listen Key
        try:
            self._listen_key = self._create_listen_key()
        except Exception:
            logger.exception("创建 Listen Key 失败")
            return
        
        # 启动 keepalive 线程
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_listen_key,
            daemon=True,
        )
        self._keepalive_thread.start()
        
        # 构建 WebSocket URL
        ws_url = f"{SPOT_WS_BASE_URL}/{self._listen_key}"
        logger.info("连接用户数据流 WebSocket...")
        
        self._ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )
        
        # 运行 WebSocket (带自动重连)
        while not self._stop_event.is_set():
            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                logger.exception("WebSocket 运行异常")
            
            if not self._stop_event.is_set():
                logger.info("WebSocket 断开，5 秒后重连...")
                time.sleep(5)
                
                # 重新创建 Listen Key (可能已过期)
                try:
                    self._listen_key = self._create_listen_key()
                    ws_url = f"{SPOT_WS_BASE_URL}/{self._listen_key}"
                    self._ws = websocket.WebSocketApp(
                        ws_url,
                        on_message=self._on_ws_message,
                        on_error=self._on_ws_error,
                        on_close=self._on_ws_close,
                        on_open=self._on_ws_open,
                    )
                except Exception:
                    logger.exception("重新创建 Listen Key 失败")
        
        logger.info("用户数据流已停止")


def run_user_data_stream(
    config: "BinanceConfig",
    enable_print: bool = True,
) -> None:
    """便捷函数: 启动用户数据流.
    
    Args:
        config:       Binance 配置。
        enable_print: 是否打印到控制台。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    stream = UserDataStream(
        config,
        enable_print=enable_print,
    )
    stream.run()


if __name__ == "__main__":
    from ..config import BinanceConfig
    
    config = BinanceConfig.from_env()
    run_user_data_stream(config)
