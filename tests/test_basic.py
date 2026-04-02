"""binance_toolkit 基础测试."""

from binance_toolkit.config import BinanceConfig
from binance_toolkit.toolkit import BinanceToolkit


def test_config_creation():
    """测试手动创建配置."""
    config = BinanceConfig(api_key="test_key")
    assert config.api_key == "test_key"
    assert config.base_url == "https://api.binance.com"
    assert config.timeout == 10


def test_toolkit_has_modules():
    """测试 toolkit 门面正确挂载所有模块."""
    config = BinanceConfig(api_key="test_key")
    tk = BinanceToolkit(config)
    assert hasattr(tk, "market")
    assert hasattr(tk, "trade")
    assert hasattr(tk, "account")
    tk.close()
