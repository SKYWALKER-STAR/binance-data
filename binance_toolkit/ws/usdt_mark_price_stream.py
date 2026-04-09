"""U本位合约标记价格 WebSocket 流.

文档参考:
  - Mark Price Stream: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Mark-Price-Stream
  - Mark Price Stream for All market: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Mark-Price-Stream-for-All-market

WebSocket Base URL: wss://fstream.binance.com

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

# U本位合约 WebSocket 基础地址
FAPI_WS_BASE_URL = "wss://fstream.binance.com/ws"

# 批量写入配置
DEFAULT_BATCH_SIZE = 500  # 达到此数量立即写入 (U本位合约多，需要更大批量)
DEFAULT_FLUSH_INTERVAL = 1.0  # 最长等待时间 (秒)
DEFAULT_MAX_RETRIES = 3  # 最大重试次数
DEFAULT_RETRY_DELAY = 1.0  # 重试间隔 (秒)
DEFAULT_WRITER_THREADS = 2  # 默认写入线程数
DEFAULT_SAMPLE_INTERVAL = 0  # 采样间隔 (秒), 0 表示不采样，存储所有数据

# 合约类型标识
CONTRACT_TYPE_USDT = "USDT"  # U本位合约


class UsdtMarkPriceStream:
    """U本位合约标记价格 WebSocket 流.

    支持订阅单个合约或全部合约的标记价格更新。

    用法:
        # 订阅全部合约 (每秒更新)
        stream = UsdtMarkPriceStream(on_message=lambda data: print(data))
        stream.run()  # 阻塞运行, Ctrl+C 停止

        # 订阅指定合约
        stream = UsdtMarkPriceStream(
            symbols=["BTCUSDT", "ETHUSDT"],
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
            symbols:      要订阅的合约列表，如 ["BTCUSDT"]。
                          省略或传空列表则订阅全部合约。
            update_speed: 更新速度，"1s" (每秒) 或 "3s" (每3秒)。
            on_message:   收到消息时的回调函数。
            perp_only:    仅保留永续合约数据 (排除交割合约，如 BTCUSDT_230630)，默认 True。
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
            return f"{FAPI_WS_BASE_URL}/{stream}"
        else:
            # 订阅指定合约
            suffix = "" if self._update_speed == "3s" else "@1s"
            streams = [f"{s.lower()}@markPrice{suffix}" for s in self._symbols]
            return f"{FAPI_WS_BASE_URL}/{'/'.join(streams)}"

    def _is_perpetual(self, symbol: str) -> bool:
        """判断是否为永续合约 (U本位永续合约不含下划线，交割合约如 BTCUSDT_230630)."""
        return "_" not in symbol

    def _on_ws_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket 消息回调."""
        try:
            data = json.loads(message)

            # 处理数组格式 (全部合约订阅)
            if isinstance(data, list):
                if self._perp_only:
                    data = [d for d in data if self._is_perpetual(d.get("s", ""))]
                if self._on_message:
                    self._on_message(data)
            else:
                # 单条消息
                if self._perp_only and not self._is_perpetual(data.get("s", "")):
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
        logger.info("正在连接 U本位 WebSocket: %s", url)

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


class UsdtMarkPriceStreamWriter:
    """带批量写入和重试机制的 U本位标记价格流写入器.

    特性:
      - 内存队列缓冲，批量写入 InfluxDB
      - 写入失败自动重试
      - 支持同时打印到控制台
      - 优雅停止，确保缓冲数据写入

    用法:
        config = BinanceConfig.from_env()
        writer = UsdtMarkPriceStreamWriter(
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
        writer_threads: int = DEFAULT_WRITER_THREADS,
        sample_interval: int = DEFAULT_SAMPLE_INTERVAL,
    ):
        """
        Args:
            config:         Binance 配置 (含 InfluxDB 配置).
            symbols:        要订阅的合约列表，省略则订阅全部。
            update_speed:   更新速度 "1s" 或 "3s"。
            perp_only:      仅保留永续合约，默认 True。
            enable_print:   是否同时打印到控制台，默认 True。
            batch_size:     批量写入大小，默认 500 条。
            flush_interval: 最长刷新间隔 (秒)，默认 1.0。
            max_retries:    写入失败最大重试次数，默认 3。
            retry_delay:    重试间隔 (秒)，默认 1.0。
            writer_threads: 写入线程数，默认 2。
            sample_interval: 采样间隔 (秒)，默认 0 不采样。设为 10 表示每个合约每 10 秒只存一条。
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
        self._writer_threads = writer_threads
        self._sample_interval = sample_interval

        self._queue: queue.Queue[dict] = queue.Queue()
        self._stop_event = threading.Event()
        self._storage: InfluxDBStorage | None = None
        self._stream: UsdtMarkPriceStream | None = None
        self._writer_thread_list: list[threading.Thread] = []

        # 采样状态: 记录每个 symbol 上次写入的时间窗口
        # key: symbol, value: 上次写入的时间窗口编号 (timestamp // sample_interval)
        self._last_sample_window: dict[str, int] = {}
        self._sample_lock = threading.Lock()

        # 统计信息
        self._stats = {
            "received": 0,
            "written": 0,
            "sampled": 0,  # 采样后实际入队的数量
            "skipped": 0,  # 采样跳过的数量
            "failed": 0,
            "retries": 0,
        }

    def _should_sample(self, item: dict) -> bool:
        """判断该数据点是否应该被采样存储.
        
        采样逻辑：每个 symbol 在同一个时间窗口内只保留第一条数据。
        时间窗口 = timestamp // sample_interval
        
        Returns:
            True 表示应该存储，False 表示跳过
        """
        if self._sample_interval <= 0:
            return True  # 不采样，全部存储

        symbol = item.get("s", "UNKNOWN")
        event_time_ms = item.get("E", 0)
        if not event_time_ms:
            return True  # 没有时间戳的数据直接存储

        # 计算当前时间窗口
        event_time_sec = event_time_ms // 1000
        current_window = event_time_sec // self._sample_interval

        with self._sample_lock:
            last_window = self._last_sample_window.get(symbol, -1)
            if current_window > last_window:
                # 新的时间窗口，记录并存储
                self._last_sample_window[symbol] = current_window
                return True
            else:
                # 同一窗口内已有数据，跳过
                return False

    def _on_message(self, data: dict | list[dict]) -> None:
        """WebSocket 消息处理: 采样过滤 + 放入队列 + 可选打印."""
        items = data if isinstance(data, list) else [data]

        for item in items:
            self._stats["received"] += 1
            
            # 采样过滤
            if self._should_sample(item):
                self._stats["sampled"] += 1
                self._queue.put(item)
            else:
                self._stats["skipped"] += 1

        if self._enable_print:
            _default_print_handler(data)

    def _writer_loop(self, thread_id: int) -> None:
        """后台写入线程: 批量写入 InfluxDB.
        
        Args:
            thread_id: 线程编号，用于日志区分
        """
        buffer: list[dict] = []
        last_flush_time = time.time()
        last_stats_time = time.time()
        stats_interval = 60.0  # 每 60 秒输出一次统计信息

        logger.info("U本位写入线程 #%d 已启动", thread_id)

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
                self._flush_buffer(buffer, thread_id)
                buffer = []
                last_flush_time = time.time()

            # 周期性输出统计信息 (仅线程 0 输出)
            if thread_id == 0 and time.time() - last_stats_time >= stats_interval:
                sample_rate = (
                    f"{self._stats['sampled'] / self._stats['received'] * 100:.1f}%"
                    if self._stats["received"] > 0 else "N/A"
                )
                logger.info(
                    "U本位写入器统计 | 接收: %d | 采样: %d (%s) | 跳过: %d | 写入: %d | 失败: %d | 队列: %d",
                    self._stats["received"],
                    self._stats["sampled"],
                    sample_rate,
                    self._stats["skipped"],
                    self._stats["written"],
                    self._stats["failed"],
                    self._queue.qsize(),
                )
                last_stats_time = time.time()

        logger.info("U本位写入线程 #%d 已结束", thread_id)

    def _flush_buffer(self, buffer: list[dict], thread_id: int = 0) -> None:
        """将缓冲数据写入 InfluxDB (带重试).
        
        Args:
            buffer: 待写入的数据列表
            thread_id: 写入线程编号
        """
        if not self._storage:
            return

        symbols = set(item.get("s", "UNKNOWN") for item in buffer)
        logger.debug(
            "U本位线程#%d 开始写入 %d 条数据, 涉及 %d 个合约",
            thread_id, len(buffer), len(symbols),
        )

        for attempt in range(self._max_retries + 1):
            try:
                start_time = time.time()
                self._write_batch(buffer)
                elapsed = time.time() - start_time
                self._stats["written"] += len(buffer)
                logger.info(
                    "✓ U本位线程#%d 批量写入成功: %d 条, 耗时 %.3fs, 队列剩余 %d",
                    thread_id, len(buffer), elapsed, self._queue.qsize(),
                )
                return
            except Exception as e:
                self._stats["retries"] += 1
                if attempt < self._max_retries:
                    logger.warning(
                        "U本位线程#%d 写入失败 (尝试 %d/%d): %s, %.1f秒后重试...",
                        thread_id, attempt + 1, self._max_retries + 1, e, self._retry_delay,
                    )
                    time.sleep(self._retry_delay)
                else:
                    logger.error("✗ U本位线程#%d 写入失败，已达最大重试次数，丢弃 %d 条数据", thread_id, len(buffer))
                    self._stats["failed"] += len(buffer)

    def _write_batch(self, buffer: list[dict]) -> None:
        """批量写入数据到 InfluxDB."""
        assert self._storage is not None

        # 构建批量写入的数据点
        points = []
        for item in buffer:
            symbol = item.get("s", "UNKNOWN")
            mark_price = float(item.get("p", 0))
            index_price = float(item.get("i", 0))

            # 资金费率 (转换为百分比形式存储，保留5位小数)
            raw_rate = item.get("r", "")
            last_funding_rate = round(float(raw_rate) * 100, 5) if raw_rate else None

            # 下次资金费时间
            raw_nft = item.get("T", 0)
            next_funding_time = int(raw_nft) if raw_nft else None

            # 事件时间作为数据时间戳
            event_time = item.get("E", 0)
            if event_time:
                timestamp = datetime.fromtimestamp(event_time / 1000, tz=timezone.utc)
            else:
                timestamp = None

            points.append({
                "symbol": symbol,
                "mark_price": mark_price,
                "index_price": index_price,
                "last_funding_rate": last_funding_rate,
                "next_funding_time": next_funding_time,
                "timestamp": timestamp,
                "contract_type": CONTRACT_TYPE_USDT,
            })

        # 一次性批量写入
        self._storage.write_mark_price_batch(points)

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

        sample_info = f"sample_interval={self._sample_interval}s" if self._sample_interval > 0 else "无采样"
        logger.info(
            "U本位标记价格流写入器启动: batch_size=%d, flush_interval=%.1fs, writer_threads=%d, %s, print=%s",
            self._batch_size, self._flush_interval, self._writer_threads, sample_info, self._enable_print,
        )

        # 启动多个后台写入线程
        for i in range(self._writer_threads):
            t = threading.Thread(target=self._writer_loop, args=(i,), daemon=True)
            t.start()
            self._writer_thread_list.append(t)

        # 启动 WebSocket 流
        self._stream = UsdtMarkPriceStream(
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
        # 等待所有写入线程完成
        for i, t in enumerate(self._writer_thread_list):
            if t.is_alive():
                logger.info("等待U本位写入线程 #%d 完成...", i)
                t.join(timeout=10)

        # 关闭 InfluxDB 连接
        if self._storage:
            self._storage.close()

        # 输出统计信息
        logger.info(
            "U本位写入器已停止 | 接收: %d | 写入: %d | 失败: %d | 重试: %d",
            self._stats["received"],
            self._stats["written"],
            self._stats["failed"],
            self._stats["retries"],
        )


def _default_print_handler(data: dict | list[dict]) -> None:
    """默认的消息打印处理器."""
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(data, list):
        # 检查第一条数据的事件时间与当前时间的差异
        if data:
            event_time_ms = data[0].get("E", 0)
            if event_time_ms:
                event_time = datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc)
                delay = (now - event_time).total_seconds()
                print(f"\n[{now_str}] U本位收到 {len(data)} 条标记价格更新 (数据延迟: {delay:.1f}s):")
            else:
                print(f"\n[{now_str}] U本位收到 {len(data)} 条标记价格更新:")
        for item in data:
            _print_single(item)
    else:
        event_time_ms = data.get("E", 0)
        if event_time_ms:
            event_time = datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc)
            delay = (now - event_time).total_seconds()
            print(f"\n[{now_str}] U本位标记价格更新 (数据延迟: {delay:.1f}s):")
        else:
            print(f"\n[{now_str}] U本位标记价格更新:")
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

    # 格式化资金费率 (转换为百分比形式，保留5位小数)
    if funding_rate:
        fr_str = f"{float(funding_rate) * 100:.5f}%"
    else:
        fr_str = "N/A"

    print(f"  {symbol:16s} | Mark: {mark_price:>14s} | Index: {index_price:>14s} | FR: {fr_str:>11s} | NextFR: {nft_str}")


def run_usdt_mark_price_stream(
    symbols: list[str] | None = None,
    update_speed: str = "1s",
    perp_only: bool = True,
    config: "BinanceConfig | None" = None,
    write_db: bool = False,
    enable_print: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    writer_threads: int = DEFAULT_WRITER_THREADS,
    sample_interval: int = DEFAULT_SAMPLE_INTERVAL,
) -> None:
    """便捷函数: 启动 U本位标记价格流.

    Args:
        symbols:        要订阅的合约列表，省略则订阅全部。
        update_speed:   更新速度 "1s" 或 "3s"。
        perp_only:      仅显示永续合约，默认 True。
        config:         Binance 配置，写入数据库时必须提供。
        write_db:       是否写入 InfluxDB，默认 False。
        enable_print:   是否打印到控制台，默认 True。
        batch_size:     批量写入大小 (仅 write_db=True 时有效)。
        flush_interval: 刷新间隔秒数 (仅 write_db=True 时有效)。
        writer_threads: 写入线程数 (仅 write_db=True 时有效)，默认 2。
        sample_interval: 采样间隔秒数，默认 0 不采样。设为 10 表示每合约每 10 秒存一条。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if write_db:
        if config is None:
            raise ValueError("写入数据库需要提供 config 参数")
        writer = UsdtMarkPriceStreamWriter(
            config,
            symbols=symbols,
            update_speed=update_speed,
            perp_only=perp_only,
            enable_print=enable_print,
            batch_size=batch_size,
            flush_interval=flush_interval,
            writer_threads=writer_threads,
            sample_interval=sample_interval,
        )
        writer.run()
    else:
        # 仅打印模式
        stream = UsdtMarkPriceStream(
            symbols=symbols,
            update_speed=update_speed,
            on_message=_default_print_handler if enable_print else None,
            perp_only=perp_only,
        )
        stream.run()
