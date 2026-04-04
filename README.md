# Binance Toolkit

一个结构清晰、可扩展的 Binance API Python 工具箱。

## 项目结构

```
biannce-api/
├── binance_toolkit/          # 核心包
│   ├── __init__.py
│   ├── __main__.py           # python -m binance_toolkit 入口
│   ├── config.py             # 配置管理 (环境变量 / JSON)
│   ├── auth.py               # 鉴权签名 (HMAC-SHA256 / Ed25519)
│   ├── client.py             # HTTP 客户端基类
│   ├── exceptions.py         # 统一异常定义
│   ├── toolkit.py            # 门面类 — 统一入口
│   ├── cli.py                # 命令行接口
│   └── api/                  # 业务 API 模块
│       ├── base.py           # API 模块基类
│       ├── market.py         # 现货市场数据 (公开, 无需签名)
│       ├── coin_futures.py   # 币本位合约市场数据 (DAPI, 无需签名)
│       ├── trade.py          # 现货交易 (需要签名)
│       └── account.py        # 账户信息 (需要签名)
│   ├── ws/                   # WebSocket 模块
│   │   └── mark_price_stream.py  # 币本位合约标记价格实时流
│   ├── collector/            # 数据采集器
│   │   ├── price_collector.py        # 现货价格定时采集常驻进程
│   │   └── mark_price_collector.py   # 币本位合约标记/指数价格采集进程
│   └── storage/              # 存储后端
│       └── influxdb.py       # InfluxDB 写入器
├── tests/
│   └── test_basic.py
├── config.example.json       # 配置文件示例
├── .env.example              # 环境变量示例
├── pyproject.toml            # 项目元数据 & 依赖
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
cd biannce-api
pip install -e .
```

### 2. 配置

**方式一：环境变量**

```bash
cp .env.example .env
# 编辑 .env 填入真实 API Key
export $(cat .env | xargs)
```

**方式二：JSON 配置文件**

```bash
cp config.example.json config.json
# 编辑 config.json
```

### 3. 命令行使用

```bash
# 测试连通性
python -m binance_toolkit ping

# 获取最新价格
python -m binance_toolkit price --symbol BTCUSDT

# 获取 K 线数据
python -m binance_toolkit klines --symbol ETHUSDT --interval 1h --limit 10

# 获取订单簿深度
python -m binance_toolkit depth --symbol BTCUSDT --limit 20

# 24 小时行情
python -m binance_toolkit ticker24 --symbol BTCUSDT

# 查询币本位合约标记价格和指数价格
python -m binance_toolkit mark-price --symbol BTCUSD_PERP

# 查询某个基础交易对的全部合约
python -m binance_toolkit mark-price --pair BTCUSD

# 查询基差历史数据 (永续合约, 1h 周期, 最近 30 条)
python -m binance_toolkit basis --pair BTCUSD --contract-type PERPETUAL --period 1h

# 查询当季合约基差, 自定义条数
python -m binance_toolkit basis --pair BTCUSD --contract-type CURRENT_QUARTER --period 4h --limit 100

# 查询所有永续合约的资金费率信息
python -m binance_toolkit funding-info

# 查看帮助
python -m binance_toolkit --help
```

### 5. 价格采集常驻进程

定时获取价格并写入 InfluxDB，适合长期运行的数据采集任务。

**前置条件：** 安装 InfluxDB 依赖并配置连接信息。

```bash
pip install -e '.[influxdb]'
```

配置 InfluxDB 连接（环境变量或 config.json）：

```bash
export INFLUX_HOST=https://your-influxdb:8086
export INFLUX_DATABASE=binance
```

启动采集：  

```bash
# 默认: 每 60 秒采集 BTCUSDT 价格
python -m binance_toolkit collect

# 自定义: 多个交易对, 30 秒间隔, 开启调试日志
python -m binance_toolkit collect --symbols BTCUSDT,ETHUSDT --interval 30 -v

# Ctrl+C 优雅停止
```

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.collector.price_collector import PriceCollector

config = BinanceConfig.from_env()
collector = PriceCollector(
    config,
    symbols=["BTCUSDT", "ETHUSDT"],
    interval=60,
)
collector.run()  # 阻塞运行, Ctrl+C 停止
```

InfluxDB 中写入的数据格式：

| Measurement | Tag | Field | Timestamp |
|-------------|-----|-------|-----------|
| `binance_ticker` | `symbol=BTCUSDT` | `price=67123.45` | UTC 时间 |

### 6. 币本位合约标记价格/指数价格采集

定时采集币本位永续合约的标记价格和指数价格，写入 InfluxDB（使用 DAPI: `dapi.binance.com`，无需 API Key）。

**前置条件：** 同上，需安装 InfluxDB 依赖并配置连接信息。

```bash
# 每 60 秒采集所有永续合约的标记价格和指数价格
python -m binance_toolkit collect-mark

# 自定义采集间隔, 开启调试日志
python -m binance_toolkit collect-mark --interval 30 -v

# Ctrl+C 优雅停止
```

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.collector.mark_price_collector import MarkPriceCollector

config = BinanceConfig.from_env()
collector = MarkPriceCollector(
    config,
    interval=60,  # 每次自动采集所有永续合约
)
collector.run()  # 阻塞运行, Ctrl+C 停止
```

InfluxDB 中写入的数据格式：

| Measurement | Tag | Field | Timestamp |
|-------------|-----|-------|-----------|
| `binance_ticker` | `symbol=BTCUSD_PERP` | `mark_price`, `index_price`, `last_funding_rate`, `next_funding_time` | UTC 时间 |

### 7. 币本位合约标记价格 WebSocket 流

通过 WebSocket 实时获取币本位永续合约的标记价格和指数价格，支持打印到控制台和/或写入 InfluxDB。

```bash
# 仅打印到控制台 (调试模式)
python -m binance_toolkit ws-mark-price

# 写入 InfluxDB + 打印到控制台
python -m binance_toolkit ws-mark-price --write-db

# 仅写入 InfluxDB (静默模式)
python -m binance_toolkit ws-mark-price --write-db --quiet

# 自定义: 指定合约, 3秒更新, 批量写入参数
python -m binance_toolkit ws-mark-price --symbols BTCUSD_PERP,ETHUSD_PERP --speed 3s --write-db --batch-size 50

# Ctrl+C 优雅停止
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--symbols` | 指定合约，逗号分隔，省略订阅全部 |
| `--speed` | 更新速度 `1s` 或 `3s`，默认 `1s` |
| `--all` | 包含交割合约，默认仅永续合约 |
| `--write-db` / `-w` | 写入 InfluxDB |
| `--quiet` / `-q` | 不打印到控制台 |
| `--batch-size` | 批量写入条数，默认 100 |
| `--flush-interval` | 最长刷新间隔秒数，默认 1.0 |

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.ws import MarkPriceStream, MarkPriceStreamWriter

config = BinanceConfig.from_env()

# 方式一: 仅打印/自定义处理
stream = MarkPriceStream(
    symbols=None,  # 订阅全部
    update_speed="1s",
    on_message=lambda data: print(data),
    perp_only=True,
)
stream.run()

# 方式二: 写入 InfluxDB (带批量写入 + 重试机制)
writer = MarkPriceStreamWriter(
    config,
    enable_print=True,   # 同时打印到控制台
    batch_size=100,      # 每 100 条写入一次
    flush_interval=1.0,  # 或每 1 秒写入一次
)
writer.run()
```

**写入特性：**
- 内存队列缓冲，批量写入减少 IO
- 写入失败自动重试 3 次
- 优雅停止时确保缓冲数据写入
- 退出时输出统计信息

### 8. 币本位合约基差数据查询

查询特定合约基础交易对的基差历史数据，结果可写入 InfluxDB。

```bash
# 一次性查询 (命令行)
python -m binance_toolkit basis --pair BTCUSD --contract-type PERPETUAL --period 1h --limit 30
```

在代码中写入 InfluxDB：

```python
from datetime import datetime, timezone
from binance_toolkit.config import BinanceConfig
from binance_toolkit.toolkit import BinanceToolkit
from binance_toolkit.storage.influxdb import InfluxDBStorage

config = BinanceConfig.from_env()
with BinanceToolkit(config) as tk:
    storage = InfluxDBStorage(config)
    records = tk.coin_futures.basis("BTCUSD", "PERPETUAL", "1h", limit=30)
    for r in records:
        storage.write_basis(
            pair=r["pair"],
            contract_type=r["contractType"],
            futures_price=float(r["futuresPrice"]),
            index_price=float(r["indexPrice"]),
            basis=float(r["basis"]),
            basis_rate=float(r["basisRate"]),
            annualized_basis_rate=float(r["annualizedBasisRate"]),
            timestamp=datetime.fromtimestamp(r["timestamp"] / 1000, tz=timezone.utc),
        )
    storage.close()
```

InfluxDB 中写入的数据格式：

| Measurement | Tag | Field | Timestamp |
|-------------|-----|-------|-----------|
| `binance_ticker` | `pair=BTCUSD`, `contract_type=PERPETUAL` | `futures_price`, `index_price`, `basis`, `basis_rate`, `annualized_basis_rate` | UTC 时间 |

### 4. 代码中使用

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.toolkit import BinanceToolkit

# 从环境变量加载配置
config = BinanceConfig.from_env()

# 或者手动创建
config = BinanceConfig(
    api_key="your_api_key",
    private_key_path="/path/to/key.pem",
    private_key_password="your_password",
)

with BinanceToolkit(config) as tk:
    # 现货市场数据 (无需签名)
    print(tk.market.ping())
    print(tk.market.ticker_price("BTCUSDT"))
    print(tk.market.klines("ETHUSDT", "1h", limit=10))
    print(tk.market.depth("BTCUSDT"))

    # 币本位合约: 标记价格和指数价格 (无需签名, 访问 dapi.binance.com)
    print(tk.coin_futures.premium_index(symbol="BTCUSD_PERP"))
    print(tk.coin_futures.premium_index(pair="BTCUSD"))   # 返回该 pair 所有合约

    # 币本位合约: 基差历史数据 (无需签名)
    print(tk.coin_futures.basis("BTCUSD", "PERPETUAL", "1h", limit=50))
    print(tk.coin_futures.basis("BTCUSD", "CURRENT_QUARTER", "4h"))

    # 币本位合约: 资金费率信息 (无需签名)
    print(tk.coin_futures.funding_info())  # 返回所有永续合约的资金费率设置

    # 交易 (需要签名)
    order = tk.trade.new_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        time_in_force="GTC",
        quantity="0.001",
        price="30000",
    )
```

## 扩展指南

添加新的 API 模块非常简单，只需 3 步:

### 1. 创建新模块

```python
# binance_toolkit/api/futures.py
from .base import BaseAPI

class FuturesAPI(BaseAPI):
    """合约 API."""

    def ticker_price(self, symbol: str) -> dict:
        return self._client.get("/fapi/v1/ticker/price", params={"symbol": symbol})
```

### 2. 注册到 Toolkit

```python
# binance_toolkit/toolkit.py
from .api.futures import FuturesAPI

class BinanceToolkit:
    def __init__(self, config):
        ...
        self.futures = FuturesAPI(self._client)
```

### 3. (可选) 添加 CLI 子命令

在 `cli.py` 中添加子命令处理函数和解析器即可。

## 鉴权方式

| 方式 | 配置项 | 适用场景 |
|------|--------|----------|
| 无签名 | 仅需 `api_key` | 公开市场数据 |
| HMAC-SHA256 | `secret_key` | 常规交易 |
| Ed25519 | `private_key_path` + `private_key_password` | 高安全性场景 |

## License

LGPL-3.0-or-later
