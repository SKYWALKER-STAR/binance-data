"""CLI 入口模块.

用法:
    python -m binance_toolkit ping
    python -m binance_toolkit price --symbol BTCUSDT
    python -m binance_toolkit klines --symbol ETHUSDT --interval 1h --limit 10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .config import BinanceConfig
from .toolkit import BinanceToolkit


def _json_print(data: Any) -> None:
    """美化输出 JSON."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ──────────────────────────────────────────────
# 子命令处理函数
# ──────────────────────────────────────────────

def _cmd_ping(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.ping())


def _cmd_time(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.server_time())


def _cmd_exchange_info(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.exchange_info(symbol=args.symbol))


def _cmd_price(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.ticker_price(symbol=args.symbol))


def _cmd_klines(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(
        tk.market.klines(
            symbol=args.symbol,
            interval=args.interval,
            limit=args.limit,
        )
    )


def _cmd_depth(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.depth(args.symbol, limit=args.limit))


def _cmd_ticker24(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.ticker_24hr(symbol=args.symbol))


def _cmd_avg_price(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.avg_price(args.symbol))


def _cmd_trades(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.market.recent_trades(args.symbol, limit=args.limit))


def _cmd_mark_price(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(
        tk.coin_futures.premium_index(
            symbol=args.symbol or None,
            pair=args.pair or None,
        )
    )


def _cmd_basis(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(
        tk.coin_futures.basis(
            pair=args.pair,
            contract_type=args.contract_type,
            period=args.period,
            limit=args.limit,
            start_time=args.start_time,
            end_time=args.end_time,
        )
    )


def _cmd_funding_info(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    _json_print(tk.coin_futures.funding_info())


def _cmd_coin_ws_mark_price(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动币本位合约标记价格 WebSocket 流."""
    from .ws.coin_mark_price_stream import run_mark_price_stream

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]

    # 判断是否需要写入数据库或 Kafka
    write_db = args.write_db
    write_kafka = args.write_kafka
    config = tk._client.config if (write_db or write_kafka) else None

    run_mark_price_stream(
        symbols=symbols,
        update_speed=args.speed,
        perp_only=not args.all,
        config=config,
        write_db=write_db,
        write_kafka=write_kafka,
        enable_print=not args.quiet,
        batch_size=args.batch_size,
        flush_interval=args.flush_interval,
        sample_interval=args.sample_interval,
    )


def _cmd_ws_mark_price_usdt(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动 U 本位合约标记价格 WebSocket 流."""
    from .ws.usdt_mark_price_stream import run_usdt_mark_price_stream

    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]

    # 判断是否需要写入数据库或 Kafka
    write_db = args.write_db
    write_kafka = args.write_kafka
    config = tk._client.config if (write_db or write_kafka) else None

    run_usdt_mark_price_stream(
        symbols=symbols,
        update_speed=args.speed,
        perp_only=not args.all,
        config=config,
        write_db=write_db,
        write_kafka=write_kafka,
        enable_print=not args.quiet,
        batch_size=args.batch_size,
        flush_interval=args.flush_interval,
        writer_threads=args.writer_threads,
        sample_interval=args.sample_interval,
    )


def _cmd_collect_mark(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动币本位合约标记价格/指数价格采集常驻进程."""
    from .collector.mark_price_collector import MarkPriceCollector

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    collector = MarkPriceCollector(
        tk._client.config,
        #symbols=symbols,
        interval=args.interval,
    )
    collector.run()


def _cmd_collect(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动价格采集常驻进程."""
    from .collector.price_collector import PriceCollector

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    collector = PriceCollector(
        tk._client.config,
        symbols=symbols,
        interval=args.interval,
    )
    collector.run()


# ──────────────────────────────────────────────
# 参数解析
# ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="binance-toolkit",
        description="Binance API 命令行工具箱",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="JSON 配置文件路径 (默认使用环境变量)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="日志文件路径, 指定后日志将同时写入该文件",
    )

    sub = parser.add_subparsers(dest="command", help="可用子命令")

    # ping
    sub.add_parser("ping", help="测试 API 连通性")

    # time
    sub.add_parser("time", help="获取服务器时间")

    # exchange-info
    p = sub.add_parser("exchange-info", help="获取交易所信息")
    p.add_argument("--symbol", default=None, help="交易对")

    # price
    p = sub.add_parser("price", help="获取最新价格")
    p.add_argument("--symbol", default=None, help="交易对 (省略返回全部)")

    # klines
    p = sub.add_parser("klines", help="获取 K 线数据")
    p.add_argument("--symbol", required=True, help="交易对")
    p.add_argument("--interval", default="1h", help="K 线间隔 (1m/5m/1h/1d 等)")
    p.add_argument("--limit", type=int, default=500, help="条数 (默认 500)")

    # depth
    p = sub.add_parser("depth", help="获取订单簿深度")
    p.add_argument("--symbol", required=True, help="交易对")
    p.add_argument("--limit", type=int, default=100, help="深度条数")

    # ticker24
    p = sub.add_parser("ticker24", help="24 小时价格变动统计")
    p.add_argument("--symbol", default=None, help="交易对")

    # avg-price
    p = sub.add_parser("avg-price", help="获取当前平均价格")
    p.add_argument("--symbol", required=True, help="交易对")

    # trades
    p = sub.add_parser("trades", help="获取最近成交记录")
    p.add_argument("--symbol", required=True, help="交易对")
    p.add_argument("--limit", type=int, default=500, help="条数")

    # basis (币本位合约基差数据)
    p = sub.add_parser("basis", help="查询币本位合约基差历史数据")
    p.add_argument("--pair", required=True, help="基础交易对, 如 BTCUSD")
    p.add_argument(
        "--contract-type", dest="contract_type", required=True,
        choices=["PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"],
        help="合约类型",
    )
    p.add_argument(
        "--period", required=True,
        choices=["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
        help="统计周期",
    )
    p.add_argument("--limit", type=int, default=30, help="返回条数, 默认 30, 最大 500")
    p.add_argument("--start-time", dest="start_time", type=int, default=None, help="起始时间 (毫秒时间戳)")
    p.add_argument("--end-time", dest="end_time", type=int, default=None, help="结束时间 (毫秒时间戳)")

    # mark-price (币本位合约标记价格/指数价格)
    p = sub.add_parser("mark-price", help="查询币本位合约的标记价格和指数价格")
    p.add_argument("--symbol", default=None, help="合约交易对, 如 BTCUSD_PERP (省略返回全部)")
    p.add_argument("--pair", default=None, help="基础交易对, 如 BTCUSD (省略返回全部)")

    # funding-info (币本位合约资金费率信息)
    sub.add_parser("funding-info", help="查询所有永续合约的资金费率信息")

    # ws-mark-price-coin (币本位合约标记价格 WebSocket 流)
    p = sub.add_parser(
        "ws-mark-price-coin",
        help="启动币本位合约标记价格 WebSocket 流",
    )
    p.add_argument(
        "--symbols", default=None,
        help="合约交易对, 多个用逗号分隔 (省略订阅全部)",
    )
    p.add_argument(
        "--speed", default="1s", choices=["1s", "3s"],
        help="更新速度: 1s (每秒) 或 3s (每3秒), 默认 1s",
    )
    p.add_argument(
        "--all", action="store_true",
        help="显示所有合约 (包括交割合约), 默认仅永续合约",
    )
    p.add_argument(
        "--write-db", "-w", action="store_true",
        help="将数据写入 InfluxDB",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将数据发布到 Kafka (需要配置 kafka_bootstrap_servers)",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印到控制台 (仅在 --write-db 或 --write-kafka 时有意义)",
    )
    p.add_argument(
        "--batch-size", type=int, default=100,
        help="批量写入大小, 默认 100 条",
    )
    p.add_argument(
        "--flush-interval", type=float, default=1.0,
        help="最长刷新间隔 (秒), 默认 1.0",
    )
    p.add_argument(
        "--sample-interval", type=int, default=0,
        help="采样间隔 (秒), 默认 0 不采样。设为 10 表示每个合约每 10 秒只存储一条数据，可大幅减少数据量",
    )

    # ws-mark-price-usdt (U本位合约标记价格 WebSocket 流)
    p = sub.add_parser(
        "ws-mark-price-usdt",
        help="启动 U 本位合约标记价格 WebSocket 流",
    )
    p.add_argument(
        "--symbols", default=None,
        help="合约交易对, 多个用逗号分隔 (省略订阅全部)",
    )
    p.add_argument(
        "--speed", default="1s", choices=["1s", "3s"],
        help="更新速度: 1s (每秒) 或 3s (每3秒), 默认 1s",
    )
    p.add_argument(
        "--all", action="store_true",
        help="显示所有合约 (包括交割合约), 默认仅永续合约",
    )
    p.add_argument(
        "--write-db", "-w", action="store_true",
        help="将数据写入 InfluxDB",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将数据发布到 Kafka (需要配置 kafka_bootstrap_servers)",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印到控制台 (仅在 --write-db 或 --write-kafka 时有意义)",
    )
    p.add_argument(
        "--batch-size", type=int, default=500,
        help="批量写入大小, 默认 500 条 (U本位合约数量多，需要更大批量)",
    )
    p.add_argument(
        "--flush-interval", type=float, default=1.0,
        help="最长刷新间隔 (秒), 默认 1.0",
    )
    p.add_argument(
        "--writer-threads", type=int, default=2,
        help="写入线程数, 默认 2 (用于并行写入提高吞吐量)",
    )
    p.add_argument(
        "--sample-interval", type=int, default=0,
        help="采样间隔 (秒), 默认 0 不采样。设为 10 表示每个合约每 10 秒只存储一条数据，可大幅减少数据量",
    )

    # collect-mark (币本位合约标记/指数价格常驻采集进程)
    p = sub.add_parser(
        "collect-mark",
        help="启动币本位合约标记价格/指数价格采集常驻进程, 定时写入 InfluxDB",
    )
    p.add_argument(
        "--symbols", default="BTCUSD_PERP",
        help="合约交易对, 多个用逗号分隔 (默认 BTCUSD_PERP)",
    )
    p.add_argument(
        "--interval", type=int, default=60,
        help="采集间隔秒数 (默认 60)",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="开启 DEBUG 日志",
    )

    # collect (常驻采集进程)
    p = sub.add_parser("collect", help="启动价格采集常驻进程, 定时写入 InfluxDB")
    p.add_argument(
        "--symbols", default="BTCUSDT",
        help="交易对, 多个用逗号分隔 (默认 BTCUSDT)",
    )
    p.add_argument(
        "--interval", type=int, default=60,
        help="采集间隔秒数 (默认 60)",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="开启 DEBUG 日志",
    )

    return parser


_COMMAND_MAP = {
    "ping": _cmd_ping,
    "time": _cmd_time,
    "exchange-info": _cmd_exchange_info,
    "price": _cmd_price,
    "klines": _cmd_klines,
    "depth": _cmd_depth,
    "ticker24": _cmd_ticker24,
    "avg-price": _cmd_avg_price,
    "trades": _cmd_trades,
    "basis": _cmd_basis,
    "mark-price": _cmd_mark_price,
    "funding-info": _cmd_funding_info,
    "ws-mark-price-coin": _cmd_coin_ws_mark_price,
    "ws-mark-price-usdt": _cmd_ws_mark_price_usdt,
    "collect-mark": _cmd_collect_mark,
    "collect": _cmd_collect,
}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 配置全局日志
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    log_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_datefmt = "%Y-%m-%d %H:%M:%S"
    if args.log_file:
        logging.basicConfig(
            level=log_level,
            format=log_fmt,
            datefmt=log_datefmt,
            filename=args.log_file,
            encoding="utf-8",
        )
    else:
        logging.basicConfig(
            level=log_level,
            format=log_fmt,
            datefmt=log_datefmt,
        )

    # 加载配置: 优先 --config 指定的文件, 其次自动查找 config.json, 最后用环境变量
    if args.config:
        config = BinanceConfig.from_json(args.config)
    else:
        # 尝试自动加载项目根目录下的 config.json
        default_cfg = Path(__file__).resolve().parent.parent / "config.json"
        if default_cfg.exists():
            config = BinanceConfig.from_json(default_cfg)
        else:
            try:
                config = BinanceConfig.from_env()
            except ValueError:
                # 对于不需要 API Key 的公开接口，允许空 key
                config = BinanceConfig(api_key="")

    handler = _COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    with BinanceToolkit(config) as tk:
        handler(tk, args)
