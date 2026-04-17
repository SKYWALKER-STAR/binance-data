"""U本位合约 K线 WebSocket 流.

文档参考:
  - Individual Symbol Kline/Candlestick Streams:
    https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Kline-Candlestick-Streams

WebSocket Base URL: wss://fstream.binance.com

Stream 格式:
  - 单个合约: <symbol>@kline_<interval>   (单流)
  - 多个合约: /stream?streams=...          (合并流, 消息包含 stream + data 两层)

支持的 interval: 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M

K线消息结构 (k 字段):
  t  - K线开始时间 (ms)
  T  - K线结束时间 (ms)
  s  - 合约交易对
  i  - 时间间隔
  f  - 第一个成交 ID
  L  - 最后一个成交 ID
  o  - 开盘价
  c  - 收盘价 (当前价格)
  h  - 最高价
  l  - 最低价
  v  - 成交量 (基础资产)
  n  - 成交笔数
  x  - K线是否已结束 (closed)
  q  - 成交额 (计价资产)
  V  - 主动买入成交量
  Q  - 主动买入成交额
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
    from ..storage.kafka import KafkaStorage

logger = logging.getLogger("binance_toolkit.ws.kline")

# U本位合约 WebSocket 基础地址
FAPI_WS_BASE_URL = "wss://fstream.binance.com"

# 批量写入配置
DEFAULT_BATCH_SIZE = 200
DEFAULT_FLUSH_INTERVAL = 2.0    # 日K线更新不频繁，稍长的 flush 间隔
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_INTERVAL = "1d"         # 默认订阅日 K 线


class UsdtKlineStream:
    """U本位合约 K线 WebSocket 流.

    订阅指定合约列表的 K 线数据，通过 on_message 回调传出。

    用法:
        stream = UsdtKlineStream(
            symbols=["BTCUSDT", "ETHUSDT"],
            interval="1d",
            on_message=lambda data: print(data),
        )
        stream.run()  # 阻塞运行, Ctrl+C 停止
    """

    def __init__(
        self,
        *,
        symbols: list[str],
        interval: str = DEFAULT_INTERVAL,
        on_message: Callable[[dict], None] | None = None,
        closed_only: bool = False,
    ):
        """
        Args:
            symbols:      要订阅的合约列表，如 ["BTCUSDT", "ETHUSDT"]。
            interval:     K 线间隔，如 "1d" / "1h" / "15m" 等。
            on_message:   收到消息时的回调函数，参数为已解析的 K线数据 dict。
            closed_only:  True 时仅回调已收盘的 K 线（k.x == true），默认 False。
        """
        if not symbols:
            raise ValueError("symbols 不能为空，请至少指定一个合约")
        self._symbols = [s.upper() for s in symbols]
        self._interval = interval
        self._on_message = on_message
        self._closed_only = closed_only
        self._stop_event = threading.Event()
        self._ws: websocket.WebSocketApp | None = None

    def _build_stream_url(self) -> str:
        """构建 WebSocket 订阅 URL."""
        streams = [f"{s.lower()}@kline_{self._interval}" for s in self._symbols]
        if len(streams) == 1:
            # 单流模式：消息直接是 kline event
            return f"{FAPI_WS_BASE_URL}/ws/{streams[0]}"
        else:
            # 合并流模式：消息包含 {"stream": "...", "data": {...}}
            return f"{FAPI_WS_BASE_URL}/stream?streams={'/'.join(streams)}"

    @property
    def _is_combined(self) -> bool:
        """是否为合并流模式（多个合约）."""
        return len(self._symbols) > 1

    def _on_ws_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket 消息回调."""
        try:
            raw = json.loads(message)

            # 合并流消息有外层 wrapper
            if self._is_combined:
                data = raw.get("data", raw)
            else:
                data = raw

            # 只处理 kline 事件
            if data.get("e") != "kline":
                return

            kline = data.get("k", {})
            is_closed = kline.get("x", False)

            if self._closed_only and not is_closed:
                return

            if self._on_message:
                self._on_message(data)

        except json.JSONDecodeError:
            logger.warning("无法解析 WebSocket 消息: %s", message[:200])
        except Exception:
            logger.exception("处理 K线 WebSocket 消息时出错")

    def _on_ws_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.error("K线 WebSocket 错误: %s", error)

    def _on_ws_close(
        self,
        ws: websocket.WebSocketApp,
        close_status_code: int,
        close_msg: str,
    ) -> None:
        logger.info("K线 WebSocket 连接关闭: code=%s, msg=%s", close_status_code, close_msg)

    def _on_ws_open(self, ws: websocket.WebSocketApp) -> None:
        logger.info(
            "K线 WebSocket 连接已建立 | interval=%s | symbols(%d)=%s",
            self._interval,
            len(self._symbols),
            ",".join(self._symbols[:5]) + ("..." if len(self._symbols) > 5 else ""),
        )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在关闭 K线 WebSocket...", sig_name)
        self.stop()

    def run(self) -> None:
        """启动 WebSocket 连接 (阻塞).

        通过 SIGINT (Ctrl+C) 或 SIGTERM 优雅退出。
        """
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        url = self._build_stream_url()
        logger.info("正在连接 U本位 K线 WebSocket: %s", url[:120])

        self._ws = websocket.WebSocketApp(
            url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )

        self._ws.run_forever(ping_interval=30, ping_timeout=10)
        logger.info("K线 WebSocket 已停止")

    def stop(self) -> None:
        """停止 WebSocket 连接."""
        self._stop_event.set()
        if self._ws:
            self._ws.close()


class UsdtKlineStreamWriter:
    """带批量写入和重试机制的 U本位 K线流写入器.

    特性:
      - 订阅指定合约列表的指定 K 线周期
      - 通过内存队列缓冲，批量写入 Kafka
      - 写入失败自动重试
      - 支持 closed_only 模式，仅保存已收盘的 K 线
      - 优雅停止，确保缓冲数据写入

    用法:
        config = BinanceConfig.from_env()
        writer = UsdtKlineStreamWriter(
            config,
            symbols=["BTCUSDT", "ETHUSDT"],
            interval="1d",
            closed_only=True,
            write_kafka=True,
        )
        writer.run()  # 阻塞运行, Ctrl+C 停止
    """

    def __init__(
        self,
        config: "BinanceConfig",
        *,
        symbols: list[str],
        interval: str = DEFAULT_INTERVAL,
        closed_only: bool = True,
        enable_print: bool = True,
        write_kafka: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        kafka_topic: str = "",
    ):
        """
        Args:
            config:         Binance 配置 (含 Kafka 配置).
            symbols:        要订阅的合约列表，如 ["BTCUSDT", "ETHUSDT"]。
            interval:       K 线间隔，默认 "1d"（日 K 线）。
            closed_only:    仅保存已收盘的 K 线，默认 True。
            enable_print:   是否同时打印到控制台，默认 True。
            write_kafka:    是否发布到 Kafka，默认 True。
            batch_size:     批量写入大小，默认 200 条。
            flush_interval: 最长刷新间隔 (秒)，默认 2.0。
            max_retries:    写入失败最大重试次数，默认 3。
            retry_delay:    重试间隔 (秒)，默认 1.0。
            kafka_topic:    目标 Kafka Topic，空字符串时使用 config.kafka_topic_kline_usdt。
        """
        self._config = config
        self._symbols = [s.upper() for s in symbols]
        self._interval = interval
        self._closed_only = closed_only
        self._enable_print = enable_print
        self._write_kafka = write_kafka
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._kafka_topic = kafka_topic or config.kafka_topic_kline_usdt

        self._queue: queue.Queue[dict] = queue.Queue()
        self._stop_event = threading.Event()
        self._kafka: KafkaStorage | None = None
        self._stream: UsdtKlineStream | None = None
        self._writer_thread: threading.Thread | None = None

        self._stats = {
            "received": 0,
            "queued": 0,
            "written": 0,
            "failed": 0,
            "retries": 0,
        }

    def _on_message(self, data: dict) -> None:
        """WebSocket 消息处理: 放入队列 + 可选打印."""
        self._stats["received"] += 1
        self._stats["queued"] += 1
        self._queue.put(data)

        if self._enable_print:
            _default_print_handler(data)

    def _writer_loop(self) -> None:
        """后台写入线程: 批量写入 Kafka."""
        buffer: list[dict] = []
        last_flush_time = time.time()
        last_stats_time = time.time()
        stats_interval = 60.0

        logger.info("K线写入线程已启动")

        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                timeout = max(0.1, self._flush_interval - (time.time() - last_flush_time))
                item = self._queue.get(timeout=timeout)
                buffer.append(item)
                self._queue.task_done()
            except queue.Empty:
                pass

            should_flush = (
                len(buffer) >= self._batch_size
                or (buffer and time.time() - last_flush_time >= self._flush_interval)
                or (self._stop_event.is_set() and buffer)
            )

            if should_flush and buffer:
                self._flush_buffer(buffer)
                buffer = []
                last_flush_time = time.time()

            if time.time() - last_stats_time >= stats_interval:
                logger.info(
                    "K线写入器统计 | 接收: %d | 入队: %d | 写入: %d | 失败: %d | 队列: %d",
                    self._stats["received"],
                    self._stats["queued"],
                    self._stats["written"],
                    self._stats["failed"],
                    self._queue.qsize(),
                )
                last_stats_time = time.time()

        logger.info("K线写入线程已结束")

    def _flush_buffer(self, buffer: list[dict]) -> None:
        """将缓冲数据写入 Kafka（带重试）."""
        if not self._kafka:
            return

        for attempt in range(self._max_retries + 1):
            try:
                start_time = time.time()
                self._write_batch(buffer)
                elapsed = time.time() - start_time
                self._stats["written"] += len(buffer)
                logger.info(
                    "✓ K线批量写入成功: %d 条, 耗时 %.3fs, 队列剩余 %d",
                    len(buffer), elapsed, self._queue.qsize(),
                )
                return
            except Exception as e:
                self._stats["retries"] += 1
                if attempt < self._max_retries:
                    logger.warning(
                        "K线写入失败 (尝试 %d/%d): %s, %.1f秒后重试...",
                        attempt + 1, self._max_retries + 1, e, self._retry_delay,
                    )
                    time.sleep(self._retry_delay)
                else:
                    logger.error("✗ K线写入失败，已达最大重试次数，丢弃 %d 条数据", len(buffer))
                    self._stats["failed"] += len(buffer)

    def _write_batch(self, buffer: list[dict]) -> None:
        """将原始 WS 消息转换为标准格式并写入 Kafka."""
        assert self._kafka is not None

        records = []
        for item in buffer:
            k = item.get("k", {})
            event_time_ms = item.get("E", 0)
            records.append({
                "symbol": k.get("s", item.get("s", "UNKNOWN")),
                "interval": k.get("i", self._interval),
                "open_time": k.get("t", 0),
                "close_time": k.get("T", 0),
                "open": k.get("o", "0"),
                "high": k.get("h", "0"),
                "low": k.get("l", "0"),
                "close": k.get("c", "0"),
                "volume": k.get("v", "0"),
                "quote_volume": k.get("q", "0"),
                "trade_count": k.get("n", 0),
                "taker_buy_volume": k.get("V", "0"),
                "taker_buy_quote_volume": k.get("Q", "0"),
                "is_closed": k.get("x", False),
                "event_time": event_time_ms,
                "timestamp": (
                    datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc).isoformat()
                    if event_time_ms else None
                ),
            })

        self._kafka.write_kline_batch(records, self._kafka_topic)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s, 正在优雅停止 K线流...", sig_name)
        self.stop()

    def run(self) -> None:
        """启动 K线流和写入线程 (阻塞).

        通过 SIGINT (Ctrl+C) 或 SIGTERM 优雅退出。
        """
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        if self._write_kafka:
            from ..storage.kafka import KafkaStorage
            self._kafka = KafkaStorage(self._config)

        closed_info = "仅收盘K线" if self._closed_only else "所有K线更新"
        logger.info(
            "U本位 K线流写入器启动: interval=%s, symbols=%d, %s, "
            "batch_size=%d, flush_interval=%.1fs, kafka=%s",
            self._interval,
            len(self._symbols),
            closed_info,
            self._batch_size,
            self._flush_interval,
            self._write_kafka,
        )

        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

        self._stream = UsdtKlineStream(
            symbols=self._symbols,
            interval=self._interval,
            on_message=self._on_message,
            closed_only=self._closed_only,
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
        if self._writer_thread and self._writer_thread.is_alive():
            logger.info("等待 K线写入线程完成...")
            self._writer_thread.join(timeout=10)

        if self._kafka:
            self._kafka.close()

        logger.info(
            "K线写入器已停止 | 接收: %d | 写入: %d | 失败: %d | 重试: %d",
            self._stats["received"],
            self._stats["written"],
            self._stats["failed"],
            self._stats["retries"],
        )


def _default_print_handler(data: dict) -> None:
    """默认的 K线消息打印处理器."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    k = data.get("k", {})
    symbol = k.get("s", data.get("s", "UNKNOWN"))
    interval = k.get("i", "?")
    is_closed = k.get("x", False)
    open_time_ms = k.get("t", 0)
    if open_time_ms:
        open_dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        open_dt = "N/A"
    status = "✓ 已收盘" if is_closed else "  进行中"
    print(
        f"[{now_str}] {status} | {symbol:16s} | {interval} | "
        f"date={open_dt} | o={k.get('o','?'):>12s} h={k.get('h','?'):>12s} "
        f"l={k.get('l','?'):>12s} c={k.get('c','?'):>12s} | "
        f"vol={k.get('v','?'):>14s}"
    )


def run_usdt_kline_stream(
    symbols: list[str],
    interval: str = DEFAULT_INTERVAL,
    closed_only: bool = True,
    config: "BinanceConfig | None" = None,
    write_kafka: bool = False,
    enable_print: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    kafka_topic: str = "",
) -> None:
    """便捷函数: 启动 U本位 K线流.

    Args:
        symbols:        要订阅的合约列表。
        interval:       K 线间隔，默认 "1d"。
        closed_only:    仅保存已收盘的 K 线，默认 True。
        config:         Binance 配置，write_kafka=True 时必须提供。
        write_kafka:    是否发布到 Kafka。
        enable_print:   是否打印到控制台。
        batch_size:     批量写入大小。
        flush_interval: 最长刷新间隔 (秒)。
        kafka_topic:    Kafka Topic，空时使用 config.kafka_topic_kline_usdt。
    """
    if write_kafka and config is None:
        raise ValueError("write_kafka=True 时必须提供 config")
    if not write_kafka and config is None:
        # 仅打印模式，使用哑 config
        from ..config import BinanceConfig
        config = BinanceConfig(api_key="")

    assert config is not None

    writer = UsdtKlineStreamWriter(
        config,
        symbols=symbols,
        interval=interval,
        closed_only=closed_only,
        enable_print=enable_print,
        write_kafka=write_kafka,
        batch_size=batch_size,
        flush_interval=flush_interval,
        kafka_topic=kafka_topic,
    )
    writer.run()
