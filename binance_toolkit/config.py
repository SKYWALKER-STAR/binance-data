"""配置管理模块.

支持从环境变量、.env 文件或 config.json 加载配置。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_DEFAULT_BASE_URL = "https://api.binance.com"
_DEFAULT_DAPI_BASE_URL = "https://dapi.binance.com"
_CONFIG_FILE_NAME = "config.json"


@dataclass(frozen=True)
class BinanceConfig:
    """Binance API 配置，不可变数据类."""

    api_key: str
    base_url: str = _DEFAULT_BASE_URL
    dapi_base_url: str = _DEFAULT_DAPI_BASE_URL
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

    # ---------- 工厂方法 ----------

    @classmethod
    def from_env(cls) -> "BinanceConfig":
        """从环境变量加载配置.

        环境变量:
            BINANCE_API_KEY        (必须)
            BINANCE_BASE_URL       (可选, 默认 https://api.binance.com)
            BINANCE_DAPI_BASE_URL  (可选, 默认 https://dapi.binance.com)
            BINANCE_PRIVATE_KEY    (可选, Ed25519 私钥路径)
            BINANCE_PRIVATE_KEY_PW (可选, 私钥密码)
            BINANCE_SECRET_KEY     (可选, HMAC 密钥)
            BINANCE_RECV_WINDOW    (可选, 默认 5000)
            BINANCE_TIMEOUT        (可选, 默认 10)
            INFLUX_HOST            (可选, InfluxDB 地址)
            INFLUX_DATABASE        (可选, InfluxDB 数据库名)
            INFLUX_MEASUREMENT     (可选, 默认 binance_ticker)
            INFLUX_FUTURES_MEASUREMENT (可选, 默认 binance_futures)
        """
        api_key = os.environ.get("BINANCE_API_KEY", "")
        if not api_key:
            raise ValueError("环境变量 BINANCE_API_KEY 未设置")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("BINANCE_BASE_URL", _DEFAULT_BASE_URL),
            dapi_base_url=os.environ.get("BINANCE_DAPI_BASE_URL", _DEFAULT_DAPI_BASE_URL),
            private_key_path=os.environ.get("BINANCE_PRIVATE_KEY"),
            private_key_password=os.environ.get("BINANCE_PRIVATE_KEY_PW"),
            secret_key=os.environ.get("BINANCE_SECRET_KEY"),
            recv_window=int(os.environ.get("BINANCE_RECV_WINDOW", "5000")),
            timeout=int(os.environ.get("BINANCE_TIMEOUT", "10")),
            influx_host=os.environ.get("INFLUX_HOST"),
            influx_database=os.environ.get("INFLUX_DATABASE"),
            influx_measurement=os.environ.get("INFLUX_MEASUREMENT", "binance_ticker"),
            influx_futures_measurement=os.environ.get("INFLUX_FUTURES_MEASUREMENT", "binance_futures"),
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
            private_key_path=data.get("private_key_path"),
            private_key_password=data.get("private_key_password"),
            secret_key=data.get("secret_key"),
            recv_window=data.get("recv_window", 5000),
            timeout=data.get("timeout", 10),
            influx_host=data.get("influx_host"),
            influx_database=data.get("influx_database"),
            influx_measurement=data.get("influx_measurement", "binance_ticker"),
            influx_futures_measurement=data.get("influx_futures_measurement", "binance_futures"),
        )
