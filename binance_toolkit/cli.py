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


def _cmd_user_data_stream(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动用户数据流 WebSocket."""
    from .ws.user_data_stream import run_user_data_stream

    run_user_data_stream(
        config=tk._client.config,
        enable_print=not args.quiet,
    )


def _cmd_account_snapshot(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """获取账户每日资产快照."""
    from .collector.account_snapshot_collector import AccountSnapshotCollector

    account_types = [t.strip().upper() for t in args.account_types.split(",")]
    collector = AccountSnapshotCollector(
        tk._client.config,
        account_types=account_types,  # type: ignore[arg-type]
        limit=args.limit,
        start_time=args.start_time,
        end_time=args.end_time,
        enable_print=not args.quiet,
        write_kafka=args.write_kafka,
        kafka_topic=args.kafka_topic,
    )
    collector.run()


def _cmd_futures_pnl(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """显示合约未实现盈亏."""
    from .pnl.futures_pnl import parse_futures_positions, run_futures_pnl

    # 解析持仓参数
    positions = []
    if args.positions:
        # 格式: BTCUSDT:LONG:60000:0.1:10,ETHUSDT:SHORT:3000:1.0:5
        positions = parse_futures_positions(args.positions, fee_rate=args.fee_rate)

    if not positions:
        # 使用示例持仓
        print("未指定持仓，使用示例数据。使用 --positions 参数指定实际持仓。")
        print("格式: --positions 'BTCUSDT:LONG:60000:0.1:10,ETHUSDT:SHORT:3000:1.0:5'")
        print("     (合约:方向:开仓价:数量:杠杆[:保证金类型])")
        positions = None  # 使用默认示例

    # 判断是否需要写入 Kafka
    write_kafka = args.write_kafka
    config = tk._client.config if write_kafka else None
    enable_print = not args.quiet

    run_futures_pnl(
        positions=positions,
        update_speed=args.speed,
        print_interval=args.interval,
        config=config,
        write_kafka=write_kafka,
        kafka_topic=args.kafka_topic,
        enable_print=enable_print,
    )


def _cmd_futures_positions(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """查询 U 本位合约当前持仓（通过 WebSocket API）."""
    from .ws.futures_trade_ws import FuturesTradeWsClient
    from .storage.kafka import KafkaStorage
    from .storage.clickhouse import ClickHousePositionStorage

    config = tk._client.config
    kafka_storage = None
    ch_storage = None

    if args.write_kafka:
        kafka_storage = KafkaStorage(config)
    if args.write_clickhouse:
        ch_storage = ClickHousePositionStorage(
            url=config.clickhouse_signal_url or "",
            database=config.clickhouse_database,
            user=config.clickhouse_user,
            password=config.clickhouse_password,
            timeout=config.clickhouse_timeout,
        )

    kafka_topic = args.kafka_topic or "binance.position.usdt_futures"
    symbol = args.symbol.strip().upper() if args.symbol else None

    try:
        with FuturesTradeWsClient(
            config,
            kafka_storage=kafka_storage,
            kafka_topic=kafka_topic.replace(".position.", ".trade."),
        ) as client:
            positions = client.query_position(symbol=symbol)

        # ClickHouse 直写：TRUNCATE + INSERT 活跃持仓
        if ch_storage is not None:
            from datetime import datetime, timezone
            ch_storage.write_current_positions(positions, queried_at=datetime.now(timezone.utc))

        # 过滤活跃持仓（positionAmt != 0）
        active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]

        if not active:
            print("当前无活跃持仓")
            return

        if args.json:
            import json as _json
            print(_json.dumps(active, indent=2, ensure_ascii=False))
        else:
            print(f"\n  {'合约':<16} {'方向':<8} {'数量':<18} {'开仓均价':<18} {'标记价格':<18} {'未实现盈亏':<18} {'杠杆':<6} {'保证金':<8} {'强平价格'}")
            print("  " + "─" * 130)
            for p in active:
                pnl = float(p.get("unRealizedProfit", 0))
                print(
                    f"  {p.get('symbol',''):<16}"
                    f" {p.get('positionSide',''):<8}"
                    f" {p.get('positionAmt',''):<18}"
                    f" {p.get('entryPrice',''):<18}"
                    f" {p.get('markPrice',''):<18}"
                    f" {pnl:+.4f}{'':10}"
                    f" {p.get('leverage','')+'x':<6}"
                    f" {p.get('marginType',''):<8}"
                    f" {p.get('liquidationPrice','')}"
                )
            total_pnl = sum(float(p.get("unRealizedProfit", 0)) for p in active)
            print(f"\n  合计未实现盈亏: {total_pnl:+.4f} USDT  (共 {len(active)} 个仓位)")
    finally:
        if kafka_storage:
            kafka_storage.close()
        if ch_storage:
            ch_storage.close()


def _cmd_futures_positions_sync_redis(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """持续通过 WS API 拉取仓位并同步到 Redis."""
    from .collector.futures_position_redis_collector import FuturesPositionRedisCollector

    collector = FuturesPositionRedisCollector(
        tk._client.config,
        symbol=args.symbol,
        interval_sec=args.interval,
        enable_print=not args.quiet,
    )
    collector.run()


def _cmd_ws_kline_usdt(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动 U 本位合约日 K 线 WebSocket 流."""
    from .ws.usdt_kline_stream import run_usdt_kline_stream

    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    write_kafka = args.write_kafka
    config = tk._client.config if write_kafka else None

    run_usdt_kline_stream(
        symbols=symbols,
        interval=args.interval,
        closed_only=not args.all_updates,
        config=config,
        write_kafka=write_kafka,
        enable_print=not args.quiet,
        batch_size=args.batch_size,
        flush_interval=args.flush_interval,
        kafka_topic=args.kafka_topic,
    )


def _parse_datetime_to_ms(value: str | None) -> int | None:
    """将 YYYY-MM-DD 或毫秒时间戳字符串解析为毫秒时间戳.

    支持格式:
      - 纯数字: 直接作为毫秒时间戳
      - YYYY-MM-DD: UTC 0点
      - YYYY-MM-DD HH:MM:SS: UTC 时间
    """
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(
        f"无法解析时间参数: {value!r}，支持格式: YYYY-MM-DD / YYYY-MM-DD HH:MM:SS / 毫秒时间戳"
    )


def _cmd_fetch_klines(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """拉取 U本位合约历史 K线（REST API，支持分页 + Kafka 写入）."""
    from datetime import datetime, timezone

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    start_ms = _parse_datetime_to_ms(args.start)
    end_ms = _parse_datetime_to_ms(args.end)

    kafka_storage = None
    if args.write_kafka:
        from .storage.kafka import KafkaStorage
        kafka_storage = KafkaStorage(tk._client.config)

    kafka_topic = args.kafka_topic or tk._client.config.kafka_topic_kline_usdt

    if start_ms:
        start_label = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        start_label = "最早"
    if end_ms:
        end_label = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        end_label = "现在"

    print(f"\n拉取 U本位合约历史 K线: interval={args.interval}, {start_label} ~ {end_label}")
    print(f"合约({len(symbols)}): {', '.join(symbols)}\n")

    try:
        total = 0
        for symbol in symbols:
            records = tk.futures_market.fetch_klines_range(
                symbol,
                args.interval,
                start_time=start_ms,
                end_time=end_ms,
                write_kafka=args.write_kafka,
                kafka_storage=kafka_storage,
                kafka_topic=kafka_topic,
                enable_print=not args.quiet,
            )
            total += len(records)

            if args.json and records:
                import json
                print(json.dumps(records, indent=2, ensure_ascii=False))
    finally:
        if kafka_storage:
            kafka_storage.close()

    if not args.quiet:
        print(f"\n全部完成，共拉取 {total} 条 K线")


def _cmd_fetch_oi(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """拉取 U本位合约持仓量统计（REST API，支持分页 + Kafka 写入）."""
    from datetime import datetime, timezone

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    start_ms = _parse_datetime_to_ms(args.start)
    end_ms = _parse_datetime_to_ms(args.end)

    kafka_storage = None
    if args.write_kafka:
        from .storage.kafka import KafkaStorage
        kafka_storage = KafkaStorage(tk._client.config)

    kafka_topic = args.kafka_topic or tk._client.config.kafka_topic_oi_usdt

    if start_ms:
        start_label = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    else:
        start_label = "最早"
    if end_ms:
        end_label = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    else:
        end_label = "现在"

    print(f"\n拉取 U本位合约持仓量统计: period={args.period}, {start_label} ~ {end_label}")
    print(f"合约({len(symbols)}): {', '.join(symbols)}")
    print("注意: Binance 仅保留最近 1 个月的数据\n")

    try:
        total = 0
        for symbol in symbols:
            records = tk.futures_market.fetch_oi_range(
                symbol,
                args.period,
                start_time=start_ms,
                end_time=end_ms,
                write_kafka=args.write_kafka,
                kafka_storage=kafka_storage,
                kafka_topic=kafka_topic,
                enable_print=not args.quiet,
            )
            total += len(records)

            if args.json and records:
                import json
                print(json.dumps(records, indent=2, ensure_ascii=False))
    finally:
        if kafka_storage:
            kafka_storage.close()

    if not args.quiet:
        print(f"\n全部完成，共拉取 {total} 条持仓量统计")


def _cmd_engine_futures(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动策略引擎（ClickHouse Pull -> U本位交易动作）."""
    import dataclasses
    from .engine import FuturesStrategyEngine

    config = tk._client.config
    if args.port is not None:
        config = dataclasses.replace(config, engine_health_port=args.port)
    engine = FuturesStrategyEngine(config, dry_run=args.dry_run)
    engine.run()


def _cmd_engine_spot(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """启动现货策略引擎（ClickHouse Pull -> 现货交易动作）."""
    import dataclasses
    from .engine import SpotStrategyEngine

    config = tk._client.config
    if args.port is not None:
        config = dataclasses.replace(config, engine_health_port=args.port)
    engine = SpotStrategyEngine(config, dry_run=args.dry_run)
    engine.run()


def _cmd_spot_pnl(tk: BinanceToolkit, args: argparse.Namespace) -> None:
    """显示现货未实现盈亏."""
    from .pnl.spot_pnl import SpotPosition, run_spot_pnl

    # 解析持仓参数
    positions = []
    if args.positions:
        # 格式: BTC:60000:0.1,ETH:3000:1.5
        for pos_str in args.positions.split(","):
            parts = pos_str.strip().split(":")
            if len(parts) == 3:
                symbol, buy_price, quantity = parts
                positions.append(SpotPosition(
                    symbol=symbol.strip().upper(),
                    buy_price=float(buy_price),
                    quantity=float(quantity),
                    fee_rate=args.fee_rate,
                ))
    
    if not positions:
        # 使用示例持仓
        print("未指定持仓，使用示例数据。使用 --positions 参数指定实际持仓。")
        print("格式: --positions 'BTC:60000:0.1,ETH:3000:1.5'")
        positions = [
            SpotPosition("BTC", buy_price=60000.0, quantity=0.1, fee_rate=args.fee_rate),
            SpotPosition("ETH", buy_price=3000.0, quantity=1.0, fee_rate=args.fee_rate),
        ]

    # 判断是否需要写入 Kafka
    write_kafka = args.write_kafka
    config = tk._client.config if write_kafka else None
    enable_print = not args.quiet

    run_spot_pnl(
        positions=positions,
        update_speed=args.speed,
        print_interval=args.interval,
        config=config,
        write_kafka=write_kafka,
        kafka_topic=args.kafka_topic,
        enable_print=enable_print,
    )


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

    # user-data-stream (用户数据流)
    p = sub.add_parser(
        "user-data-stream",
        help="订阅用户数据流 (账户更新、余额变动、订单状态)",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印事件到控制台",
    )

    # account-snapshot (账户每日快照)
    p = sub.add_parser(
        "account-snapshot",
        help="获取账户每日资产快照 (SPOT/MARGIN/FUTURES)",
    )
    p.add_argument(
        "--type", dest="account_types", default="SPOT,MARGIN,FUTURES",
        metavar="TYPE[,TYPE...]",
        help="账户类型, 逗号分隔: SPOT / MARGIN / FUTURES (默认全部)",
    )
    p.add_argument(
        "--limit", type=int, default=7, metavar="7~30",
        help="每种账户类型返回的快照条数, 范围 7~30 (默认 7)",
    )
    p.add_argument(
        "--start", dest="start_time", type=int, default=None, metavar="MS",
        help="起始时间 (毫秒时间戳), 可选",
    )
    p.add_argument(
        "--end", dest="end_time", type=int, default=None, metavar="MS",
        help="结束时间 (毫秒时间戳), 可选",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将快照数据发布到 Kafka (需配置 kafka_bootstrap_servers)",
    )
    p.add_argument(
        "--kafka-topic", default="binance.account.snapshot",
        help="Kafka Topic 名称, 默认 binance.account.snapshot",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印到控制台",
    )

    # ws-kline-usdt (U本位合约日 K 线 WebSocket 流)
    p = sub.add_parser(
        "ws-kline-usdt",
        help="启动 U 本位合约 K 线 WebSocket 流（默认日 K 线，仅收盘蜡烛）",
    )
    p.add_argument(
        "--symbols", default="BTCUSDT",
        help="合约交易对, 多个用逗号分隔 (默认 BTCUSDT)",
    )
    p.add_argument(
        "--interval", default="1d",
        choices=["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"],
        help="K 线间隔, 默认 1d",
    )
    p.add_argument(
        "--all-updates", action="store_true",
        help="保存所有 K 线更新（含未收盘），默认仅保存已收盘 K 线",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将数据发布到 Kafka (需要配置 kafka_bootstrap_servers)",
    )
    p.add_argument(
        "--kafka-topic", default="",
        help="Kafka Topic 名称, 默认 binance.kline.usdt_futures",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印到控制台",
    )
    p.add_argument(
        "--batch-size", type=int, default=200,
        help="批量写入大小, 默认 200 条",
    )
    p.add_argument(
        "--flush-interval", type=float, default=2.0,
        help="最长刷新间隔 (秒), 默认 2.0",
    )

    # fetch-klines (历史 K线拉取)
    p = sub.add_parser(
        "fetch-klines",
        help="拉取 U本位合约历史 K线 (REST API, 支持分页 + Kafka 写入)",
    )
    p.add_argument(
        "--symbols", default="BTCUSDT",
        help="合约交易对, 多个用逗号分隔 (默认 BTCUSDT)",
    )
    p.add_argument(
        "--interval", default="1d",
        choices=["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"],
        help="K 线间隔, 默认 1d",
    )
    p.add_argument(
        "--start", default=None, metavar="DATE_OR_MS",
        help="起始时间, 支持 YYYY-MM-DD / 毫秒时间戳, 省略则从最早数据开始",
    )
    p.add_argument(
        "--end", default=None, metavar="DATE_OR_MS",
        help="截止时间, 支持 YYYY-MM-DD / 毫秒时间戳, 省略则到当前时间",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将 K线数据发布到 Kafka (需要配置 kafka_bootstrap_servers)",
    )
    p.add_argument(
        "--kafka-topic", default="",
        help="Kafka Topic, 默认 binance.kline.usdt_futures",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印进度",
    )
    p.add_argument(
        "--json", action="store_true",
        help="将结果以 JSON 格式打印到控制台 (调试用)",
    )

    # fetch-oi (持仓量统计拉取)
    p = sub.add_parser(
        "fetch-oi",
        help="拉取 U本位合约持仓量统计 (REST API, 支持分页 + Kafka 写入, 近 1 个月)",
    )
    p.add_argument(
        "--symbols", default="BTCUSDT",
        help="合约交易对, 多个用逗号分隔 (默认 BTCUSDT)",
    )
    p.add_argument(
        "--period", default="1h",
        choices=["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
        help="统计周期, 默认 1h",
    )
    p.add_argument(
        "--start", default=None, metavar="DATE_OR_MS",
        help="起始时间, 支持 YYYY-MM-DD / 毫秒时间戳, 省略则从最早可用数据开始",
    )
    p.add_argument(
        "--end", default=None, metavar="DATE_OR_MS",
        help="截止时间, 支持 YYYY-MM-DD / 毫秒时间戳, 省略则到当前时间",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将 OI 数据发布到 Kafka (需要配置 kafka_bootstrap_servers)",
    )
    p.add_argument(
        "--kafka-topic", default="",
        help="Kafka Topic, 默认 binance.oi.usdt_futures",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印进度",
    )
    p.add_argument(
        "--json", action="store_true",
        help="将结果以 JSON 格式打印到控制台 (调试用)",
    )

    # engine-futures (U本位合约策略引擎)
    p = sub.add_parser(
        "engine-futures",
        help="启动 U 本位合约策略引擎 (ClickHouse Pull 信号源, market='futures')",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="演练模式: 不真实下单/撤单, 仅走引擎状态流转",
    )
    p.add_argument(
        "--port", type=int, default=None, metavar="PORT",
        help="健康检查监听端口 (覆盖 config.json 中的 engine_health_port)",
    )

    # engine-spot (现货策略引擎)
    p = sub.add_parser(
        "engine-spot",
        help="启动现货策略引擎 (ClickHouse Pull 信号源, market='spot')",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="演练模式: 不真实下单/撤单, 仅走引擎状态流转",
    )
    p.add_argument(
        "--port", type=int, default=None, metavar="PORT",
        help="健康检查监听端口 (覆盖 config.json 中的 engine_health_port)",
    )

    # spot-pnl (现货未实现盈亏)
    p = sub.add_parser("spot-pnl", help="显示现货未实现盈亏 (使用 U 本位合约 index 价格)")
    p.add_argument(
        "--positions", default=None,
        help="持仓列表, 格式: 'BTC:买入价:数量,ETH:买入价:数量' 例如: 'BTC:60000:0.1,ETH:3000:1.5'",
    )
    p.add_argument(
        "--fee-rate", type=float, default=0.0002,
        help="交易手续费率, 默认 0.0002 (0.02%%)",
    )
    p.add_argument(
        "--speed", default="1s", choices=["1s", "3s"],
        help="价格更新速度: 1s (每秒) 或 3s (每3秒), 默认 1s",
    )
    p.add_argument(
        "--interval", type=float, default=1.0,
        help="盈亏打印/写入间隔秒数, 默认 1.0",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将 PnL 数据发布到 Kafka",
    )
    p.add_argument(
        "--kafka-topic", default="binance.pnl.spot",
        help="Kafka Topic 名称, 默认 binance.pnl.spot",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印到控制台",
    )

    # futures-pnl (合约未实现盈亏)
    p = sub.add_parser("futures-pnl", help="显示合约未实现盈亏 (支持 U 本位和币本位)")
    p.add_argument(
        "--positions", default=None,
        help="持仓列表, 格式: '合约:方向:开仓价:数量:杠杆[:保证金类型]' "
             "例如: 'BTCUSDT:LONG:60000:0.1:10,ETHUSDT:SHORT:3000:1.0:5'",
    )
    p.add_argument(
        "--fee-rate", type=float, default=0.0004,
        help="交易手续费率, 默认 0.0004 (0.04%% Taker)",
    )
    p.add_argument(
        "--speed", default="1s", choices=["1s", "3s"],
        help="价格更新速度: 1s (每秒) 或 3s (每3秒), 默认 1s",
    )
    p.add_argument(
        "--interval", type=float, default=1.0,
        help="盈亏打印/写入间隔秒数, 默认 1.0",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将 PnL 数据发布到 Kafka",
    )
    p.add_argument(
        "--kafka-topic", default="binance.pnl.futures",
        help="Kafka Topic 名称, 默认 binance.pnl.futures",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印到控制台",
    )

    # futures-positions (查询 U 本位合约持仓)
    p = sub.add_parser(
        "futures-positions",
        help="查询 U 本位合约当前持仓 (WebSocket API, 需要签名配置)",
    )
    p.add_argument(
        "--symbol", default=None,
        help="指定合约交易对, 如 BTCUSDT。省略则返回所有活跃持仓",
    )
    p.add_argument(
        "--write-kafka", "-k", action="store_true",
        help="将持仓快照发布到 Kafka (需要配置 kafka_bootstrap_servers)",
    )
    p.add_argument(
        "--kafka-topic", default="",
        help="Kafka Topic, 默认 binance.position.usdt_futures",
    )
    p.add_argument(
        "--write-clickhouse", "-c", action="store_true",
        help="将当前持仓写入 ClickHouse (TRUNCATE + INSERT, 需要配置 clickhouse_signal_url)",
    )
    p.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式打印原始响应（调试用）",
    )

    # futures-positions-sync-redis (仓位同步到 Redis)
    p = sub.add_parser(
        "futures-positions-sync-redis",
        help="通过 WebSocket API 持续获取 U 本位仓位并维护到 Redis",
    )
    p.add_argument(
        "--symbol", default=None,
        help="指定合约交易对, 如 BTCUSDT。省略则同步全部活跃仓位",
    )
    p.add_argument(
        "--interval", type=float, default=None,
        help="同步间隔秒数。省略则使用配置 redis_position_sync_interval_sec",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式, 不打印每次同步摘要",
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
    "user-data-stream": _cmd_user_data_stream,
    "account-snapshot": _cmd_account_snapshot,
    "spot-pnl": _cmd_spot_pnl,
    "futures-pnl": _cmd_futures_pnl,
    "ws-kline-usdt": _cmd_ws_kline_usdt,
    "fetch-klines": _cmd_fetch_klines,
    "fetch-oi": _cmd_fetch_oi,
    "futures-positions": _cmd_futures_positions,
    "futures-positions-sync-redis": _cmd_futures_positions_sync_redis,
    "engine-futures": _cmd_engine_futures,
    "engine-spot": _cmd_engine_spot,
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

    # 若配置文件中指定了 log_level 且命令行未显式传 --verbose，则以配置文件为准
    if not getattr(args, "verbose", False):
        cfg_level = getattr(logging, config.log_level, None)
        if isinstance(cfg_level, int):
            logging.getLogger().setLevel(cfg_level)

    handler = _COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    with BinanceToolkit(config) as tk:
        handler(tk, args)
