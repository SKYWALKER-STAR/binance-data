"""User Data Stream API.

用于管理用户数据流的 Listen Key，以及通过 WebSocket 接收账户更新、订单更新等事件。

文档: https://developers.binance.com/docs/binance-spot-api-docs/user-data-stream
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import BaseAPI

if TYPE_CHECKING:
    pass


class UserDataStreamAPI(BaseAPI):
    """用户数据流 API.
    
    用于创建、延长和关闭 Listen Key，以订阅用户数据流。
    """
    
    # Listen Key 有效期为 60 分钟，需要定期 keepalive
    LISTEN_KEY_EXPIRE_MINUTES = 60
    
    def create_listen_key(self) -> dict[str, Any]:
        """创建新的 Listen Key.
        
        POST /api/v3/userDataStream
        
        Returns:
            包含 listenKey 的字典，如:
            {"listenKey": "pqia91ma19a5s61cv6a81va65sdf19v8a65a1a5s61cv6a81va65sdf19v8a65a1"}
        
        注意:
            - Listen Key 有效期为 60 分钟
            - 需要定期调用 keepalive 延长有效期
        """
        return self._client.post("/api/v3/userDataStream")
    
    def keepalive_listen_key(self, listen_key: str) -> dict[str, Any]:
        """延长 Listen Key 有效期.
        
        PUT /api/v3/userDataStream
        
        Args:
            listen_key: 要延长的 Listen Key
        
        Returns:
            空字典 {} 表示成功
        
        注意:
            - 建议每 30 分钟调用一次
            - 如果 24 小时内没有 keepalive，Listen Key 会过期
        """
        return self._client.put(
            "/api/v3/userDataStream",
            data={"listenKey": listen_key},
        )
    
    def delete_listen_key(self, listen_key: str) -> dict[str, Any]:
        """关闭 Listen Key (终止用户数据流).
        
        DELETE /api/v3/userDataStream
        
        Args:
            listen_key: 要关闭的 Listen Key
        
        Returns:
            空字典 {} 表示成功
        """
        return self._client.delete(
            "/api/v3/userDataStream",
            params={"listenKey": listen_key},
        )
