"""账户每日快照采集器.

调用 GET /sapi/v1/accountSnapshot 获取账户的每日资产快照，
支持 SPOT（现货）、MARGIN（杠杆）、FUTURES（合约）三种账户类型。

功能:
  - 将快照数据格式化打印到控制台
  - 预留 Kafka 写入接口，后续可接入 Kafka → ClickHouse 管道

文档: https://developers.binance.com/docs/wallet/account/daily-account-snapshoot

用法:
    python -m binance_toolkit account-snapshot --type SPOT
    python -m binance_toolkit account-snapshot --type FUTURES --limit 30
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from ..config import BinanceConfig
from ..toolkit import BinanceToolkit

logger = logging.getLogger("binance_toolkit.collector")

AccountSnapshotType = Literal["SPOT", "MARGIN", "FUTURES"]


class AccountSnapshotCollector:
    """账户每日快照采集器.

    一次性拉取指定账户类型的每日资产快照，打印到控制台，
    并通过可选的 Kafka 写入接口将结构化数据推送到下游。

    设计说明:
        _write_kafka() 方法已预留接口，传入 write_kafka=True 并配置
        kafka_bootstrap_servers 后即可启用。KafkaStorage 中对应的
        write_account_snapshot() 方法亦已实现。

    用法:
        config = BinanceConfig.from_env()
        collector = AccountSnapshotCollector(
            config,
            account_types=["SPOT", "FUTURES"],
            limit=7,
        )
        collector.run()
    """

    def __init__(
        self,
        config: BinanceConfig,
        *,
        account_types: list[AccountSnapshotType] | None = None,
        limit: int = 7,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        enable_print: bool = True,
        write_kafka: bool = False,
        kafka_topic: str = "binance.account.snapshot",
    ):
        """
        Args:
            config:        Binance 配置（需要 API Key & Secret）。
            account_types: 要查询的账户类型列表，默认 ["SPOT", "MARGIN", "FUTURES"]。
            limit:         每种账户类型返回的快照条数，范围 7 ~ 30，默认 7。
            start_time:    查询起始时间（毫秒时间戳），可选。
            end_time:      查询结束时间（毫秒时间戳），可选。
            enable_print:  是否将结果打印到控制台，默认 True。
            write_kafka:   是否将结果发布到 Kafka，默认 False。
            kafka_topic:   Kafka Topic 名称，默认 "binance.account.snapshot"。
        """
        self._config = config
        self._account_types: list[AccountSnapshotType] = account_types or ["SPOT", "MARGIN", "FUTURES"]
        self._limit = limit
        self._start_time = start_time
        self._end_time = end_time
        self._enable_print = enable_print
        self._write_kafka = write_kafka
        self._kafka_topic = kafka_topic

    # ──────────────────────────────────────────────────────────
    #  公共入口
    # ──────────────────────────────────────────────────────────

    def run(self) -> None:
        """执行一次完整的账户快照采集（阻塞，执行完返回）."""
        with BinanceToolkit(self._config) as tk:
            kafka_storage = self._make_kafka_storage() if self._write_kafka else None
            try:
                for acct_type in self._account_types:
                    self._collect_one(tk, acct_type, kafka_storage)
            finally:
                if kafka_storage is not None:
                    kafka_storage.close()

    # ──────────────────────────────────────────────────────────
    #  内部实现
    # ──────────────────────────────────────────────────────────

    def _collect_one(
        self,
        tk: BinanceToolkit,
        account_type: AccountSnapshotType,
        kafka_storage: Any,
    ) -> None:
        """采集单一账户类型的快照数据."""
        try:
            result = tk.account.daily_snapshot(
                account_type,
                start_time=self._start_time,
                end_time=self._end_time,
                limit=self._limit,
            )
        except Exception:
            logger.exception("获取 %s 账户快照失败", account_type)
            return

        if self._enable_print:
            _print_snapshot_result(result)

        if kafka_storage is not None:
            self._write_to_kafka(kafka_storage, result)

    def _make_kafka_storage(self) -> Any:
        """创建 KafkaStorage 实例（懒加载）."""
        from ..storage.kafka import KafkaStorage
        return KafkaStorage(self._config)

    def _write_to_kafka(self, kafka_storage: Any, result: dict[str, Any]) -> None:
        """将快照结果推送到 Kafka."""
        snapshots: list[dict] = result.get("snapshotVos", [])
        if not snapshots:
            return
        try:
            kafka_storage.write_account_snapshot(snapshots, topic=self._kafka_topic)
            logger.info(
                "✓ 已推送 %d 条快照到 Kafka Topic [%s]",
                len(snapshots),
                self._kafka_topic,
            )
        except Exception:
            logger.exception("✗ 推送快照到 Kafka 失败")


# ──────────────────────────────────────────────────────────────
#  控制台打印
# ──────────────────────────────────────────────────────────────

def _ts_to_str(ts_ms: int) -> str:
    """将毫秒时间戳转换为可读字符串."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def _sep(char: str = "─", width: int = 68) -> None:
    print(char * width)


def _print_spot(snapshot: dict[str, Any]) -> None:
    data = snapshot.get("data", {})
    print(f"  日期           : {_ts_to_str(snapshot.get('updateTime', 0))}")
    print(f"  BTC 总估值     : {data.get('totalAssetOfBtc', 'N/A')} BTC")
    balances = [
        b for b in data.get("balances", [])
        if float(b.get("free", 0)) + float(b.get("locked", 0)) > 0
    ]
    if balances:
        print(f"  {'资产':<10} {'可用 (free)':<24} {'锁定 (locked)'}")
        for b in balances:
            print(f"  {b['asset']:<10} {b.get('free','0'):<24} {b.get('locked','0')}")
    else:
        print("  余额: (全部为零)")


def _print_margin(snapshot: dict[str, Any]) -> None:
    data = snapshot.get("data", {})
    print(f"  日期           : {_ts_to_str(snapshot.get('updateTime', 0))}")
    print(f"  保证金等级     : {data.get('marginLevel', 'N/A')}")
    print(f"  总资产 (BTC)   : {data.get('totalAssetOfBtc', 'N/A')}")
    print(f"  总负债 (BTC)   : {data.get('totalLiabilityOfBtc', 'N/A')}")
    print(f"  净资产 (BTC)   : {data.get('totalNetAssetOfBtc', 'N/A')}")
    assets = [
        a for a in data.get("userAssets", [])
        if any(float(a.get(k, 0)) != 0 for k in ("free", "locked", "borrowed", "netAsset"))
    ]
    if assets:
        print(f"  {'资产':<10} {'可用':<20} {'借入':<20} {'净资产'}")
        for a in assets:
            print(
                f"  {a.get('asset',''):<10} "
                f"{a.get('free','0'):<20} "
                f"{a.get('borrowed','0'):<20} "
                f"{a.get('netAsset','0')}"
            )
    else:
        print("  持仓: (无)")


def _print_futures(snapshot: dict[str, Any]) -> None:
    data = snapshot.get("data", {})
    print(f"  日期           : {_ts_to_str(snapshot.get('updateTime', 0))}")
    assets = data.get("assets", [])
    if assets:
        print(f"  {'资产':<10} {'钱包余额 (walletBalance)'}")
        for a in assets:
            print(f"  {a.get('asset',''):<10} {a.get('walletBalance','0')}")
    positions = [p for p in data.get("position", []) if float(p.get("positionAmt", 0)) != 0]
    if positions:
        print(f"  {'合约':<16} {'持仓量':<20} {'开仓价 (entryPrice)'}")
        for p in positions:
            print(
                f"  {p.get('symbol',''):<16} "
                f"{p.get('positionAmt','0'):<20} "
                f"{p.get('entryPrice','0')}"
            )
    else:
        print("  合约持仓: (无持仓)")


_PRINTERS = {
    "spot": _print_spot,
    "margin": _print_margin,
    "futures": _print_futures,
}


def _print_snapshot_result(result: dict[str, Any]) -> None:
    """格式化打印 daily_snapshot() 的返回结果."""
    code = result.get("code", -1)
    msg = result.get("msg", "")
    snapshots: list[dict] = result.get("snapshotVos", [])

    _sep("═")
    print("  Binance 每日账户快照")
    _sep("═")

    if code != 200:
        print(f"  [错误] code={code}  msg={msg!r}")
        _sep("═")
        return

    if not snapshots:
        print("  (无快照数据)")
        _sep("═")
        return

    acct_type = snapshots[0].get("type", "").lower()
    printer = _PRINTERS.get(acct_type)
    print(f"  账户类型: {acct_type.upper()}    共 {len(snapshots)} 条快照")
    _sep()

    for i, snap in enumerate(snapshots, start=1):
        print(f"  [{i}/{len(snapshots)}]")
        if printer:
            printer(snap)
        if i < len(snapshots):
            _sep("·")

    _sep("═")
