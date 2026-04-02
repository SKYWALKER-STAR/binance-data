"""签名/鉴权模块.

支持两种鉴权方式:
  1. HMAC-SHA256 (secret_key)
  2. Ed25519 (private_key_path + password)
"""

from __future__ import annotations

import abc
import base64
import hashlib
import hmac
import time
import urllib.parse
from pathlib import Path
from typing import Any

from .config import BinanceConfig


class BaseSigner(abc.ABC):
    """签名策略基类."""

    @abc.abstractmethod
    def sign(self, payload: str) -> str:
        """对 payload 进行签名，返回签名字符串."""

    def prepare_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """为需要签名的请求添加 timestamp 和 signature."""
        params = dict(params)  # 浅拷贝，不修改原始参数
        params["timestamp"] = int(time.time() * 1000)
        payload = urllib.parse.urlencode(params, encoding="UTF-8")
        params["signature"] = self.sign(payload)
        return params


class HMACSigner(BaseSigner):
    """HMAC-SHA256 签名."""

    def __init__(self, secret_key: str):
        self._secret_key = secret_key.encode("utf-8")

    def sign(self, payload: str) -> str:
        return hmac.new(
            self._secret_key, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()


class Ed25519Signer(BaseSigner):
    """Ed25519 签名 (使用 PEM 私钥文件)."""

    def __init__(self, key_path: str | Path, password: str | None = None):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        key_path = Path(key_path)
        if not key_path.exists():
            raise FileNotFoundError(f"私钥文件未找到: {key_path}")
        with open(key_path, "rb") as f:
            pw = password.encode("utf-8") if password else None
            self._private_key = load_pem_private_key(data=f.read(), password=pw)

    def sign(self, payload: str) -> str:
        raw_signature = self._private_key.sign(payload.encode("ASCII"))
        return base64.b64encode(raw_signature).decode("ascii")


def create_signer(config: BinanceConfig) -> BaseSigner | None:
    """根据配置自动选择签名策略.

    优先使用 Ed25519，其次 HMAC，如果都没配置则返回 None（公开 API 不需要签名）。
    """
    if config.private_key_path:
        return Ed25519Signer(config.private_key_path, config.private_key_password)
    if config.secret_key:
        return HMACSigner(config.secret_key)
    return None
