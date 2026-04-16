"""配置管理模块.

支持从环境变量、.env 文件或 config.json 加载配置。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_DEFAULT_BASE_URL = "https://api.binance.com"
_DEFAULT_DAPI_BASE_URL = "https://dapi.binance.com"
_DEFAULT_FAPI_BASE_URL = "https://fapi.binance.com"
_DEFAULT_FAPI_WS_URL = "wss://fstream.binance.com/ws"
_DEFAULT_SPOT_WS_URL = "wss://ws-api.binance.com:443/ws-api/v3"
_CONFIG_FILE_NAME = "config.json"


@dataclass(frozen=True)
class BinanceConfig:
    """Binance API 配置，不可变数据类."""

    api_key: str
    base_url: str = _DEFAULT_BASE_URL
    dapi_base_url: str = _DEFAULT_DAPI_BASE_URL
    fapi_base_url: str = _DEFAULT_FAPI_BASE_URL
    fapi_ws_url: str = _DEFAULT_FAPI_WS_URL  # U本位合约 WebSocket 地址
    spot_ws_url: str = _DEFAULT_SPOT_WS_URL  # 现货 WebSocket API 地址
    private_key_path: Optional[str] = None
    private_key_password: Optional[str] = None
    secret_key: Optional[str] = None
    recv_window: int = 5000
    timeout: int = 10

    # InfluxDB (可选, 用于数据采集存储)
    influx_host: Optional[str] = None
    influx_database: Optional[str] = None
    influx_measurement: str = "binance_ticker"
    influx_futures_measurement: str = "binance_futures"

    # Kafka (可选, 用于实时数据流)
    kafka_bootstrap_servers: Optional[str] = None  # 逗号分隔, 如 "localhost:9092"
    kafka_topic_coin: str = "binance.mark_price.coin"    # 币本位合约标记价格 Topic
    kafka_topic_usdt: str = "binance.mark_price.usdt"    # U本位合约标记价格 Topic
    kafka_topic_futures_trade: str = "binance.trade.usdt_futures"  # U本位合约交易结果 Topic
    kafka_topic_spot_trade: str = "binance.trade.spot"   # 现货交易结果 Topic
    kafka_topic_engine_events: str = "binance.engine.futures"      # 策略引擎审计 Topic
    kafka_topic_kline_usdt: str = "binance.kline.usdt_futures"    # U本位合约 K线 Topic

    # ClickHouse signal source (策略引擎 Pull)
    clickhouse_signal_url: Optional[str] = None
    clickhouse_database: str = "default"
    clickhouse_user: Optional[str] = None
    clickhouse_password: Optional[str] = None
    clickhouse_signal_table: str = "strategy_signals"
    clickhouse_signal_where: Optional[str] = None
    clickhouse_timeout: int = 10

    # Strategy Engine
    engine_state_db_path: str = ".state/strategy_engine.db"
    engine_poll_interval_sec: float = 1.0
    engine_reconcile_interval_sec: float = 5.0
    engine_reconcile_lag_sec: int = 2
    engine_reconcile_batch_size: int = 200
    engine_request_timeout: int = 10
    engine_startup_lookback_ms: int = 300000
    engine_clickhouse_batch_size: int = 200
    engine_max_notional_per_order: float = 0.0
    engine_max_actions_per_min_symbol: int = 120
    engine_health_host: str = "127.0.0.1"
    engine_health_port: int = 0
    log_level: str = "INFO"  # DEBUG / INFO / WARNING / ERROR

    # ---------- 工厂方法 ----------

    @classmethod
    def from_env(cls) -> "BinanceConfig":
        """从环境变量加载配置.

        环境变量:
            BINANCE_API_KEY        (必须)
            BINANCE_BASE_URL       (可选, 默认 https://api.binance.com)
            BINANCE_DAPI_BASE_URL  (可选, 默认 https://dapi.binance.com)
            BINANCE_FAPI_WS_URL    (可选, 默认 wss://fstream.binance.com/ws)
            BINANCE_SPOT_WS_URL    (可选, 默认 wss://ws-api.binance.com:443/ws-api/v3)
            BINANCE_PRIVATE_KEY    (可选, Ed25519 私钥路径)
            BINANCE_PRIVATE_KEY_PW (可选, 私钥密码)
            BINANCE_SECRET_KEY     (可选, HMAC 密钥)
            BINANCE_RECV_WINDOW    (可选, 默认 5000)
            BINANCE_TIMEOUT        (可选, 默认 10)
            INFLUX_HOST            (可选, InfluxDB 地址)
            INFLUX_DATABASE        (可选, InfluxDB 数据库名)
            INFLUX_MEASUREMENT     (可选, 默认 binance_ticker)
            INFLUX_FUTURES_MEASUREMENT (可选, 默认 binance_futures)
            KAFKA_BOOTSTRAP_SERVERS (可选, Kafka 地址, 逗号分隔)
            KAFKA_TOPIC_COIN          (可选, 币本位标记价格 Topic, 默认 binance.mark_price.coin)
            KAFKA_TOPIC_USDT          (可选, U本位标记价格 Topic, 默认 binance.mark_price.usdt)
            KAFKA_TOPIC_FUTURES_TRADE (可选, U本位合约交易结果 Topic, 默认 binance.trade.usdt_futures)
            KAFKA_TOPIC_SPOT_TRADE    (可选, 现货交易结果 Topic, 默认 binance.trade.spot)
            KAFKA_TOPIC_ENGINE_EVENTS (可选, 策略引擎审计 Topic, 默认 binance.engine.futures)
            CLICKHOUSE_SIGNAL_URL      (可选, ClickHouse HTTP 地址)
            CLICKHOUSE_DATABASE        (可选, 默认 default)
            CLICKHOUSE_USER            (可选)
            CLICKHOUSE_PASSWORD        (可选)
            CLICKHOUSE_SIGNAL_TABLE    (可选, 默认 strategy_signals)
            CLICKHOUSE_SIGNAL_WHERE    (可选, 额外过滤条件)
            CLICKHOUSE_TIMEOUT         (可选, 默认 10)
            ENGINE_STATE_DB_PATH       (可选, 默认 .state/strategy_engine.db)
            ENGINE_POLL_INTERVAL_SEC   (可选, 默认 1.0)
            ENGINE_RECONCILE_INTERVAL_SEC (可选, 默认 5.0)
            ENGINE_RECONCILE_LAG_SEC   (可选, 默认 2)
            ENGINE_RECONCILE_BATCH_SIZE (可选, 默认 200)
            ENGINE_REQUEST_TIMEOUT     (可选, 默认 10)
            ENGINE_STARTUP_LOOKBACK_MS (可选, 默认 300000)
            ENGINE_CLICKHOUSE_BATCH_SIZE (可选, 默认 200)
            ENGINE_MAX_NOTIONAL_PER_ORDER (可选, 默认 0 不限制)
            ENGINE_MAX_ACTIONS_PER_MIN_SYMBOL (可选, 默认 120)
            ENGINE_HEALTH_HOST         (可选, 默认 127.0.0.1)
            ENGINE_HEALTH_PORT         (可选, 默认 0 表示关闭)
        """
        api_key = os.environ.get("BINANCE_API_KEY", "")
        if not api_key:
            raise ValueError("环境变量 BINANCE_API_KEY 未设置")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("BINANCE_BASE_URL", _DEFAULT_BASE_URL),
            dapi_base_url=os.environ.get("BINANCE_DAPI_BASE_URL", _DEFAULT_DAPI_BASE_URL),
            fapi_base_url=os.environ.get("BINANCE_FAPI_BASE_URL", _DEFAULT_FAPI_BASE_URL),
            fapi_ws_url=os.environ.get("BINANCE_FAPI_WS_URL", _DEFAULT_FAPI_WS_URL),
            spot_ws_url=os.environ.get("BINANCE_SPOT_WS_URL", _DEFAULT_SPOT_WS_URL),
            private_key_path=os.environ.get("BINANCE_PRIVATE_KEY"),
            private_key_password=os.environ.get("BINANCE_PRIVATE_KEY_PW"),
            secret_key=os.environ.get("BINANCE_SECRET_KEY"),
            recv_window=int(os.environ.get("BINANCE_RECV_WINDOW", "5000")),
            timeout=int(os.environ.get("BINANCE_TIMEOUT", "10")),
            influx_host=os.environ.get("INFLUX_HOST"),
            influx_database=os.environ.get("INFLUX_DATABASE"),
            influx_measurement=os.environ.get("INFLUX_MEASUREMENT", "binance_ticker"),
            influx_futures_measurement=os.environ.get("INFLUX_FUTURES_MEASUREMENT", "binance_futures"),
            kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS"),
            kafka_topic_coin=os.environ.get("KAFKA_TOPIC_COIN", "binance.mark_price.coin"),
            kafka_topic_usdt=os.environ.get("KAFKA_TOPIC_USDT", "binance.mark_price.usdt"),
            kafka_topic_futures_trade=os.environ.get("KAFKA_TOPIC_FUTURES_TRADE", "binance.trade.usdt_futures"),
            kafka_topic_spot_trade=os.environ.get("KAFKA_TOPIC_SPOT_TRADE", "binance.trade.spot"),
            kafka_topic_engine_events=os.environ.get("KAFKA_TOPIC_ENGINE_EVENTS", "binance.engine.futures"),
            kafka_topic_kline_usdt=os.environ.get("KAFKA_TOPIC_KLINE_USDT", "binance.kline.usdt_futures"),
            clickhouse_signal_url=os.environ.get("CLICKHOUSE_SIGNAL_URL"),
            clickhouse_database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
            clickhouse_user=os.environ.get("CLICKHOUSE_USER"),
            clickhouse_password=os.environ.get("CLICKHOUSE_PASSWORD"),
            clickhouse_signal_table=os.environ.get("CLICKHOUSE_SIGNAL_TABLE", "strategy_signals"),
            clickhouse_signal_where=os.environ.get("CLICKHOUSE_SIGNAL_WHERE"),
            clickhouse_timeout=int(os.environ.get("CLICKHOUSE_TIMEOUT", "10")),
            engine_state_db_path=os.environ.get("ENGINE_STATE_DB_PATH", ".state/strategy_engine.db"),
            engine_poll_interval_sec=float(os.environ.get("ENGINE_POLL_INTERVAL_SEC", "1.0")),
            engine_reconcile_interval_sec=float(os.environ.get("ENGINE_RECONCILE_INTERVAL_SEC", "5.0")),
            engine_reconcile_lag_sec=int(os.environ.get("ENGINE_RECONCILE_LAG_SEC", "2")),
            engine_reconcile_batch_size=int(os.environ.get("ENGINE_RECONCILE_BATCH_SIZE", "200")),
            engine_request_timeout=int(os.environ.get("ENGINE_REQUEST_TIMEOUT", "10")),
            engine_startup_lookback_ms=int(os.environ.get("ENGINE_STARTUP_LOOKBACK_MS", "300000")),
            engine_clickhouse_batch_size=int(os.environ.get("ENGINE_CLICKHOUSE_BATCH_SIZE", "200")),
            engine_max_notional_per_order=float(os.environ.get("ENGINE_MAX_NOTIONAL_PER_ORDER", "0")),
            engine_max_actions_per_min_symbol=int(os.environ.get("ENGINE_MAX_ACTIONS_PER_MIN_SYMBOL", "120")),
            engine_health_host=os.environ.get("ENGINE_HEALTH_HOST", "127.0.0.1"),
            engine_health_port=int(os.environ.get("ENGINE_HEALTH_PORT", "0")),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )

    @classmethod
    def from_json(cls, path: str | Path | None = None) -> "BinanceConfig":
        """从 JSON 配置文件加载.

        Args:
            path: JSON 文件路径，默认在项目根目录下的 config.json
        """
        if path is None:
            path = Path(__file__).resolve().parent.parent / _CONFIG_FILE_NAME
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件未找到: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data: dict = json.load(f)
        return cls(
            api_key=data["api_key"],
            base_url=data.get("base_url", _DEFAULT_BASE_URL),
            dapi_base_url=data.get("dapi_base_url", _DEFAULT_DAPI_BASE_URL),
            fapi_base_url=data.get("fapi_base_url", _DEFAULT_FAPI_BASE_URL),
            fapi_ws_url=data.get("fapi_ws_url", _DEFAULT_FAPI_WS_URL),
            spot_ws_url=data.get("spot_ws_url", _DEFAULT_SPOT_WS_URL),
            private_key_path=data.get("private_key_path"),
            private_key_password=data.get("private_key_password"),
            secret_key=data.get("secret_key"),
            recv_window=data.get("recv_window", 5000),
            timeout=data.get("timeout", 10),
            influx_host=data.get("influx_host"),
            influx_database=data.get("influx_database"),
            influx_measurement=data.get("influx_measurement", "binance_ticker"),
            influx_futures_measurement=data.get("influx_futures_measurement", "binance_futures"),
            kafka_bootstrap_servers=data.get("kafka_bootstrap_servers"),
            kafka_topic_coin=data.get("kafka_topic_coin", "binance.mark_price.coin"),
            kafka_topic_usdt=data.get("kafka_topic_usdt", "binance.mark_price.usdt"),
            kafka_topic_futures_trade=data.get("kafka_topic_futures_trade", "binance.trade.usdt_futures"),
            kafka_topic_spot_trade=data.get("kafka_topic_spot_trade", "binance.trade.spot"),
            kafka_topic_engine_events=data.get("kafka_topic_engine_events", "binance.engine.futures"),
            kafka_topic_kline_usdt=data.get("kafka_topic_kline_usdt", "binance.kline.usdt_futures"),
            clickhouse_signal_url=data.get("clickhouse_signal_url"),
            clickhouse_database=data.get("clickhouse_database", "default"),
            clickhouse_user=data.get("clickhouse_user"),
            clickhouse_password=data.get("clickhouse_password"),
            clickhouse_signal_table=data.get("clickhouse_signal_table", "strategy_signals"),
            clickhouse_signal_where=data.get("clickhouse_signal_where"),
            clickhouse_timeout=data.get("clickhouse_timeout", 10),
            engine_state_db_path=data.get("engine_state_db_path", ".state/strategy_engine.db"),
            engine_poll_interval_sec=data.get("engine_poll_interval_sec", 1.0),
            engine_reconcile_interval_sec=data.get("engine_reconcile_interval_sec", 5.0),
            engine_reconcile_lag_sec=data.get("engine_reconcile_lag_sec", 2),
            engine_reconcile_batch_size=data.get("engine_reconcile_batch_size", 200),
            engine_request_timeout=data.get("engine_request_timeout", 10),
            engine_startup_lookback_ms=data.get("engine_startup_lookback_ms", 300000),
            engine_clickhouse_batch_size=data.get("engine_clickhouse_batch_size", 200),
            engine_max_notional_per_order=data.get("engine_max_notional_per_order", 0.0),
            engine_max_actions_per_min_symbol=data.get("engine_max_actions_per_min_symbol", 120),
            engine_health_host=data.get("engine_health_host", "127.0.0.1"),
            engine_health_port=data.get("engine_health_port", 0),
            log_level=str(data.get("log_level", "INFO")).upper(),
        )
