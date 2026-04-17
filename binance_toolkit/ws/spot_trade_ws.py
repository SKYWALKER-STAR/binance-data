"""现货 WebSocket 交易 API.

通过持久 WebSocket 连接与 Binance 现货交易服务交互，支持:
  - 下单         (order.place)
  - 撤销订单     (order.cancel)
  - 查询订单     (order.status)
  - 撤销全部订单 (openOrders.cancelAll)

每笔交易结果记录:
  - sent_at       : 交易发起时间 (发送请求的本地 UTC 时间)
  - transact_at   : 交易成交/更新时间 (来自响应中的 transactTime 字段)

交易结果通过 Kafka Topic ``binance.trade.spot`` 写入数据库。

文档参考:
  https://developers.binance.com/docs/binance-spot-api-docs/websocket-api/trading-requests
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

import websocket

from ..auth import create_signer
from ..exceptions import BinanceAPIError, BinanceAuthError

if TYPE_CHECKING:
    from ..auth import BaseSigner
    from ..config import BinanceConfig
    from ..storage.kafka import KafkaStorage

logger = logging.getLogger("binance_toolkit.ws.spot_trade")


# 请求超时秒数
_DEFAULT_TIMEOUT = 10

# WebSocket 重连最大等待秒数
_MAX_RECONNECT_WAIT = 60

# recv 读取超时秒数（长于请求超时，留给心跳检测用）
_RECV_TIMEOUT = 30

# Binance 要求每 3 分钟发一次 ping，否则服务端会关闭连接
_PING_INTERVAL = 150


class SpotTradeWsClient:
    """现货 WebSocket 交易客户端.

    维护一条持久 WebSocket 连接，以请求/响应方式调用 Binance 现货
    交易 WebSocket API。每笔操作的结果（含发起时间和成交时间）
    均会写入 Kafka。

    用法::

        from binance_toolkit.config import BinanceConfig
        from binance_toolkit.storage.kafka import KafkaStorage
        from binance_toolkit.ws.spot_trade_ws import SpotTradeWsClient

        config = BinanceConfig.from_env()
        kafka = KafkaStorage(config)

        with SpotTradeWsClient(config, kafka_storage=kafka) as client:
            result = client.new_order(
                symbol="BTCUSDT",
                side="BUY",
                order_type="LIMIT",
                quantity="0.001",
                price="60000",
                time_in_force="GTC",
            )
            print(result)
    """

    def __init__(
        self,
        config: "BinanceConfig",
        *,
        kafka_storage: Optional["KafkaStorage"] = None,
        kafka_topic: str = "binance.trade.spot",
        request_timeout: int = _DEFAULT_TIMEOUT,
    ):
        """
        Args:
            config:          Binance 配置（需要 api_key + secret_key 或 private_key）。
            kafka_storage:   Kafka 存储实例，传入时自动写入交易结果。
            kafka_topic:     目标 Kafka Topic，默认 ``binance.trade.spot``。
            request_timeout: 单次请求等待超时秒数，默认 10 秒。
        """
        self._config = config
        self._kafka = kafka_storage
        self._kafka_topic = kafka_topic
        self._timeout = request_timeout

        self._ws_url: str = config.spot_ws_url
        self._signer: Optional["BaseSigner"] = create_signer(config)
        if self._signer is None:
            raise BinanceAuthError("SpotTradeWsClient 需要签名配置 (secret_key 或 private_key_path)")

        self._ws: Optional[websocket.WebSocket] = None
        self._lock = threading.Lock()                     # 保护 ws 写操作
        self._pending: dict[str, _PendingRequest] = {}   # id -> 待处理请求
        self._recv_thread: Optional[threading.Thread] = None
        self._ping_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._connected = threading.Event()

        # 开机自动连接
        self._connect()

    # ------------------------------------------------------------------
    # 公开交易接口
    # ------------------------------------------------------------------

    def new_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        *,
        time_in_force: str | None = None,
        quantity: str | None = None,
        quote_order_qty: str | None = None,
        price: str | None = None,
        new_client_order_id: str | None = None,
        new_order_resp_type: str | None = None,
        stop_price: str | None = None,
        trailing_delta: int | None = None,
        iceberg_qty: str | None = None,
        strategy_id: int | None = None,
        strategy_type: int | None = None,
        self_trade_prevention_mode: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """下单.

        Args:
            symbol:                     交易对，如 ``"BTCUSDT"``。
            side:                       方向，``"BUY"`` 或 ``"SELL"``。
            order_type:                 订单类型，``"LIMIT"`` / ``"MARKET"`` /
                                        ``"LIMIT_MAKER"`` / ``"STOP_LOSS"`` /
                                        ``"STOP_LOSS_LIMIT"`` / ``"TAKE_PROFIT"`` /
                                        ``"TAKE_PROFIT_LIMIT"``。
            time_in_force:              有效方式，``"GTC"`` / ``"IOC"`` / ``"FOK"``。
            quantity:                   下单数量（基础货币）。
            quote_order_qty:            下单金额（报价货币，仅 MARKET 订单）。
            price:                      限价价格。
            new_client_order_id:        自定义订单 ID。
            new_order_resp_type:        响应类型，``"ACK"`` / ``"RESULT"`` / ``"FULL"``。
            stop_price:                 止损 / 止盈触发价。
            trailing_delta:             追踪止损 delta（BIPS）。
            iceberg_qty:                冰山订单显示数量。
            strategy_id:                策略 ID。
            strategy_type:              策略类型。
            self_trade_prevention_mode: 自成交保护模式。
            **kwargs:                   其他可选参数透传。

        Returns:
            Binance 响应 result 字典，包含 orderId、status、executedQty 等。
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        _maybe(params, "timeInForce", time_in_force)
        _maybe(params, "quantity", quantity)
        _maybe(params, "quoteOrderQty", quote_order_qty)
        _maybe(params, "price", price)
        _maybe(params, "newClientOrderId", new_client_order_id)
        _maybe(params, "newOrderRespType", new_order_resp_type)
        _maybe(params, "stopPrice", stop_price)
        _maybe(params, "trailingDelta", trailing_delta)
        _maybe(params, "icebergQty", iceberg_qty)
        _maybe(params, "strategyId", strategy_id)
        _maybe(params, "strategyType", strategy_type)
        _maybe(params, "selfTradePreventionMode", self_trade_prevention_mode)
        params.update(kwargs)
        return self._request("order.place", params, action="new_order")

    def cancel_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        new_client_order_id: str | None = None,
        cancel_restrictions: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """撤销订单.

        Args:
            symbol:                交易对。
            order_id:              订单 ID（与 orig_client_order_id 二选一）。
            orig_client_order_id:  自定义订单 ID（与 order_id 二选一）。
            new_client_order_id:   撤单后的新订单 ID（可选）。
            cancel_restrictions:   取消限制，``"ONLY_NEW"`` / ``"ONLY_PARTIALLY_FILLED"``。
            **kwargs:              其他可选参数透传。

        Returns:
            Binance 响应 result 字典，status 为 ``"CANCELED"``。
        """
        params: dict[str, Any] = {"symbol": symbol}
        _maybe(params, "orderId", order_id)
        _maybe(params, "origClientOrderId", orig_client_order_id)
        _maybe(params, "newClientOrderId", new_client_order_id)
        _maybe(params, "cancelRestrictions", cancel_restrictions)
        params.update(kwargs)
        return self._request("order.cancel", params, action="cancel_order")

    def query_order(
        self,
        symbol: str,
        *,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
        **kwargs: Any,
    ) -> dict:
        """查询订单状态.

        Args:
            symbol:                交易对。
            order_id:              订单 ID（与 orig_client_order_id 二选一）。
            orig_client_order_id:  自定义订单 ID（与 order_id 二选一）。
            **kwargs:              其他可选参数透传。

        Returns:
            Binance 响应 result 字典，包含当前订单状态。
        """
        params: dict[str, Any] = {"symbol": symbol}
        _maybe(params, "orderId", order_id)
        _maybe(params, "origClientOrderId", orig_client_order_id)
        params.update(kwargs)
        return self._request("order.status", params, action="query_order")

    def cancel_all_orders(
        self,
        symbol: str,
        **kwargs: Any,
    ) -> list[dict]:
        """撤销指定交易对的所有挂单.

        Args:
            symbol:   交易对。
            **kwargs: 其他可选参数透传。

        Returns:
            Binance 响应 result 列表，包含所有被撤销订单的信息。
        """
        params: dict[str, Any] = {"symbol": symbol}
        params.update(kwargs)
        return self._request_list("openOrders.cancelAll", params, action="cancel_all_orders")

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭 WebSocket 连接并释放资源."""
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=5)
        if self._ping_thread and self._ping_thread.is_alive():
            self._ping_thread.join(timeout=5)
        logger.info("SpotTradeWsClient 已关闭")

    def __enter__(self) -> "SpotTradeWsClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """建立 WebSocket 连接，启动接收线程和心跳线程."""
        self._connected.clear()
        attempt = 0
        while not self._stop_event.is_set():
            try:
                ws = websocket.create_connection(self._ws_url, timeout=self._timeout)
                # 连接成功后将 socket 读超时调大，避免空闲时 recv() 误报超时
                ws.sock.settimeout(_RECV_TIMEOUT)
                self._ws = ws
                self._connected.set()
                logger.info("已连接 Binance 现货 WebSocket: %s", self._ws_url)
                # 启动后台接收线程
                self._recv_thread = threading.Thread(
                    target=self._recv_loop,
                    daemon=True,
                    name="spot-trade-ws-recv",
                )
                self._recv_thread.start()
                # 启动心跳线程（每 150 秒发一次 ping，防止服务端断开）
                self._ping_thread = threading.Thread(
                    target=self._ping_loop,
                    daemon=True,
                    name="spot-trade-ws-ping",
                )
                self._ping_thread.start()
                return
            except Exception as exc:
                wait = min(2 ** attempt, _MAX_RECONNECT_WAIT)
                logger.warning("WebSocket 连接失败，%d 秒后重试: %s", wait, exc)
                attempt += 1
                self._stop_event.wait(wait)

    def _recv_loop(self) -> None:
        """后台线程：持续接收 WebSocket 消息并分发到等待的请求."""
        while not self._stop_event.is_set():
            try:
                raw = self._ws.recv()  # type: ignore[union-attr]
                if not raw:
                    continue
                msg: dict = json.loads(raw)
                req_id: str = msg.get("id", "")
                if req_id in self._pending:
                    self._pending[req_id].set_result(msg)
            except websocket.WebSocketConnectionClosedException:
                if self._stop_event.is_set():
                    break
                logger.warning("WebSocket 连接断开，尝试重连…")
                self._connected.clear()
                self._connect()
                break
            except (websocket.WebSocketTimeoutException, socket.timeout, TimeoutError):
                # recv 在空闲窗口内未收到消息，属于正常情况，继续等待
                logger.debug("[recv] 读取超时（无新消息），继续等待")
                continue
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.error("接收消息时出错: %s", exc)

    def _ping_loop(self) -> None:
        """后台心跳线程：定期发送 ping 防止服务端因空闲关闭连接."""
        while not self._stop_event.wait(_PING_INTERVAL):
            if not self._connected.is_set():
                continue
            try:
                with self._lock:
                    self._ws.ping()  # type: ignore[union-attr]
                logger.debug("[ping] 心跳已发送")
            except Exception as exc:
                logger.warning("[ping] 心跳发送失败: %s", exc)

    def _sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """为 WebSocket 请求参数注入 apiKey、timestamp、recvWindow 并签名.

        Binance WebSocket API 要求所有私有请求的 params 中包含:
          - ``apiKey``   ←→ HTTP 请求头中的 ``X-MBX-APIKEY``
          - ``timestamp``     毫秒时间戳
          - ``recvWindow``    时间窗口
          - ``signature``     对所有参数按字母序拼接后签名
        """
        params = dict(params)
        params["apiKey"] = self._config.api_key
        params["recvWindow"] = self._config.recv_window
        params["timestamp"] = int(time.time() * 1000)
        # 按键名字母序排序后拼接，用于签名
        sorted_pairs = sorted(params.items(), key=lambda kv: kv[0])
        payload = urllib.parse.urlencode(sorted_pairs)
        params["signature"] = self._signer.sign(payload)  # type: ignore[union-attr]
        return params

    def _request(self, method: str, params: dict[str, Any], *, action: str) -> dict:
        """发送 WebSocket 请求并等待响应.

        Args:
            method:  WebSocket API 方法名，如 ``"order.place"``。
            params:  请求参数（不含签名）。
            action:  操作名称，用于日志和 Kafka 消息标记。

        Returns:
            Binance 响应的 ``result`` 字典。

        Raises:
            BinanceAPIError:    Binance 业务级错误。
            TimeoutError:       在 ``request_timeout`` 内未收到响应。
            ConnectionError:    WebSocket 未连接。
        """
        if not self._connected.is_set():
            raise ConnectionError("WebSocket 未连接，请稍后重试")

        req_id = str(uuid.uuid4())
        signed_params = self._sign_params(params)
        message = json.dumps({"id": req_id, "method": method, "params": signed_params})

        pending = _PendingRequest()
        self._pending[req_id] = pending

        # 记录交易发起时间
        sent_at = datetime.now(timezone.utc)

        try:
            with self._lock:
                self._ws.send(message)  # type: ignore[union-attr]
            logger.debug("已发送 %s 请求 id=%s", method, req_id)

            if not pending.wait(timeout=self._timeout):
                raise TimeoutError(f"{method} 请求超时 (>{self._timeout}s), id={req_id}")

            response = pending.result
        finally:
            self._pending.pop(req_id, None)

        # 校验响应
        status = response.get("status", 0)
        if status != 200:
            error = response.get("error", {})
            raise BinanceAPIError(
                f"{method} 失败: {error.get('msg', '未知错误')}",
                status_code=status,
                error_code=error.get("code"),
                response=response,
            )

        result: dict = response["result"]

        # 计算成交/更新时间 (现货使用 transactTime 或 time)
        transact_time_ms: int | None = result.get("transactTime") or result.get("time")
        transact_at: datetime | None = None
        if transact_time_ms:
            transact_at = datetime.fromtimestamp(transact_time_ms / 1000, tz=timezone.utc)

        logger.info(
            "[%s] symbol=%s orderId=%s status=%s sent_at=%s transact_at=%s",
            action,
            result.get("symbol", ""),
            result.get("orderId", ""),
            result.get("status", ""),
            sent_at.isoformat(),
            transact_at.isoformat() if transact_at else "N/A",
        )

        # 写入 Kafka
        if self._kafka is not None:
            self._kafka.write_spot_trade(
                result,
                action=action,
                sent_at=sent_at,
                transact_at=transact_at,
                topic=self._kafka_topic,
            )

        return result

    def _request_list(self, method: str, params: dict[str, Any], *, action: str) -> list[dict]:
        """发送 WebSocket 请求并等待响应（返回列表）.

        Args:
            method:  WebSocket API 方法名，如 ``"openOrders.cancelAll"``。
            params:  请求参数（不含签名）。
            action:  操作名称，用于日志和 Kafka 消息标记。

        Returns:
            Binance 响应的 ``result`` 列表。

        Raises:
            BinanceAPIError:    Binance 业务级错误。
            TimeoutError:       在 ``request_timeout`` 内未收到响应。
            ConnectionError:    WebSocket 未连接。
        """
        if not self._connected.is_set():
            raise ConnectionError("WebSocket 未连接，请稍后重试")

        req_id = str(uuid.uuid4())
        signed_params = self._sign_params(params)
        message = json.dumps({"id": req_id, "method": method, "params": signed_params})

        pending = _PendingRequest()
        self._pending[req_id] = pending

        # 记录交易发起时间
        sent_at = datetime.now(timezone.utc)

        try:
            with self._lock:
                self._ws.send(message)  # type: ignore[union-attr]
            logger.debug("已发送 %s 请求 id=%s", method, req_id)

            if not pending.wait(timeout=self._timeout):
                raise TimeoutError(f"{method} 请求超时 (>{self._timeout}s), id={req_id}")

            response = pending.result
        finally:
            self._pending.pop(req_id, None)

        # 校验响应
        status = response.get("status", 0)
        if status != 200:
            error = response.get("error", {})
            raise BinanceAPIError(
                f"{method} 失败: {error.get('msg', '未知错误')}",
                status_code=status,
                error_code=error.get("code"),
                response=response,
            )

        result: list = response["result"]

        logger.info(
            "[%s] 共 %d 条记录, sent_at=%s",
            action,
            len(result),
            sent_at.isoformat(),
        )

        # 写入 Kafka（逐条写入）
        if self._kafka is not None:
            for item in result:
                # 处理订单和订单列表两种格式
                if "orderId" in item:
                    transact_time_ms = item.get("transactTime")
                    transact_at = None
                    if transact_time_ms:
                        transact_at = datetime.fromtimestamp(transact_time_ms / 1000, tz=timezone.utc)
                    self._kafka.write_spot_trade(
                        item,
                        action=action,
                        sent_at=sent_at,
                        transact_at=transact_at,
                        topic=self._kafka_topic,
                    )

        return result


class _PendingRequest:
    """单个等待中请求的容器，封装 Event + result 存储."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.result: dict = {}

    def set_result(self, data: dict) -> None:
        self.result = data
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout=timeout)


def _maybe(params: dict, key: str, value: Any) -> None:
    """若 value 不为 None，则将其写入 params[key]."""
    if value is not None:
        params[key] = value
