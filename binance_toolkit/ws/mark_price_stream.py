"""币本位合约标记价格 WebSocket 流.

文档参考:
  - Mark Price Stream: https://developers.binance.com/docs/derivatives/coin-margined-futures/websocket-market-streams/Mark-Price-Stream

WebSocket Base URL: wss://dstream.binance.com

Stream 格式:
  - 单个合约: <symbol>@markPrice 或 <symbol>@markPrice@1s
  - 全部合约: !markPrice@arr 或 !markPrice@arr@1s
"""

from __future__ import annotations

import json
import logging
import queue
import signal
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

import websocket

if TYPE_CHECKING:
    from ..config import BinanceConfig
    from ..storage.influxdb import InfluxDBStorage

logger = logging.getLogger("binance_toolkit.ws")

# 币本位合约 WebSocket 基础地址
DAPI_WS_BASE_URL = "wss://dstream.binance.com/ws"

# 批量写入配置
DEFAULT_BATCH_SIZE = 100  # 达到此数量立即写入
DEFAULT_FLUSH_INTERVAL = 1.0  # 最长等待时间 (秒)
DEFAULT_MAX_RETRIES = 3  # 最大重试次数
DEFAULT_RETRY_DELAY = 1.0  # 重试间隔 (秒)


class MarkPriceStream:
    """币本位合约标记价格 WebSocket 流.

    支持订阅单个合约或全部合约的标记价格更新。

    用法:
        # 订阅全部合约 (每秒更新)
        stream = MarkPriceStream(on_message=lambda data: print(data))
        stream.run()  # 阻塞运行, Ctrl+C 停止

        # 订阅指定合约
        stream = MarkPriceStream(
            symbols=["BTCUSD_PERP", "ETHUSD_PERP"],
            update_speed="1s",
            on_message=my_handler,
        )
        stream.run()
    """

    def __init__(
        self,
        *,
        symbols: list[str] | None = None,
        update_speed: str = "1s",
        on_message: Callable[[dict | list[dict]], None] | None = None,
        perp_only: bool = True,
    ):
        """
        Args:
            symbols:      要订阅的合约列表，如 ["BTCUSD_PERP"]。
                          省略或传空列表则订阅全部合约。
            update_speed: 更新速度，"1s" (每秒) 或 "3s" (每3秒)。
            on_message:   收到消息时的回调函数。
            perp_only:    仅保留永续合约数据 (symbol 以 _PERP 结尾)，默认 True。
        """
        self._symbols = symbols or []
        self._update_speed = update_speed
        self._on_message = on_message
        self._perp_only = perp_only
        self._stop_event = threading.Event()
        self._ws: websocket.WebSocketApp | None = None

    def _build_stream_url(self) -> str:
        """构建 WebSocket 订阅 URL."""
        if not self._symbols:
            # 订阅全部合约
            stream = "!markPrice@arr" if self._update_speed == "3s" else "!markPrice@arr@1s"
            return f"{DAPI_WS_BASE_URL}/{stream}"
        else:
            # 订阅指定合约
            suffix = "" if self._update_speed == "3s" else "@1s"
            streams = [f"{s.lower()}@markPrice{suffix}" for s in self._symbols]
            return f"{DAPI_WS_BASE_URL}/{'/'.join(streams)}"

    def _on_ws_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket 消息回调."""
        try:
            data = json.loads(message)

            # 处理数组格式 (全部合约订阅)
            if isinstance(data, list):
                if self._perp_only:
                    data = [d for d in data if d.get("s", "").endswith("_PERP")]
                if self._on_message:
                    self._on_message(data)
            else:
                # 单条消息
                if self._perp_only and not data.get("s", "").endswith("_PERP"):
                    return
                if self._on_message:
                    self._on_message(data)

        except json.JSONDecodeError:
            logger.warning("无法解析 WebSocket 消息: %s", message[:200])
        except Exception:
            logger.exception("处理 WebSocket 消息时出错")

    def _on_ws_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """WebSocket 错误回调."""
        logger.error("WebSocket 错误: %s", error)

    def _on_ws_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """WebSocket 关闭回调."""
        logger.info("WebSocket 连接关闭: code=%s, msg=%s", close_status_code, close_msg)

    def _on_ws_open(self, ws: websocket.WebSocketApp) -> None:
        """WebSocket 连接建立回调."""
        logger.info("WebSocket 连接已建立")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """信号处理."""
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在关闭 WebSocket...", sig_name)
        self.stop()

    def run(self) -> None:
        """启动 WebSocket 连接 (阻塞).

        通过 SIGINT (Ctrl+C) 或 SIGTERM 优雅退出。
        """
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        url = self._build_stream_url()
        logger.info("正在连接 WebSocket: %s", url)

        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )

        # run_forever 会阻塞直到连接关闭
        self._ws.run_forever(ping_interval=30, ping_timeout=10)
        logger.info("WebSocket 已停止")

    def stop(self) -> None:
        """停止 WebSocket 连接."""
        self._stop_event.set()
        if self._ws:
            self._ws.close()


class MarkPriceStreamWriter:
    """带批量写入和重试机制的标记价格流写入器.

    特性:
      - 内存队列缓冲，批量写入 InfluxDB
      - 写入失败自动重试
      - 支持同时打印到控制台
      - 优雅停止，确保缓冲数据写入

    用法:
        config = BinanceConfig.from_env()
        writer = MarkPriceStreamWriter(
            config,
            enable_print=True,
            batch_size=100,
            flush_interval=1.0,
        )
        writer.run()  # 阻塞运行, Ctrl+C 停止
    """

    def __init__(
        self,
        config: "BinanceConfig",
        *,
        symbols: list[str] | None = None,
        update_speed: str = "1s",
        perp_only: bool = True,
        enable_print: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ):
        """
        Args:
            config:         Binance 配置 (含 InfluxDB 配置).
            symbols:        要订阅的合约列表，省略则订阅全部。
            update_speed:   更新速度 "1s" 或 "3s"。
            perp_only:      仅保留永续合约，默认 True。
            enable_print:   是否同时打印到控制台，默认 True。
            batch_size:     批量写入大小，默认 100 条。
            flush_interval: 最长刷新间隔 (秒)，默认 1.0。
            max_retries:    写入失败最大重试次数，默认 3。
            retry_delay:    重试间隔 (秒)，默认 1.0。
        """
        self._config = config
        self._symbols = symbols
        self._update_speed = update_speed
        self._perp_only = perp_only
        self._enable_print = enable_print
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        self._queue: queue.Queue[dict] = queue.Queue()
        self._stop_event = threading.Event()
        self._storage: InfluxDBStorage | None = None
        self._stream: MarkPriceStream | None = None
        self._writer_thread: threading.Thread | None = None

        # 统计信息
        self._stats = {
            "received": 0,
            "written": 0,
            "failed": 0,
            "retries": 0,
        }

    def _on_message(self, data: dict | list[dict]) -> None:
        """WebSocket 消息处理: 放入队列 + 可选打印."""
        items = data if isinstance(data, list) else [data]

        for item in items:
            self._stats["received"] += 1
            self._queue.put(item)

        if self._enable_print:
            _default_print_handler(data)

    def _writer_loop(self) -> None:
        """后台写入线程: 批量写入 InfluxDB."""
        buffer: list[dict] = []
        last_flush_time = time.time()

        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                # 从队列获取数据，最多等待 flush_interval
                timeout = max(0.1, self._flush_interval - (time.time() - last_flush_time))
                item = self._queue.get(timeout=timeout)
                buffer.append(item)
                self._queue.task_done()
            except queue.Empty:
                pass

            # 判断是否需要刷新
            should_flush = (
                len(buffer) >= self._batch_size
                or (buffer and time.time() - last_flush_time >= self._flush_interval)
                or (self._stop_event.is_set() and buffer)
            )

            if should_flush and buffer:
                self._flush_buffer(buffer)
                buffer = []
                last_flush_time = time.time()

    def _flush_buffer(self, buffer: list[dict]) -> None:
        """将缓冲数据写入 InfluxDB (带重试)."""
        if not self._storage:
            return

        for attempt in range(self._max_retries + 1):
            try:
                self._write_batch(buffer)
                self._stats["written"] += len(buffer)
                logger.debug("批量写入 %d 条数据成功", len(buffer))
                return
            except Exception as e:
                self._stats["retries"] += 1
                if attempt < self._max_retries:
                    logger.warning(
                        "写入失败 (尝试 %d/%d): %s, %.1f秒后重试...",
                        attempt + 1, self._max_retries + 1, e, self._retry_delay,
                    )
                    time.sleep(self._retry_delay)
                else:
                    logger.error("写入失败，已达最大重试次数，丢弃 %d 条数据", len(buffer))
                    self._stats["failed"] += len(buffer)

    def _write_batch(self, buffer: list[dict]) -> None:
        """批量写入数据到 InfluxDB."""
        assert self._storage is not None

        for item in buffer:
            symbol = item.get("s", "UNKNOWN")
            mark_price = float(item.get("p", 0))
            index_price = float(item.get("i", 0))

            # 资金费率
            raw_rate = item.get("r", "")
            last_funding_rate = float(raw_rate) if raw_rate else None

            # 下次资金费时间
            raw_nft = item.get("T", 0)
            next_funding_time = int(raw_nft) if raw_nft else None

            # 事件时间作为数据时间戳
            event_time = item.get("E", 0)
            if event_time:
                timestamp = datetime.fromtimestamp(event_time / 1000, tz=timezone.utc)
            else:
                timestamp = None

            self._storage.write_mark_price(
                symbol,
                mark_price,
                index_price,
                last_funding_rate=last_funding_rate,
                next_funding_time=next_funding_time,
                timestamp=timestamp,
            )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """信号处理."""
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在优雅停止...", sig_name)
        self.stop()

    def run(self) -> None:
        """启动 WebSocket 流和写入线程 (阻塞).

        通过 SIGINT (Ctrl+C) 或 SIGTERM 优雅退出。
        """
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # 初始化 InfluxDB 存储
        from ..storage.influxdb import InfluxDBStorage
        self._storage = InfluxDBStorage(self._config)

        logger.info(
            "标记价格流写入器启动: batch_size=%d, flush_interval=%.1fs, print=%s",
            self._batch_size, self._flush_interval, self._enable_print,
        )

        # 启动后台写入线程
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

        # 启动 WebSocket 流
        self._stream = MarkPriceStream(
            symbols=self._symbols,
            update_speed=self._update_speed,
            on_message=self._on_message,
            perp_only=self._perp_only,
        )

        try:
            self._stream.run()
        finally:
            self._cleanup()

    def stop(self) -> None:
        """停止写入器."""
        self._stop_event.set()
        if self._stream:
            self._stream.stop()

    def _cleanup(self) -> None:
        """清理资源."""
        # 等待写入线程完成
        if self._writer_thread and self._writer_thread.is_alive():
            logger.info("等待缓冲数据写入完成...")
            self._writer_thread.join(timeout=10)

        # 关闭 InfluxDB 连接
        if self._storage:
            self._storage.close()

        # 输出统计信息
        logger.info(
            "写入器已停止 | 接收: %d | 写入: %d | 失败: %d | 重试: %d",
            self._stats["received"],
            self._stats["written"],
            self._stats["failed"],
            self._stats["retries"],
        )


def _default_print_handler(data: dict | list[dict]) -> None:
    """默认的消息打印处理器."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(data, list):
        print(f"\n[{now}] 收到 {len(data)} 条标记价格更新:")
        for item in data:
            _print_single(item)
    else:
        print(f"\n[{now}] 标记价格更新:")
        _print_single(data)


def _print_single(item: dict) -> None:
    """打印单条标记价格数据."""
    symbol = item.get("s", "UNKNOWN")
    mark_price = item.get("p", "N/A")
    index_price = item.get("i", "N/A")
    funding_rate = item.get("r", "")
    next_funding_time = item.get("T", 0)

    # 格式化下次资金费时间
    if next_funding_time:
        nft_str = datetime.fromtimestamp(next_funding_time / 1000, tz=timezone.utc).strftime("%H:%M:%S")
    else:
        nft_str = "N/A"

    # 格式化资金费率
    if funding_rate:
        fr_str = f"{float(funding_rate) * 100:.5f}%"
    else:
        fr_str = "N/A"

    print(f"  {symbol:16s} | Mark: {mark_price:>14s} | Index: {index_price:>14s} | FR: {fr_str:>11s} | NextFR: {nft_str}")


def run_mark_price_stream(
    symbols: list[str] | None = None,
    update_speed: str = "1s",
    perp_only: bool = True,
    config: "BinanceConfig | None" = None,
    write_db: bool = False,
    enable_print: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    flush_interval: float = DEFAULT_FLUSH_INTERVAL,
) -> None:
    """便捷函数: 启动标记价格流.

    Args:
        symbols:        要订阅的合约列表，省略则订阅全部。
        update_speed:   更新速度 "1s" 或 "3s"。
        perp_only:      仅显示永续合约，默认 True。
        config:         Binance 配置，写入数据库时必须提供。
        write_db:       是否写入 InfluxDB，默认 False。
        enable_print:   是否打印到控制台，默认 True。
        batch_size:     批量写入大小 (仅 write_db=True 时有效)。
        flush_interval: 刷新间隔秒数 (仅 write_db=True 时有效)。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if write_db:
        if config is None:
            raise ValueError("写入数据库需要提供 config 参数")
        writer = MarkPriceStreamWriter(
            config,
            symbols=symbols,
            update_speed=update_speed,
            perp_only=perp_only,
            enable_print=enable_print,
            batch_size=batch_size,
            flush_interval=flush_interval,
        )
        writer.run()
    else:
        # 仅打印模式
        stream = MarkPriceStream(
            symbols=symbols,
            update_speed=update_speed,
            on_message=_default_print_handler if enable_print else None,
            perp_only=perp_only,
        )
        stream.run()
