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
│   │   ├── coin_mark_price_stream.py  # 币本位合约标记价格实时流
│   │   └── usdt_mark_price_stream.py  # U本位合约标记价格实时流
│   ├── collector/            # 数据采集器
│   │   ├── price_collector.py        # 现货价格定时采集常驻进程
│   │   └── mark_price_collector.py   # 币本位合约标记/指数价格采集进程
│   ├── pnl/                  # 盈亏计算模块
│   │   ├── spot_pnl.py       # 现货未实现盈亏计算
│   │   └── futures_pnl.py    # 合约未实现盈亏计算
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

通过 WebSocket 实时获取币本位永续合约的标记价格和指数价格，支持打印到控制台、写入 InfluxDB 和/或发布到 Kafka。

```bash
# 仅打印到控制台 (调试模式)
python -m binance_toolkit ws-mark-price-coin

# 写入 InfluxDB + 打印到控制台
python -m binance_toolkit ws-mark-price-coin --write-db

# 仅写入 InfluxDB (静默模式)
python -m binance_toolkit ws-mark-price-coin --write-db --quiet

# 发布到 Kafka + 打印到控制台
python -m binance_toolkit ws-mark-price-coin --write-kafka

# 同时写入 InfluxDB 和 Kafka (静默模式)
python -m binance_toolkit ws-mark-price-coin --write-db --write-kafka --quiet

# 自定义: 指定合约, 3秒更新, 批量写入参数
python -m binance_toolkit ws-mark-price-coin --symbols BTCUSD_PERP,ETHUSD_PERP --speed 3s --write-db --batch-size 50

# 采样存储: 每 10 秒存一条 (大幅减少数据量)
python -m binance_toolkit ws-mark-price-coin --write-db --quiet --sample-interval 10

# Ctrl+C 优雅停止
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--symbols` | 指定合约，逗号分隔，省略订阅全部 |
| `--speed` | 更新速度 `1s` 或 `3s`，默认 `1s` |
| `--all` | 包含交割合约，默认仅永续合约 |
| `--write-db` / `-w` | 写入 InfluxDB |
| `--write-kafka` / `-k` | 发布到 Kafka |
| `--quiet` / `-q` | 不打印到控制台 |
| `--batch-size` | 批量写入条数，默认 100 |
| `--flush-interval` | 最长刷新间隔秒数，默认 1.0 |
| `--sample-interval` | 采样间隔秒数，默认 0 不采样 |

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

# 方式二: 写入 InfluxDB (带批量写入 + 重试机制 + 采样)
writer = MarkPriceStreamWriter(
    config,
    write_db=True,
    enable_print=True,    # 同时打印到控制台
    batch_size=100,       # 每 100 条写入一次
    flush_interval=1.0,   # 或每 1 秒写入一次
    sample_interval=10,   # 每 10 秒采样一条 (可选)
)
writer.run()

# 方式三: 发布到 Kafka
writer = MarkPriceStreamWriter(
    config,
    write_db=False,
    write_kafka=True,
    enable_print=False,
)
writer.run()
```

**写入特性：**
- 内存队列缓冲，批量写入减少 IO
- 写入失败自动重试 3 次
- 优雅停止时确保缓冲数据写入
- 支持采样存储，减少数据量
- 退出时输出统计信息
- InfluxDB 和 Kafka 可同时启用

**Kafka 前置条件：**

```bash
pip install 'binance-toolkit[kafka]'
```

配置 Kafka 连接（config.json 或环境变量）：

```json
{
  "kafka_bootstrap_servers": "localhost:9092",
  "kafka_topic_coin": "binance.mark_price.coin",
  "kafka_topic_usdt": "binance.mark_price.usdt"
}
```

环境变量方式：

```bash
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
export KAFKA_TOPIC_COIN=binance.mark_price.coin
export KAFKA_TOPIC_USDT=binance.mark_price.usdt
```

Kafka 消息格式 (每条消息 Key=symbol, Value=JSON)：

```json
{
  "symbol": "BTCUSD_PERP",
  "mark_price": 67123.45,
  "index_price": 67100.00,
  "last_funding_rate": 0.00500,
  "next_funding_time": 1712700000000,
  "contract_type": "COIN",
  "timestamp": "2026-04-09T12:00:00+00:00"
}
```

### 7.1 U 本位合约标记价格 WebSocket 流

通过 WebSocket 实时获取 U 本位永续合约的标记价格和指数价格，支持打印到控制台、写入 InfluxDB 和/或发布到 Kafka。用法与币本位合约相同。

```bash
# 仅打印到控制台 (调试模式)
python -m binance_toolkit ws-mark-price-usdt

# 写入 InfluxDB + 打印到控制台
python -m binance_toolkit ws-mark-price-usdt --write-db

# 仅写入 InfluxDB (静默模式)
python -m binance_toolkit ws-mark-price-usdt --write-db --quiet

# 发布到 Kafka
python -m binance_toolkit ws-mark-price-usdt --write-kafka --quiet

# 同时写入 InfluxDB 和 Kafka
python -m binance_toolkit ws-mark-price-usdt --write-db --write-kafka --quiet

# 自定义: 指定合约, 3秒更新, 批量写入参数
python -m binance_toolkit ws-mark-price-usdt --symbols BTCUSDT,ETHUSDT --speed 3s --write-db --batch-size 50

# Ctrl+C 优雅停止
```

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.ws import UsdtMarkPriceStream, UsdtMarkPriceStreamWriter

config = BinanceConfig.from_env()

# 方式一: 仅打印/自定义处理
stream = UsdtMarkPriceStream(
    symbols=None,  # 订阅全部
    update_speed="1s",
    on_message=lambda data: print(data),
    perp_only=True,  # 仅永续合约 (无下划线的合约)
)
stream.run()

# 方式二: 写入 InfluxDB (带批量写入 + 重试机制)
writer = UsdtMarkPriceStreamWriter(
    config,
    write_db=True,
    enable_print=True,    # 同时打印到控制台
    batch_size=500,       # 每 500 条写入一次
    flush_interval=1.0,   # 或每 1 秒写入一次
    writer_threads=2,     # 2 个写入线程并行
    sample_interval=10,   # 每 10 秒采样一条 (减少数据量)
)
writer.run()

# 方式三: 发布到 Kafka
writer = UsdtMarkPriceStreamWriter(
    config,
    write_db=False,
    write_kafka=True,
    enable_print=False,
)
writer.run()
```

**U 本位参数说明：**

| 参数 | 说明 |
|------|------|
| `--symbols` | 指定合约，逗号分隔，省略订阅全部 |
| `--speed` | 更新速度 `1s` 或 `3s`，默认 `1s` |
| `--all` | 包含交割合约，默认仅永续合约 |
| `--write-db` / `-w` | 写入 InfluxDB |
| `--write-kafka` / `-k` | 发布到 Kafka |
| `--quiet` / `-q` | 不打印到控制台 |
| `--batch-size` | 批量写入条数，默认 500 |
| `--flush-interval` | 最长刷新间隔秒数，默认 1.0 |
| `--writer-threads` | 写入线程数，默认 2 |
| `--sample-interval` | 采样间隔秒数，默认 0 不采样 |

**采样存储 (解决数据量过大问题)：**

U 本位合约约 200+ 个，每秒推送一次会产生大量数据（约 1700 万条/天）。使用 `--sample-interval` 可大幅减少数据量：

```bash
# 每 10 秒采样一次 (数据量减少到 1/10)
python -m binance_toolkit ws-mark-price-usdt --write-db --quiet --sample-interval 10

# 每 30 秒采样一次 (数据量减少到 1/30)
python -m binance_toolkit ws-mark-price-usdt --write-db --quiet --sample-interval 30

# 每分钟采样一次 (适合历史趋势分析)
python -m binance_toolkit ws-mark-price-usdt --write-db --quiet --sample-interval 60
```

| 采样间隔 | 每天数据量 | 相比原始 |
|---------|-----------|---------|
| 无采样 | ~1700万条 | 100% |
| 10 秒 | ~170万条 | 10% |
| 30 秒 | ~60万条 | 3.5% |
| 60 秒 | ~30万条 | 1.7% |

**InfluxDB 中 margin_type 字段区分：**

| 合约类型 | margin_type 值 |
|----------|----------------|
| 币本位合约 (COIN-M) | `COIN` |
| U本位合约 (USDT-M) | `USDT` |

InfluxDB 中写入的数据格式：

| Measurement | Tag | Field | Timestamp |
|-------------|-----|-------|-----------|
| `binance_ticker` | `symbol=BTCUSDT`, `margin_type=USDT` | `mark_price`, `index_price`, `last_funding_rate`, `next_funding_time` | UTC 时间 |

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

### 9. 现货未实现盈亏计算

通过 WebSocket 实时获取 U 本位合约的 index 价格，计算现货持仓的未实现盈亏。

```bash
# 使用示例持仓数据
python -m binance_toolkit spot-pnl

# 指定实际持仓 (格式: 币种:买入价:数量)
python -m binance_toolkit spot-pnl --positions "BTC:60000:0.1,ETH:3000:1.5"

# 自定义手续费率 (默认 0.02%)
python -m binance_toolkit spot-pnl --positions "BTC:65000:0.5" --fee-rate 0.001

# 调整打印间隔 (默认 1 秒)
python -m binance_toolkit spot-pnl --positions "BTC:60000:0.1" --interval 3

# Ctrl+C 停止
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--positions` | 持仓列表，格式: `币种:买入价:数量`，多个用逗号分隔 |
| `--fee-rate` | 交易手续费率，默认 0.0002 (0.02%) |
| `--speed` | 价格更新速度 `1s` 或 `3s`，默认 `1s` |
| `--interval` | 盈亏打印间隔秒数，默认 1.0 |

**盈亏计算公式：**

- 买入成本 = 买入价 × 数量 × (1 + 手续费率)
- 卖出价值 = 现价 × 数量 × (1 - 手续费率)
- 未实现盈亏 = 卖出价值 - 买入成本

**控制台输出示例：**

```
================================================================================
[2026-04-12 10:30:00] 现货未实现盈亏 (手续费: 0.02%)
================================================================================
币种            买入价          现价        数量          成本          市值          盈亏      盈亏%
--------------------------------------------------------------------------------
BTC          60000.00     62000.00      0.1000      6001.20      6198.76     +197.56   +3.29%
ETH           3000.00      3100.00      1.0000      3000.60      3099.38      +98.78   +3.29%
--------------------------------------------------------------------------------
合计                                                 9001.80      9298.14     +296.34   +3.29%
```

在代码中使用：

```python
from binance_toolkit.pnl import SpotPosition, SpotPnLCalculator

# 配置持仓
positions = [
    SpotPosition("BTC", buy_price=60000.0, quantity=0.1),
    SpotPosition("ETH", buy_price=3000.0, quantity=1.5),
    SpotPosition("SOL", buy_price=150.0, quantity=10.0, fee_rate=0.001),  # 自定义手续费
]

# 启动盈亏计算
calculator = SpotPnLCalculator(
    positions,
    update_speed="1s",
    print_interval=1.0,
)
calculator.run()  # 阻塞运行，Ctrl+C 停止
```

### 10. 合约未实现盈亏计算

通过 WebSocket 实时获取标记价格，计算合约持仓的未实现盈亏。支持 U 本位和币本位合约。

```bash
# 使用示例持仓数据
python -m binance_toolkit futures-pnl

# 指定实际持仓 (格式: 合约:方向:开仓价:数量:杠杆[:保证金类型])
python -m binance_toolkit futures-pnl --positions "BTCUSDT:LONG:60000:0.1:10,ETHUSDT:SHORT:3000:1.0:5"

# 币本位合约
python -m binance_toolkit futures-pnl --positions "BTCUSD_PERP:LONG:60000:100:20:COIN"

# 混合 U 本位和币本位
python -m binance_toolkit futures-pnl --positions "BTCUSDT:LONG:60000:0.1:10:USDT,BTCUSD_PERP:SHORT:61000:100:20:COIN"

# 自定义手续费率 (默认 0.04% Taker)
python -m binance_toolkit futures-pnl --positions "BTCUSDT:LONG:60000:0.1:10" --fee-rate 0.0002

# 调整打印间隔 (默认 1 秒)
python -m binance_toolkit futures-pnl --positions "BTCUSDT:LONG:60000:0.1:10" --interval 3

# Ctrl+C 停止
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--positions` | 持仓列表，格式: `合约:方向:开仓价:数量:杠杆[:保证金类型]`，多个用逗号分隔 |
| `--fee-rate` | 交易手续费率，默认 0.0004 (0.04% Taker) |
| `--speed` | 价格更新速度 `1s` 或 `3s`，默认 `1s` |
| `--interval` | 盈亏打印间隔秒数，默认 1.0 |

**持仓参数格式：**

- `合约`: 合约交易对，如 `BTCUSDT`（U本位）或 `BTCUSD_PERP`（币本位）
- `方向`: `LONG`（多头）或 `SHORT`（空头）
- `开仓价`: 开仓均价
- `数量`: 持仓数量（合约张数或币数量）
- `杠杆`: 杠杆倍数
- `保证金类型`: 可选，`USDT`（默认）或 `COIN`

**盈亏计算公式：**

- 多头盈亏 = (当前价格 - 开仓价格) × 数量
- 空头盈亏 = (开仓价格 - 当前价格) × 数量
- 保证金 = 开仓名义价值 / 杠杆
- ROE = 盈亏(含手续费) / 保证金 × 100%

**控制台输出示例：**

```
====================================================================================================
[2026-04-12 10:30:00] 合约未实现盈亏 (手续费: 0.04%)
====================================================================================================
合约             方向   杠杆       开仓价         标记价         数量       保证金       未实盈亏       ROE     资金费率
----------------------------------------------------------------------------------------------------
BTCUSDT          多  10x     60000.00     62000.00       0.1000      600.00      +200.00   +32.87%    +0.0100%
ETHUSDT          空   5x      3000.00      2900.00       1.0000      600.00      +100.00   +16.43%    -0.0050%
----------------------------------------------------------------------------------------------------
合计                                                                 1200.00      +300.00   +24.65%

含手续费估算: +295.04 USDT
```

在代码中使用：

```python
from binance_toolkit.pnl import (
    FuturesPosition,
    FuturesPnLCalculator,
    PositionSide,
    MarginType,
)

# 配置持仓
positions = [
    FuturesPosition(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        entry_price=60000.0,
        quantity=0.1,
        leverage=10,
        margin_type=MarginType.USDT,
    ),
    FuturesPosition(
        symbol="ETHUSDT",
        side=PositionSide.SHORT,
        entry_price=3000.0,
        quantity=1.0,
        leverage=5,
    ),
    # 币本位合约
    FuturesPosition(
        symbol="BTCUSD_PERP",
        side=PositionSide.LONG,
        entry_price=60000.0,
        quantity=100,  # 合约张数
        leverage=20,
        margin_type=MarginType.COIN,
    ),
]

# 启动盈亏计算
calculator = FuturesPnLCalculator(
    positions,
    update_speed="1s",
    print_interval=1.0,
)
calculator.run()  # 阻塞运行，Ctrl+C 停止
```

### 11. 用户数据流 (账户/订单更新)

通过 WebSocket 订阅用户数据流，实时接收账户余额变动、充值提现、订单状态更新等事件。

**前置条件：** 需要配置 API Key（需要读取权限）。

```bash
# 启动用户数据流，打印事件到控制台
python -m binance_toolkit user-data-stream

# 静默模式 (不打印到控制台)
python -m binance_toolkit user-data-stream --quiet

# Ctrl+C 优雅停止
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--quiet` / `-q` | 静默模式，不打印事件到控制台 |

**支持的事件类型：**

| 事件类型 | 说明 |
|----------|------|
| `outboundAccountPosition` | 账户余额变动（交易、充值、提现等导致） |
| `balanceUpdate` | 余额更新（充值、提现、划转） |
| `executionReport` | 订单状态更新（新订单、成交、取消等） |
| `listStatus` | OCO 订单列表状态更新 |

**控制台输出示例：**

```
📊 账户持仓更新 [2026-04-12 10:30:45]
├─ BTC: 1.5 (可用) / 0.5 (锁定)
├─ ETH: 10.0 (可用) / 2.0 (锁定)
└─ USDT: 50000.0 (可用) / 5000.0 (锁定)

💵 余额更新 [2026-04-12 10:31:00]
├─ 资产: USDT
├─ 变动: +1000.0
└─ 清算时间: 2026-04-12 10:30:55

📋 订单更新 [2026-04-12 10:32:15]
├─ 交易对: BTCUSDT
├─ 订单ID: 123456789
├─ 类型: LIMIT
├─ 方向: BUY
├─ 状态: FILLED (已完全成交)
├─ 价格: 42000.00
├─ 数量: 0.5
├─ 成交均价: 42000.00
└─ 成交量: 0.5 / 0.5
```

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.ws import UserDataStream, run_user_data_stream

config = BinanceConfig.from_env()

# 方式一: 使用便捷函数
run_user_data_stream(config, enable_print=True)

# 方式二: 自定义事件处理
def on_order_update(data):
    print(f"订单更新: {data['s']} {data['S']} {data['X']}")

stream = UserDataStream(
    config,
    enable_print=False,
    on_order_update=on_order_update,
)
stream.run()
```

**Listen Key 管理：**

- Listen Key 有效期 60 分钟
- 程序自动每 30 分钟续期
- 断线自动重连
- Ctrl+C 优雅停止时自动删除 Listen Key

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
