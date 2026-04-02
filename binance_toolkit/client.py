"""HTTP 客户端基类.

统一管理请求发送、鉴权、错误处理和响应解析。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from .auth import BaseSigner, create_signer
from .config import BinanceConfig
from .exceptions import BinanceAPIError, BinanceAuthError, BinanceRequestError

logger = logging.getLogger("binance_toolkit")


class BinanceClient:
    """Binance REST API 客户端.

    所有业务 API 模块通过组合此客户端来发送请求。
    """

    def __init__(self, config: BinanceConfig):
        self._config = config
        self._session = requests.Session()
        self._session.headers.update({"X-MBX-APIKEY": config.api_key})
        self._signer: Optional[BaseSigner] = create_signer(config)

    @property
    def config(self) -> BinanceConfig:
        return self._config

    # ---------- 公共请求方法 ----------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        """发送 HTTP 请求.

        Args:
            method: HTTP 方法 (GET, POST, PUT, DELETE).
            path:   API 路径, 例如 "/api/v3/ping".
            params: URL 查询参数.
            data:   POST body 参数.
            signed: 是否需要签名.

        Returns:
            解析后的 JSON 响应.

        Raises:
            BinanceAuthError: 签名所需配置缺失或服务端鉴权失败.
            BinanceRequestError: 网络级别错误.
            BinanceAPIError: Binance 业务级别错误.
        """
        url = f"{self._config.base_url}{path}"

        if signed:
            if self._signer is None:
                raise BinanceAuthError("需要签名但未配置 secret_key 或 private_key")
            target = params if method.upper() == "GET" else data
            if target is None:
                target = {}
            target["recvWindow"] = self._config.recv_window
            target = self._signer.prepare_params(target)
            if method.upper() == "GET":
                params = target
            else:
                data = target

        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                data=data,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            raise BinanceRequestError(f"请求失败: {exc}") from exc

        return self._handle_response(resp)

    def get(self, path: str, *, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        return self.request("GET", path, params=params, signed=signed)

    def post(self, path: str, *, data: dict[str, Any] | None = None, signed: bool = False) -> Any:
        return self.request("POST", path, data=data, signed=signed)

    def put(self, path: str, *, data: dict[str, Any] | None = None, signed: bool = False) -> Any:
        return self.request("PUT", path, data=data, signed=signed)

    def delete(self, path: str, *, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        return self.request("DELETE", path, params=params, signed=signed)

    # ---------- 内部方法 ----------

    @staticmethod
    def _handle_response(resp: requests.Response) -> Any:
        """统一处理响应，提取错误信息."""
        try:
            result = resp.json()
        except ValueError:
            raise BinanceAPIError(
                f"无法解析 JSON 响应: {resp.text}",
                status_code=resp.status_code,
            )

        if resp.status_code >= 400:
            error_code = result.get("code")
            error_msg = result.get("msg", resp.text)
            if resp.status_code in (401, 403) or error_code in (-2015, -2014, -1022):
                raise BinanceAuthError(
                    f"鉴权失败 [{error_code}]: {error_msg}",
                    status_code=resp.status_code,
                    error_code=error_code,
                    response=result,
                )
            raise BinanceAPIError(
                f"API 错误 [{error_code}]: {error_msg}",
                status_code=resp.status_code,
                error_code=error_code,
                response=result,
            )
        return result

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
