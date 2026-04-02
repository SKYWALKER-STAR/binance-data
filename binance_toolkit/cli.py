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


def _cmd_collect(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动价格采集常驻进程."""
    from .collector.price_collector import PriceCollector

    # 配置日志输出
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

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
    "collect": _cmd_collect,
}


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

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
