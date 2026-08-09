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
│       ├── futures_market.py # U本位合约市场数据 (FAPI, 无需签名, 含历史K线 / OI统计)
│       ├── trade.py          # 现货交易 (需要签名)
│       └── account.py        # 账户信息 (需要签名)
│   ├── ws/                   # WebSocket 模块
│   │   ├── coin_mark_price_stream.py  # 币本位合约标记价格实时流
│   │   ├── usdt_mark_price_stream.py  # U本位合约标记价格实时流
│   │   ├── usdt_kline_stream.py       # U本位合约 K线 WebSocket 流
│   │   ├── futures_trade_ws.py        # U本位合约 WebSocket 交易客户端
│   │   └── spot_trade_ws.py           # 现货 WebSocket 交易客户端
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

### 持仓维护（WebSocket -> Redis）

1. 安装 Redis 依赖：

```bash
pip install 'binance-toolkit[redis]'
```

2. 在配置中设置：

- `redis_url`，例如 `redis://127.0.0.1:6379/0`
- `redis_position_key_prefix`，例如 `binance:position:usdt_futures`
- `redis_position_sync_interval_sec`，例如 `2.0`

3. 启动仓位同步：

```bash
python -m binance_toolkit futures-positions-sync-redis --interval 2
```

可选只同步单个合约：

```bash
python -m binance_toolkit futures-positions-sync-redis --symbol BTCUSDT
```

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

# 查询 U 本位合约当前持仓（需要 API Key + 签名配置）
python -m binance_toolkit futures-positions

# 查看帮助
python -m binance_toolkit --help
```

### 4. K 线 & 持仓量快速命令

#### 实时 K 线（WebSocket，仅收盘推送一次）

```bash
# 订阅 BTCUSDT 日K线，打印到控制台（调试）
python -m binance_toolkit ws-kline-usdt --symbols BTCUSDT

# 订阅多个合约日K线，写入 Kafka（生产推荐）
python -m binance_toolkit ws-kline-usdt --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT --write-kafka --quiet

# 订阅 1 小时 K线（含未收盘的实时更新）
python -m binance_toolkit ws-kline-usdt --symbols BTCUSDT --interval 1h --all-updates --write-kafka --quiet
```

#### 历史 K 线（REST API，自动分页）

```bash
# 查询 BTCUSDT 最近 500 条日K线（打印到控制台）
python -m binance_toolkit fetch-klines --symbols BTCUSDT

# 回填指定日期范围的日K线到 Kafka
python -m binance_toolkit fetch-klines --symbols BTCUSDT,ETHUSDT --start 2024-01-01 --end 2025-01-01 --write-kafka --quiet

# 回填全量历史（从最早数据到现在）
python -m binance_toolkit fetch-klines --symbols BTCUSDT --write-kafka --quiet

# 拉取 4 小时 K线，指定时间范围
python -m binance_toolkit fetch-klines --symbols BTCUSDT --interval 4h --start 2025-01-01 --end 2026-01-01 --write-kafka --quiet

# 打印 JSON 格式（调试）
python -m binance_toolkit fetch-klines --symbols BTCUSDT --interval 1d --start 2026-01-01 --json
```

> **两者共用同一个 Kafka Topic `binance.kline.usdt_futures` 和 ClickHouse 表**，可以先用 `fetch-klines` 回填历史，再用 `ws-kline-usdt` 持续接收新K线，无缝衔接。

#### 持仓量统计（REST API，近 1 个月）

```bash
# 拉取 BTCUSDT 最近 500 条 1h OI（打印到控制台）
python -m binance_toolkit fetch-oi --symbols BTCUSDT

# 拉取多个合约近 1 个月 OI，写入 Kafka
python -m binance_toolkit fetch-oi --symbols BTCUSDT,ETHUSDT --write-kafka --quiet

# 指定时间范围（注意仅保留最近 1 个月）
python -m binance_toolkit fetch-oi --symbols BTCUSDT --period 1h --start 2026-03-20 --end 2026-04-16 --write-kafka --quiet

# 拉取日级别 OI，打印 JSON（调试）
python -m binance_toolkit fetch-oi --symbols BTCUSDT --period 1d --json
```

---

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
  "kafka_topic_usdt": "binance.mark_price.usdt",
  "kafka_topic_futures_trade": "binance.trade.usdt_futures"
}
```

环境变量方式：

```bash
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092
export KAFKA_TOPIC_COIN=binance.mark_price.coin
export KAFKA_TOPIC_USDT=binance.mark_price.usdt
export KAFKA_TOPIC_FUTURES_TRADE=binance.trade.usdt_futures
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

### 7.2 U 本位合约 K 线 WebSocket 流

通过 WebSocket 实时接收 U 本位永续合约的 K 线（蜡烛图）数据，默认订阅**日 K 线**并仅保存**已收盘**的 K 线，通过 Kafka 写入 ClickHouse。

**文档参考：**  
[Individual Symbol Kline/Candlestick Streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Kline-Candlestick-Streams)

#### Kafka Topic 设计

| Topic | 说明 |
|-------|------|
| `binance.kline.usdt_futures` | U 本位合约 K 线数据（默认日 K 线） |

```bash
# 订阅 BTCUSDT 日 K 线，打印到控制台（调试模式，默认仅收盘才打印）
python -m binance_toolkit ws-kline-usdt --symbols BTCUSDT

# 订阅多个合约日 K 线，发布到 Kafka（静默模式）
python -m binance_toolkit ws-kline-usdt --symbols BTCUSDT,ETHUSDT,SOLUSDT --write-kafka --quiet

# 订阅 1 小时 K 线，保存所有更新（含未收盘）
python -m binance_toolkit ws-kline-usdt --symbols BTCUSDT --interval 1h --all-updates --write-kafka --quiet

# 自定义 Kafka Topic
python -m binance_toolkit ws-kline-usdt --symbols BTCUSDT --write-kafka --kafka-topic my.kline.topic

# Ctrl+C 优雅停止
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--symbols` | 合约列表，逗号分隔（必填，默认 `BTCUSDT`） |
| `--interval` | K 线间隔，默认 `1d`（日 K 线） |
| `--all-updates` | 包含未收盘的 K 线更新；默认仅保存已收盘的 K 线 |
| `--write-kafka` / `-k` | 发布到 Kafka |
| `--kafka-topic` | Kafka Topic，默认 `binance.kline.usdt_futures` |
| `--quiet` / `-q` | 不打印到控制台 |
| `--batch-size` | 批量写入大小，默认 200 |
| `--flush-interval` | 最长刷新间隔秒数，默认 2.0 |

**支持的 K 线间隔：**  
`1m` `3m` `5m` `15m` `30m` `1h` `2h` `4h` `6h` `8h` `12h` `1d` `3d` `1w` `1M`

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.ws import UsdtKlineStream, UsdtKlineStreamWriter

config = BinanceConfig.from_env()

# 方式一: 仅打印/自定义处理（日K线，仅收盘触发）
stream = UsdtKlineStream(
    symbols=["BTCUSDT", "ETHUSDT"],
    interval="1d",
    on_message=lambda data: print(data),
    closed_only=True,   # 仅在 K线收盘时触发回调
)
stream.run()

# 方式二: 发布到 Kafka（日K线，仅收盘，静默）
writer = UsdtKlineStreamWriter(
    config,
    symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    interval="1d",
    closed_only=True,     # 仅保存已收盘的 K线
    write_kafka=True,
    enable_print=False,
    batch_size=200,
    flush_interval=2.0,
)
writer.run()

# 方式三: 订阅 1h K线，保存所有更新
writer = UsdtKlineStreamWriter(
    config,
    symbols=["BTCUSDT"],
    interval="1h",
    closed_only=False,    # 保存所有更新（含进行中的 K线）
    write_kafka=True,
    enable_print=True,
)
writer.run()
```

**Kafka 前置条件：**

```bash
pip install 'binance-toolkit[kafka]'
```

配置（config.json 或环境变量）：

```json
{
  "kafka_bootstrap_servers": "localhost:9092",
  "kafka_topic_kline_usdt": "binance.kline.usdt_futures"
}
```

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka 地址（逗号分隔） | — |
| `KAFKA_TOPIC_KLINE_USDT` | K 线 Topic | `binance.kline.usdt_futures` |

**Kafka 消息格式（每条消息 Key=symbol, Value=JSON）：**

```json
{
  "symbol":                  "BTCUSDT",
  "interval":                "1d",
  "open_time":               1744848000000,
  "close_time":              1744934399999,
  "open":                    "83500.00",
  "high":                    "85200.00",
  "low":                     "82800.00",
  "close":                   "84100.00",
  "volume":                  "12345.678",
  "quote_volume":            "1038245678.90",
  "trade_count":             450000,
  "taker_buy_volume":        "6200.000",
  "taker_buy_quote_volume":  "521000000.00",
  "is_closed":               true,
  "event_time":              1744934400123,
  "timestamp":               "2026-04-17T16:00:00.123000+00:00"
}
```

| 字段 | 说明 |
|------|------|
| `open_time` / `close_time` | K线开盘/收盘时间（毫秒时间戳） |
| `open` / `high` / `low` / `close` | 开高低收价格（字符串，保持原始精度） |
| `volume` | 成交量（基础资产，如 BTC 数量） |
| `quote_volume` | 成交额（计价资产，如 USDT） |
| `taker_buy_volume` | 主动买入成交量 |
| `is_closed` | `true` 表示该 K 线已收盘，数据为最终状态 |

**ClickHouse 建表参考（完整 DDL 见 `clickhouse_kline_setup.sql`）：**

```sql
-- 存储表（ReplacingMergeTree，用 event_time 去重保留最新状态）
CREATE TABLE binance.usdt_kline
(
    symbol              LowCardinality(String),
    interval            LowCardinality(String),
    open_time           DateTime64(3, 'UTC'),          -- K线开盘时间
    close_time          DateTime64(3, 'UTC'),          -- K线收盘时间
    open                Decimal(28, 8),
    high                Decimal(28, 8),
    low                 Decimal(28, 8),
    close               Decimal(28, 8),
    volume              Decimal(28, 8),
    quote_volume        Decimal(28, 8),
    trade_count         Int64,
    taker_buy_volume    Decimal(28, 8),
    taker_buy_quote_volume Decimal(28, 8),
    is_closed           Bool,
    event_time          Int64,
    timestamp           DateTime64(3, 'UTC'),
    _insert_time        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(event_time)
PARTITION BY (toYYYYMM(open_time), interval)
ORDER BY (symbol, interval, open_time);
```

> **注意：** 使用 `ReplacingMergeTree(event_time)` 是为了在同一根 K 线有多次更新时（例如 `closed_only=False` 模式下）自动保留最新的状态。查询时建议使用 `SELECT ... FINAL` 来获取去重后的结果。

### 7.3 历史 K 线补全（REST API）

通过 REST API (`GET /fapi/v1/klines`) 一次性拉取历史 K 线，支持自动分页和 Kafka 写入。
数据写入同一个 Kafka Topic `binance.kline.usdt_futures`，进入相同的 ClickHouse 表。

**文档参考：**  
[Kline/Candlestick Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)

```bash
# 查询最近 500 条日K线（仅打印到控制台）
python -m binance_toolkit fetch-klines --symbols BTCUSDT

# 拉取指定日期范围（自动翻页）
python -m binance_toolkit fetch-klines --symbols BTCUSDT --interval 1d --start 2024-01-01 --end 2025-01-01

# 回填历史数据到 Kafka（静默模式）
python -m binance_toolkit fetch-klines --symbols BTCUSDT,ETHUSDT --start 2024-01-01 --write-kafka --quiet

# 多个合约、1小时K线、指定时间范围
python -m binance_toolkit fetch-klines --symbols BTCUSDT,ETHUSDT,SOLUSDT --interval 1h --start 2025-01-01 --end 2025-04-01 --write-kafka --quiet

# 打印 JSON 格式结果（调试）
python -m binance_toolkit fetch-klines --symbols BTCUSDT --interval 1d --start 2025-12-01 --end 2026-01-01 --json
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--symbols` | 合约列表，逗号分隔（默认 `BTCUSDT`） |
| `--interval` | K 线间隔，默认 `1d` |
| `--start` | 起始时间，`YYYY-MM-DD` 或毫秒时间戳，省略则从最早数据开始 |
| `--end` | 截止时间，`YYYY-MM-DD` 或毫秒时间戳，省略则到当前时间 |
| `--write-kafka` / `-k` | 写入 Kafka |
| `--kafka-topic` | 目标 Topic，默认 `binance.kline.usdt_futures` |
| `--quiet` / `-q` | 不打印进度 |
| `--json` | 将结果以 JSON 打印到控制台（调试用） |

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.toolkit import BinanceToolkit
from binance_toolkit.storage.kafka import KafkaStorage
from datetime import datetime, timezone

config = BinanceConfig.from_env()

with BinanceToolkit(config) as tk:
    # --- 一次性查询（返回 dict 列表）---
    records = tk.futures_market.klines_as_records("BTCUSDT", "1d", limit=30)
    for r in records:
        print(r["open_time"], r["open"], r["close"])

    # --- 分页拉取并写入 Kafka ---
    kafka = KafkaStorage(config)
    tk.futures_market.fetch_klines_range(
        "BTCUSDT",
        "1d",
        start_time=int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
        end_time=int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
        write_kafka=True,
        kafka_storage=kafka,
        kafka_topic=config.kafka_topic_kline_usdt,
    )
    kafka.close()

    # --- 使用迭代器逐批处理（适合内存受限场景）---
    for batch in tk.futures_market.iter_klines("ETHUSDT", "1h",
                                               start_time=1704067200000):
        print(f"本批 {len(batch)} 条, 首条={batch[0]['timestamp']}")
        # 自行处理 batch ...
```

**`FuturesMarketAPI` 接口说明：**

| 方法 | 说明 |
|------|------|
| `klines(symbol, interval, ...)` | 单次查询，返回原始列表（最多 1500 条） |
| `klines_as_records(symbol, interval, ...)` | 单次查询，返回标准化 dict 列表 |
| `iter_klines(symbol, interval, ...)` | 自动分页迭代器，按批 yield dict 列表 |
| `fetch_klines_range(symbol, interval, ...)` | 全量拉取 + 可选 Kafka 写入，返回所有记录 |

> **数据格式与实时流完全一致**，历史拉取的 K 线和 WebSocket 流的 K 线写入同一个 Kafka Topic 和 ClickHouse 表，无需额外建表。

### 7.4 U 本位合约持仓量统计（OI Statistics）

通过 REST API (`GET /futures/data/openInterestHist`) 获取 U 本位合约持仓量历史统计数据，支持自动分页和 Kafka 写入。

> **注意：** Binance 接口仅保留最近 **1 个月**的 OI 数据，建议配置定时任务每天增量拉取。

**文档参考：**  
[Open Interest Statistics](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)

**数据字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | String | 合约交易对，如 `BTCUSDT` |
| `period` | String | 统计周期，如 `1h` / `1d` |
| `sum_open_interest` | String | 持仓量（合约张数） |
| `sum_open_interest_value` | String | 持仓量价值（USDT） |
| `timestamp` | Int64 | 时间戳（毫秒） |
| `timestamp_iso` | String | ISO8601 UTC 时间 |

```bash
# 拉取 BTCUSDT 近期 1h OI（打印到控制台）
python -m binance_toolkit fetch-oi --symbols BTCUSDT

# 拉取多个合约近 1 个月 1h OI，写入 Kafka
python -m binance_toolkit fetch-oi --symbols BTCUSDT,ETHUSDT,SOLUSDT --write-kafka --quiet

# 指定时间范围（仅近 1 个月内有效）
python -m binance_toolkit fetch-oi --symbols BTCUSDT --period 1h --start 2026-03-20 --end 2026-04-16 --write-kafka --quiet

# 拉取日级别 OI
python -m binance_toolkit fetch-oi --symbols BTCUSDT --period 1d --write-kafka --quiet

# 打印 JSON 格式结果（调试）
python -m binance_toolkit fetch-oi --symbols BTCUSDT --period 1h --json
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--symbols` | 合约列表，逗号分隔（默认 `BTCUSDT`） |
| `--period` | 统计周期，可选 `5m` / `15m` / `30m` / `1h` / `2h` / `4h` / `6h` / `12h` / `1d`，默认 `1h` |
| `--start` | 起始时间，`YYYY-MM-DD` 或毫秒时间戳 |
| `--end` | 截止时间，`YYYY-MM-DD` 或毫秒时间戳 |
| `--write-kafka` / `-k` | 写入 Kafka |
| `--kafka-topic` | 目标 Topic，默认 `binance.oi.usdt_futures` |
| `--quiet` / `-q` | 不打印进度 |
| `--json` | 将结果以 JSON 打印到控制台（调试用） |

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.toolkit import BinanceToolkit
from binance_toolkit.storage.kafka import KafkaStorage

config = BinanceConfig.from_env()

with BinanceToolkit(config) as tk:
    # --- 单次查询（最多 500 条）---
    records = tk.futures_market.open_interest_hist_as_records("BTCUSDT", "1h", limit=48)
    for r in records:
        print(r["timestamp_iso"], r["sum_open_interest"], r["sum_open_interest_value"])

    # --- 全量拉取并写入 Kafka ---
    kafka = KafkaStorage(config)
    tk.futures_market.fetch_oi_range(
        "BTCUSDT",
        "1h",
        write_kafka=True,
        kafka_storage=kafka,
        kafka_topic=config.kafka_topic_oi_usdt,
    )
    kafka.close()

    # --- 使用迭代器逐批处理 ---
    for batch in tk.futures_market.iter_open_interest("ETHUSDT", "1h"):
        print(f"本批 {len(batch)} 条, 首条={batch[0]['timestamp_iso']}")
```

**`FuturesMarketAPI` OI 接口说明：**

| 方法 | 说明 |
|------|------|
| `open_interest_hist(symbol, period, ...)` | 单次查询，返回原始 dict 列表（最多 500 条） |
| `open_interest_hist_as_records(symbol, period, ...)` | 单次查询，返回标准化 dict 列表 |
| `iter_open_interest(symbol, period, ...)` | 自动分页迭代器，按批 yield dict 列表 |
| `fetch_oi_range(symbol, period, ...)` | 全量拉取 + 可选 Kafka 写入，返回所有记录 |

**ClickHouse 建表参考（完整 DDL 见 `clickhouse_oi_setup.sql`）：**

```sql
-- 存储表
CREATE TABLE IF NOT EXISTS binance.usdt_open_interest
(
    symbol                   LowCardinality(String),
    period                   LowCardinality(String),
    sum_open_interest        Decimal(28, 8),
    sum_open_interest_value  Decimal(28, 8),
    timestamp                Int64,
    timestamp_iso            DateTime64(3, 'UTC'),
    _insert_time             DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(timestamp)
PARTITION BY (toYYYYMM(toDateTime(intDiv(timestamp, 1000))), period)
ORDER BY (symbol, period, timestamp);

-- Kafka 引擎表
CREATE TABLE IF NOT EXISTS binance.kafka_oi_usdt ( ... )
ENGINE = Kafka SETTINGS kafka_topic_list = 'binance.oi.usdt_futures', ...;

-- Materialized View
CREATE MATERIALIZED VIEW IF NOT EXISTS binance.oi_usdt_mv
TO binance.usdt_open_interest AS
SELECT symbol, period,
       toDecimal128(sum_open_interest, 8), toDecimal128(sum_open_interest_value, 8),
       timestamp, toDateTime64(timestamp / 1000, 3, 'UTC') AS timestamp_iso
FROM binance.kafka_oi_usdt;
```

> 查询时使用 `SELECT ... FINAL` 或 `argMax` 聚合去重，完整 DDL（含查询示例）见 `clickhouse_oi_setup.sql`。

---

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

### 12. 账户每日资产快照

调用 `GET /sapi/v1/accountSnapshot` 获取账户每日资产快照，支持现货、杠杆、合约三种账户类型。
查询结果打印到控制台，并预留了 Kafka → ClickHouse 写入管道接口。

**前置条件：** 需要配置 API Key + Secret Key（或 Ed25519 私钥）。

```bash
# 查询全部三种账户类型的最近 7 日快照 (默认)
python -m binance_toolkit account-snapshot

# 仅查询现货账户
python -m binance_toolkit account-snapshot --type SPOT

# 仅查询合约账户, 返回最近 30 日
python -m binance_toolkit account-snapshot --type FUTURES --limit 30

# 同时查询现货和合约, 指定时间范围 (毫秒时间戳)
python -m binance_toolkit account-snapshot --type SPOT,FUTURES --start 1712000000000 --end 1714000000000

# 发布到 Kafka (同时打印到控制台)
python -m binance_toolkit account-snapshot --write-kafka --kafka-topic binance.account.snapshot

# 静默模式 (只写 Kafka, 不打印)
python -m binance_toolkit account-snapshot --write-kafka --quiet

# Ctrl+C / 执行完毕自动退出
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--type` | 账户类型，逗号分隔: `SPOT` / `MARGIN` / `FUTURES`，默认全部 |
| `--limit` | 每种类型返回条数，范围 7~30，默认 7 |
| `--start` | 起始时间（毫秒时间戳），可选 |
| `--end` | 结束时间（毫秒时间戳），可选 |
| `--write-kafka` / `-k` | 将快照数据发布到 Kafka |
| `--kafka-topic` | Kafka Topic，默认 `binance.account.snapshot` |
| `--quiet` / `-q` | 静默模式，不打印到控制台 |

**控制台输出示例（现货账户）：**

```
════════════════════════════════════════════════════════════════════
  Binance 每日账户快照
════════════════════════════════════════════════════════════════════
  账户类型: SPOT    共 7 条快照
────────────────────────────────────────────────────────────────────
  [1/7]
  日期           : 2026-04-13 00:00:00 UTC
  BTC 总估值     : 0.15432100 BTC
  资产           可用 (free)              锁定 (locked)
  BTC            0.10000000               0.00000000
  USDT           5231.84000000            0.00000000
```

**控制台输出示例（合约账户）：**

```
════════════════════════════════════════════════════════════════════
  Binance 每日账户快照
════════════════════════════════════════════════════════════════════
  账户类型: FUTURES    共 7 条快照
────────────────────────────────────────────────────────────────────
  [1/7]
  日期           : 2026-04-13 00:00:00 UTC
  资产           钱包余额 (walletBalance)
  USDT           1200.00000000
  合约           持仓量               开仓价 (entryPrice)
  BTCUSDT        0.01000000           60000.00000000
```

在代码中使用：

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.collector.account_snapshot_collector import AccountSnapshotCollector

config = BinanceConfig.from_env()

# 仅打印到控制台
collector = AccountSnapshotCollector(
    config,
    account_types=["SPOT", "FUTURES"],
    limit=7,
)
collector.run()

# 同时推送到 Kafka (后续流入 ClickHouse)
collector = AccountSnapshotCollector(
    config,
    account_types=["SPOT", "MARGIN", "FUTURES"],
    limit=30,
    write_kafka=True,
    kafka_topic="binance.account.snapshot",
    enable_print=False,
)
collector.run()
```

**Kafka 消息格式 (每条消息 Key=`{type}:{updateTime}`, Value=JSON)：**

```json
{
  "type": "spot",
  "updateTime": 1744502400000,
  "timestamp": "2026-04-13T00:00:00",
  "data": {
    "totalAssetOfBtc": "0.15432100",
    "balances": [
      { "asset": "BTC", "free": "0.10000000", "locked": "0.00000000" },
      { "asset": "USDT", "free": "5231.84000000", "locked": "0.00000000" }
    ]
  }
}
```

**数据流说明（Kafka → ClickHouse）：**

1. 启动采集器，快照数据推送至 Kafka Topic `binance.account.snapshot`
2. ClickHouse 配置 Kafka 引擎表消费该 Topic
3. 通过 Materialized View 将数据写入持久化表，按 `type` 和 `updateTime` 分区

**API 接口约束：**

- 每次请求 IP 权重: 2400（注意频率限制）
- 查询时间跨度不超过 30 天
- 仅支持查询最近一个月数据
- `limit` 范围 7 ~ 30

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

### 13. U 本位合约 WebSocket 交易

通过持久 WebSocket 连接（`wss://fstream.binance.com/ws`）调用 Binance U 本位合约交易 API，
支持下单、修改订单、撤销订单和查询订单。每笔交易结果自动记录**交易发起时间**和**成交/更新时间**，
并写入 Kafka Topic，再由 Kafka 流入 ClickHouse 等数据库。

**前置条件：** 需要配置 API Key + Secret Key（或 Ed25519 私钥），并安装 Kafka 依赖。

```bash
pip install 'binance-toolkit[kafka]'
```

#### Kafka Topic 设计

| Topic | 说明 |
|-------|------|
| `binance.trade.usdt_futures` | U 本位合约每笔交易操作结果（下单 / 改单 / 撤单 / 查单） |

#### 消息格式（每条消息 Key=symbol, Value=JSON）

```json
{
  "action":                     "new_order",
  "order_id":                   325078477,
  "client_order_id":            "iCXL1BywlBaf2sesNUrVl3",
  "symbol":                     "BTCUSDT",
  "side":                       "BUY",
  "position_side":              "BOTH",
  "type":                       "LIMIT",
  "time_in_force":              "GTC",
  "quantity":                   "0.100",
  "price":                      "43187.00",
  "avg_price":                  "0.00",
  "stop_price":                 "0.00",
  "executed_qty":               "0.000",
  "cum_quote":                  "0.00000",
  "status":                     "NEW",
  "reduce_only":                false,
  "close_position":             false,
  "working_type":               "CONTRACT_PRICE",
  "price_protect":              false,
  "price_match":                "NONE",
  "self_trade_prevention_mode": "NONE",
  "good_till_date":             0,
  "sent_at":                    "2026-04-14T08:00:00.123456+00:00",
  "filled_at":                  "2026-04-14T08:00:00.435000+00:00",
  "update_time":                1702555534435,
  "recorded_at":                "2026-04-14T08:00:00.500000+00:00"
}
```

| 字段 | 说明 |
|------|------|
| `action` | 操作类型: `new_order` / `modify_order` / `cancel_order` / `query_order` |
| `sent_at` | **交易发起时间** — 客户端发送请求前记录的本地 UTC 时间（ISO 8601）|
| `filled_at` | **成交/更新时间** — 来自 Binance 响应中的 `updateTime` 字段（ISO 8601）|
| `update_time` | Binance 原始 `updateTime` 毫秒时间戳 |
| `recorded_at` | 写入 Kafka 时的本地 UTC 时间 |

#### 在代码中使用

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.storage.kafka import KafkaStorage
from binance_toolkit.ws.futures_trade_ws import FuturesTradeWsClient

config = BinanceConfig.from_env()

# 使用 with 语句自动管理连接
kafka = KafkaStorage(config)
with FuturesTradeWsClient(config, kafka_storage=kafka) as client:

    # --- 下单 (LIMIT) ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity="0.01",
        price="60000",
        time_in_force="GTC",
    )
    print("下单:", result["orderId"], result["status"])

    # --- 下单 (MARKET) ---
    result = client.new_order(
        symbol="ETHUSDT",
        side="SELL",
        order_type="MARKET",
        quantity="0.1",
    )

    # --- 双向持仓模式下单 ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity="0.01",
        price="59000",
        time_in_force="GTC",
        position_side="LONG",       # 双向持仓模式传入
    )

    # --- 止损单 ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="STOP_MARKET",
        stop_price="58000",
        close_position="true",      # 触发时全平
    )

    # --- 追踪止损单 ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="TRAILING_STOP_MARKET",
        quantity="0.01",
        callback_rate="1.0",        # 1% 回调幅度
        activation_price="62000",
    )

    # --- 修改订单 (仅 LIMIT 订单) ---
    result = client.modify_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity="0.015",
        price="59500",
        order_id=result["orderId"],
    )

    # --- 撤销订单 ---
    result = client.cancel_order(
        symbol="BTCUSDT",
        order_id=325078477,
    )
    print("撤单:", result["status"])   # "CANCELED"

    # --- 查询订单 ---
    result = client.query_order(
        symbol="BTCUSDT",
        order_id=325078477,
    )
    print("订单状态:", result["status"])

kafka.close()
```

#### 配置说明

```json
{
  "kafka_bootstrap_servers": "localhost:9092",
  "kafka_topic_futures_trade": "binance.trade.usdt_futures"
}
```

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka 地址（逗号分隔） | — |
| `KAFKA_TOPIC_FUTURES_TRADE` | 交易结果 Topic | `binance.trade.usdt_futures` |

#### `FuturesTradeWsClient` 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `BinanceConfig` | 含 API Key + 签名密钥的配置（必填）|
| `kafka_storage` | `KafkaStorage` | Kafka 存储实例，不传则不写 Kafka |
| `kafka_topic` | `str` | 目标 Topic（默认 `binance.trade.usdt_futures`）|
| `request_timeout` | `int` | 单次请求超时秒数（默认 `10`）|

#### ClickHouse 建表参考

```sql
-- Kafka 引擎表（消费 binance.trade.usdt_futures）
CREATE TABLE binance_futures_trade_queue
(
    action                     String,
    order_id                   Nullable(Int64),
    client_order_id            Nullable(String),
    symbol                     String,
    side                       Nullable(String),
    position_side              Nullable(String),
    type                       Nullable(String),
    time_in_force              Nullable(String),
    quantity                   Nullable(String),
    price                      Nullable(String),
    avg_price                  Nullable(String),
    stop_price                 Nullable(String),
    executed_qty               Nullable(String),
    cum_quote                  Nullable(String),
    status                     Nullable(String),
    reduce_only                Nullable(Bool),
    close_position             Nullable(Bool),
    working_type               Nullable(String),
    price_protect              Nullable(Bool),
    price_match                Nullable(String),
    self_trade_prevention_mode Nullable(String),
    good_till_date             Nullable(Int64),
    activate_price             Nullable(String),
    price_rate                 Nullable(String),
    sent_at                    Nullable(String),
    filled_at                  Nullable(String),
    update_time                Nullable(Int64),
    recorded_at                Nullable(String)
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'localhost:9092',
    kafka_topic_list  = 'binance.trade.usdt_futures',
    kafka_group_name  = 'clickhouse_futures_trade',
    kafka_format      = 'JSONEachRow';

-- 持久化表
CREATE TABLE binance_futures_trade
(
    action                     LowCardinality(String),
    order_id                   Int64,
    client_order_id            String,
    symbol                     LowCardinality(String),
    side                       LowCardinality(String),
    position_side              LowCardinality(String),
    type                       LowCardinality(String),
    time_in_force              LowCardinality(String),
    quantity                   Decimal(18, 8),
    price                      Decimal(18, 8),
    avg_price                  Decimal(18, 8),
    stop_price                 Decimal(18, 8),
    executed_qty               Decimal(18, 8),
    cum_quote                  Decimal(18, 8),
    status                     LowCardinality(String),
    reduce_only                Bool,
    close_position             Bool,
    working_type               LowCardinality(String),
    sent_at                    DateTime64(6, 'UTC'),
    filled_at                  Nullable(DateTime64(6, 'UTC')),
    update_time                Int64,
    recorded_at                DateTime64(6, 'UTC')
)
ENGINE = MergeTree
ORDER BY (symbol, order_id, recorded_at);

-- Materialized View（消费队列 → 持久化）
CREATE MATERIALIZED VIEW binance_futures_trade_mv TO binance_futures_trade AS
SELECT
    action,
    ifNull(order_id, 0)       AS order_id,
    ifNull(client_order_id,'') AS client_order_id,
    symbol,
    ifNull(side,'')            AS side,
    ifNull(position_side,'')   AS position_side,
    ifNull(type,'')            AS type,
    ifNull(time_in_force,'')   AS time_in_force,
    toDecimal64(ifNull(quantity,'0'), 8)      AS quantity,
    toDecimal64(ifNull(price,'0'), 8)         AS price,
    toDecimal64(ifNull(avg_price,'0'), 8)     AS avg_price,
    toDecimal64(ifNull(stop_price,'0'), 8)    AS stop_price,
    toDecimal64(ifNull(executed_qty,'0'), 8)  AS executed_qty,
    toDecimal64(ifNull(cum_quote,'0'), 8)     AS cum_quote,
    ifNull(status,'')          AS status,
    ifNull(reduce_only, false) AS reduce_only,
    ifNull(close_position, false) AS close_position,
    ifNull(working_type,'')    AS working_type,
    parseDateTimeBestEffort(ifNull(sent_at,''))     AS sent_at,
    if(filled_at IS NULL, NULL, parseDateTimeBestEffort(filled_at)) AS filled_at,
    ifNull(update_time, 0)     AS update_time,
    parseDateTimeBestEffort(ifNull(recorded_at,'')) AS recorded_at
FROM binance_futures_trade_queue;
```

#### 查询持仓信息

通过 WebSocket API 查询当前 U 本位合约持仓信息，支持写入 Kafka。

**设计原则：数据库与实际持仓始终保持一致**

每次写入 Kafka 时会推送 **全量持仓快照**（包括 `positionAmt = "0"` 的已平仓记录）。
ClickHouse 存储表使用 `ReplacingMergeTree(queried_at)` 引擎，排序键为 `(symbol, position_side)`（不含时间维度），
这样同一个仓位的新写入会在后台 merge 时覆盖旧记录。
"当前持仓"视图在查询时过滤掉 `position_amt = 0` 的记录，最终结果与实际持仓一致，不多也不少。

| 场景 | Binance 返回 | Kafka 写入 | ClickHouse 视图结果 |
|------|------------|-----------|-------------------|
| 开新仓 BTCUSDT | `positionAmt = "0.1"` | 写入非零记录 | 可见 |
| 仓位数量变化 | `positionAmt = "0.2"` | 写入新版本，覆盖旧记录 | 显示最新数量 |
| 平仓 BTCUSDT | `positionAmt = "0"` | 写入零仓位记录（版本更新） | 被视图过滤，消失 |
| 完全无持仓 | 全部为零 | 写入全零记录 | 视图为空 |

> **注意：** `--symbol` 参数仅用于控制台展示。如果需要将持仓数据同步到数据库，**必须不带 `--symbol` 参数**进行全量查询，否则只能感知到指定合约的状态变化，无法检测其他合约的平仓事件。

**命令行快速查询：**

```bash
# 查询所有活跃持仓（格式化表格输出）
python -m binance_toolkit futures-positions

# 全量持仓快照写入 Kafka（与数据库同步，推荐生产使用）
python -m binance_toolkit futures-positions --write-kafka --quiet

# 仅查看指定合约（调试/控制台展示，不影响数据库同步）
python -m binance_toolkit futures-positions --symbol BTCUSDT

# 打印原始 JSON（调试）
python -m binance_toolkit futures-positions --json
```

| 参数 | 说明 |
|------|------|
| `--symbol` | 指定合约（如 `BTCUSDT`）筛选控制台输出；**数据库同步时请勿指定此参数** |
| `--write-kafka` / `-k` | 将全量持仓快照写入 Kafka |
| `--kafka-topic` | 目标 Topic，默认 `binance.position.usdt_futures` |
| `--json` | 以 JSON 格式打印原始响应（调试） |
| `--quiet` / `-q` | 不打印到控制台 |

**在代码中使用：**

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.storage.kafka import KafkaStorage
from binance_toolkit.ws.futures_trade_ws import FuturesTradeWsClient

config = BinanceConfig.from_env()
kafka = KafkaStorage(config)

with FuturesTradeWsClient(config, kafka_storage=kafka) as client:

    # --- 全量查询（用于数据库同步，不传 symbol）---
    # 写入 Kafka，包含所有持仓（含 positionAmt=0 的已平仓记录）
    all_positions = client.query_position()
    active = [p for p in all_positions if float(p.get("positionAmt", 0)) != 0]
    print(f"活跃持仓 {len(active)} 个（共查询 {len(all_positions)} 条）")

    # --- 查询指定交易对（仅用于展示，不适合数据库同步）---
    positions = client.query_position(symbol="BTCUSDT")
    for pos in positions:
        print(f"{pos['symbol']} {pos['positionSide']}: "
              f"数量={pos['positionAmt']}, "
              f"开仓价={pos['entryPrice']}, "
              f"未实现盈亏={pos['unRealizedProfit']}")

kafka.close()
```

#### 持仓 Kafka Topic 设计

| Topic | 说明 |
|-------|------|
| `binance.position.usdt_futures` | U 本位合约全量持仓快照（含零仓位） |

#### 持仓消息格式（Key=symbol:positionSide, Value=JSON）

```json
{
  "symbol":                    "BTCUSDT",
  "position_side":             "BOTH",
  "position_amt":              "0.100",
  "entry_price":               "60000.00",
  "break_even_price":          "60012.00",
  "mark_price":                "61234.56",
  "unrealized_profit":         "123.456",
  "liquidation_price":         "45000.00",

  "isolated_margin":           "0.00000000",
  "notional":                  "6123.456",
  "margin_asset":              "USDT",
  "isolated_wallet":           "0",
  "initial_margin":            "612.3456",
  "maint_margin":              "24.49382",
  "position_initial_margin":   "612.3456",
  "open_order_initial_margin": "0",
  "adl":                       2,
  "bid_notional":              "0",
  "ask_notional":              "0",
  "update_time":               1702555534435,
  "updated_at":                "2026-04-14T08:00:00.435000+00:00",
  "queried_at":                "2026-04-14T08:00:00.123456+00:00",
  "recorded_at":               "2026-04-14T08:00:00.500000+00:00"
}
```

| 字段 | 说明 |
|------|------|
| `position_amt` | 持仓数量（正为多仓，负为空仓，`"0"` 表示已平仓）|
| `entry_price` | 开仓均价 |
| `mark_price` | 当前标记价格 |
| `unrealized_profit` | 未实现盈亏 |
| `liquidation_price` | 强平价格（全仓模式为 `"0"`）|
| `queried_at` | **查询发起时间** — 作为 `ReplacingMergeTree` 的版本号，值越新的记录越优先保留 |
| `updated_at` | **持仓更新时间** — 来自 Binance 响应中的 `updateTime` 字段 |

#### ClickHouse 持仓表建表参考

```sql
-- Kafka 引擎表（消费 binance.position.usdt_futures）
CREATE TABLE binance_futures_position_queue
(
    symbol                     String,
    position_side              String,
    position_amt               Nullable(String),
    entry_price                Nullable(String),
    break_even_price           Nullable(String),
    mark_price                 Nullable(String),
    unrealized_profit          Nullable(String),
    liquidation_price          Nullable(String),
    isolated_margin            Nullable(String),
    notional                   Nullable(String),
    margin_asset               Nullable(String),
    isolated_wallet            Nullable(String),
    initial_margin             Nullable(String),
    maint_margin               Nullable(String),
    position_initial_margin    Nullable(String),
    open_order_initial_margin  Nullable(String),
    adl                        Nullable(Int8),
    bid_notional               Nullable(String),
    ask_notional               Nullable(String),
    update_time                Nullable(Int64),
    updated_at                 Nullable(String),
    queried_at                 Nullable(String),
    recorded_at                Nullable(String)
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'localhost:9092',
    kafka_topic_list  = 'binance.position.usdt_futures',
    kafka_group_name  = 'clickhouse_futures_position',
    kafka_format      = 'JSONEachRow';

-- 持久化表
-- 核心设计：
--   ReplacingMergeTree(queried_at) — 以查询时间作为版本号，同一仓位的新快照覆盖旧快照
--   ORDER BY (symbol, position_side) — 不含时间维度，确保同一仓位只保留最新一条
--   TTL queried_at + INTERVAL 7 DAY — 自动清理 7 天前的历史版本，防止旧数据堆积
CREATE TABLE binance_futures_position
(
    symbol                     LowCardinality(String),
    position_side              LowCardinality(String),
    position_amt               Decimal(18, 8),
    entry_price                Decimal(18, 8),
    break_even_price           Decimal(18, 8),
    mark_price                 Decimal(18, 8),
    unrealized_profit          Decimal(18, 8),
    liquidation_price          Decimal(18, 8),
    isolated_margin            Decimal(18, 8),
    notional                   Decimal(18, 8),
    margin_asset               LowCardinality(String),
    isolated_wallet            Decimal(18, 8),
    initial_margin             Decimal(18, 8),
    maint_margin               Decimal(18, 8),
    position_initial_margin    Decimal(18, 8),
    open_order_initial_margin  Decimal(18, 8),
    adl                        Int8,
    bid_notional               Decimal(18, 8),
    ask_notional               Decimal(18, 8),
    update_time                Int64,
    updated_at                 Nullable(DateTime64(6, 'UTC')),
    queried_at                 DateTime64(6, 'UTC'),
    recorded_at                DateTime64(6, 'UTC')
)
ENGINE = ReplacingMergeTree(queried_at)
ORDER BY (symbol, position_side)
TTL toDate(queried_at) + INTERVAL 7 DAY;

-- 当前持仓视图（与实际持仓实时一致）
-- FINAL：强制 ClickHouse 在查询时执行去重，返回每个 (symbol, position_side) 的最新记录
-- WHERE position_amt != 0：过滤掉已平仓的零仓位记录
CREATE OR REPLACE VIEW v_current_futures_position AS
SELECT *
FROM binance_futures_position FINAL
WHERE position_amt != 0;

-- Materialized View（消费队列 → 持久化）
CREATE MATERIALIZED VIEW binance_futures_position_mv TO binance_futures_position AS
SELECT
    symbol,
    position_side,
    toDecimal64(ifNull(position_amt,'0'), 8)              AS position_amt,
    toDecimal64(ifNull(entry_price,'0'), 8)               AS entry_price,
    toDecimal64(ifNull(break_even_price,'0'), 8)          AS break_even_price,
    toDecimal64(ifNull(mark_price,'0'), 8)                AS mark_price,
    toDecimal64(ifNull(unrealized_profit,'0'), 8)         AS unrealized_profit,
    toDecimal64(ifNull(liquidation_price,'0'), 8)         AS liquidation_price,
    toDecimal64(ifNull(isolated_margin,'0'), 8)           AS isolated_margin,
    toDecimal64(ifNull(notional,'0'), 8)                  AS notional,
    ifNull(margin_asset,'USDT')                           AS margin_asset,
    toDecimal64(ifNull(isolated_wallet,'0'), 8)           AS isolated_wallet,
    toDecimal64(ifNull(initial_margin,'0'), 8)            AS initial_margin,
    toDecimal64(ifNull(maint_margin,'0'), 8)              AS maint_margin,
    toDecimal64(ifNull(position_initial_margin,'0'), 8)   AS position_initial_margin,
    toDecimal64(ifNull(open_order_initial_margin,'0'), 8) AS open_order_initial_margin,
    ifNull(adl, 0)                                        AS adl,
    toDecimal64(ifNull(bid_notional,'0'), 8)              AS bid_notional,
    toDecimal64(ifNull(ask_notional,'0'), 8)              AS ask_notional,
    ifNull(update_time, 0)                                AS update_time,
    if(updated_at IS NULL, NULL, parseDateTimeBestEffort(updated_at)) AS updated_at,
    parseDateTimeBestEffort(ifNull(queried_at,''))        AS queried_at,
    parseDateTimeBestEffort(ifNull(recorded_at,''))       AS recorded_at
FROM binance_futures_position_queue;
```

#### 查询当前持仓

```sql
-- 查看当前所有活跃持仓（与实际持仓一致）
SELECT symbol, position_side, position_amt, entry_price, mark_price, unrealized_profit, queried_at
FROM v_current_futures_position
ORDER BY symbol;

-- 若未创建视图，直接查询时需加 FINAL 并过滤零仓位
SELECT symbol, position_side, position_amt, entry_price, unrealized_profit
FROM binance_futures_position FINAL
WHERE position_amt != 0
ORDER BY symbol;

-- 手动触发后台合并（可选，减少存储占用）
OPTIMIZE TABLE binance_futures_position FINAL;
```

> **为什么要用 `FINAL`？** `ReplacingMergeTree` 的去重发生在后台 merge 时，不是实时的。
> 不加 `FINAL` 可能看到同一仓位的多个历史版本。生产环境查询时始终使用 `FINAL` 或视图。

### 14. 现货 WebSocket 交易

通过持久 WebSocket 连接（`wss://ws-api.binance.com:443/ws-api/v3`）调用 Binance 现货交易 API，
支持下单、撤销订单、查询订单和撤销所有订单。每笔交易结果自动记录**交易发起时间**和**成交时间**，
并写入 Kafka Topic，再由 Kafka 流入 ClickHouse 等数据库。

**前置条件：** 需要配置 API Key + Secret Key（或 Ed25519 私钥），并安装 Kafka 依赖。

```bash
pip install 'binance-toolkit[kafka]'
```

#### Kafka Topic 设计

| Topic | 说明 |
|-------|------|
| `binance.trade.spot` | 现货每笔交易操作结果（下单 / 撤单 / 查单 / 撤销全部） |

#### 消息格式（每条消息 Key=symbol, Value=JSON）

```json
{
  "action":                     "new_order",
  "order_id":                   28,
  "order_list_id":              -1,
  "client_order_id":            "6gCrw2kRUAF9CvJDGP16IP",
  "orig_client_order_id":       null,
  "symbol":                     "BTCUSDT",
  "side":                       "SELL",
  "type":                       "LIMIT",
  "time_in_force":              "GTC",
  "quantity":                   "1.00000000",
  "quote_order_qty":            null,
  "price":                      "0.10000000",
  "stop_price":                 null,
  "trailing_delta":             null,
  "trailing_time":              null,
  "iceberg_qty":                "0.00000000",
  "executed_qty":               "0.00000000",
  "cummulative_quote_qty":      "0.00000000",
  "status":                     "NEW",
  "working_time":               1507725176595,
  "self_trade_prevention_mode": "NONE",
  "prevented_match_id":         null,
  "prevented_quantity":         null,
  "strategy_id":                null,
  "strategy_type":              null,
  "fills":                      null,
  "sent_at":                    "2026-04-14T08:00:00.123456+00:00",
  "transact_at":                "2026-04-14T08:00:00.435000+00:00",
  "transact_time":              1507725176595,
  "recorded_at":                "2026-04-14T08:00:00.500000+00:00"
}
```

| 字段 | 说明 |
|------|------|
| `action` | 操作类型: `new_order` / `cancel_order` / `query_order` / `cancel_all_orders` |
| `sent_at` | **交易发起时间** — 客户端发送请求前记录的本地 UTC 时间（ISO 8601）|
| `transact_at` | **成交时间** — 来自 Binance 响应中的 `transactTime` 字段（ISO 8601）|
| `transact_time` | Binance 原始 `transactTime` 毫秒时间戳 |
| `recorded_at` | 写入 Kafka 时的本地 UTC 时间 |
| `fills` | 成交明细 JSON 字符串（仅响应类型为 FULL 时包含）|

#### 在代码中使用

```python
from binance_toolkit.config import BinanceConfig
from binance_toolkit.storage.kafka import KafkaStorage
from binance_toolkit.ws.spot_trade_ws import SpotTradeWsClient

config = BinanceConfig.from_env()

# 使用 with 语句自动管理连接
kafka = KafkaStorage(config)
with SpotTradeWsClient(config, kafka_storage=kafka) as client:

    # --- 下单 (LIMIT) ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity="0.001",
        price="60000",
        time_in_force="GTC",
    )
    print("下单:", result["orderId"], result["status"])

    # --- 下单 (MARKET) ---
    result = client.new_order(
        symbol="ETHUSDT",
        side="SELL",
        order_type="MARKET",
        quantity="0.1",
    )

    # --- 下单 (市价金额) ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quote_order_qty="100",   # 用 100 USDT 买入
    )

    # --- 止损限价单 ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="STOP_LOSS_LIMIT",
        quantity="0.001",
        price="58000",
        stop_price="58500",
        time_in_force="GTC",
    )

    # --- 冰山订单 ---
    result = client.new_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity="1",
        price="60000",
        time_in_force="GTC",
        iceberg_qty="0.1",       # 每次只显示 0.1 的挂单量
    )

    # --- 撤销订单 ---
    result = client.cancel_order(
        symbol="BTCUSDT",
        order_id=28,
    )
    print("撤单:", result["status"])   # "CANCELED"

    # --- 使用自定义 ID 撤销 ---
    result = client.cancel_order(
        symbol="BTCUSDT",
        orig_client_order_id="6gCrw2kRUAF9CvJDGP16IP",
    )

    # --- 查询订单 ---
    result = client.query_order(
        symbol="BTCUSDT",
        order_id=28,
    )
    print("订单状态:", result["status"])

    # --- 撤销全部订单 ---
    results = client.cancel_all_orders(symbol="BTCUSDT")
    print(f"已撤销 {len(results)} 个订单")

kafka.close()
```

#### 配置说明

```json
{
  "spot_ws_url": "wss://ws-api.binance.com:443/ws-api/v3",
  "kafka_bootstrap_servers": "localhost:9092",
  "kafka_topic_spot_trade": "binance.trade.spot"
}
```

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `BINANCE_SPOT_WS_URL` | 现货 WebSocket API 地址 | `wss://ws-api.binance.com:443/ws-api/v3` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka 地址（逗号分隔） | — |
| `KAFKA_TOPIC_SPOT_TRADE` | 交易结果 Topic | `binance.trade.spot` |

#### `SpotTradeWsClient` 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `config` | `BinanceConfig` | 含 API Key + 签名密钥的配置（必填）|
| `kafka_storage` | `KafkaStorage` | Kafka 存储实例，不传则不写 Kafka |
| `kafka_topic` | `str` | 目标 Topic（默认 `binance.trade.spot`）|
| `request_timeout` | `int` | 单次请求超时秒数（默认 `10`）|

#### 引擎架构

`SpotTradeWsClient` 与 `FuturesTradeWsClient` 采用相同的引擎架构，保证一致的可靠性和可扩展性：

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SpotTradeWsClient                              │
├──────────────────────────────────────┬──────────────────────────────┤
│              主线程                  │          后台线程            │
│  ┌─────────────────────────────┐     │  ┌────────────────────────┐  │
│  │  new_order / cancel_order   │     │  │    _recv_thread        │  │
│  │  query_order / cancel_all   │     │  │  ──────────────────    │  │
│  │           ↓                 │     │  │  - 接收 WebSocket 消息 │  │
│  │  _request() → send + wait   │     │  │  - 分发响应到 pending  │  │
│  │           ↓                 │     │  │  - 断线自动重连        │  │
│  │     Kafka 写入              │     │  │  - 超时继续等待        │  │
│  └─────────────────────────────┘     │  └────────────────────────┘  │
│                                      │  ┌────────────────────────┐  │
│                                      │  │    _ping_thread        │  │
│                                      │  │  ──────────────────    │  │
│                                      │  │  - 每 150 秒发 ping    │  │
│                                      │  │  - 保持连接活跃        │  │
│                                      │  └────────────────────────┘  │
└──────────────────────────────────────┴──────────────────────────────┘
```

**连接管理特性:**

| 特性 | 说明 |
|------|------|
| **自动连接** | 实例化时自动建立 WebSocket 连接 |
| **心跳保活** | 每 150 秒发送 ping 帧，防止服务端因空闲断开 |
| **读超时** | socket 读超时设为 30 秒，超时后继续等待（正常空闲行为） |
| **断线重连** | 连接断开后自动指数退避重连（最长 60 秒） |
| **请求超时** | 单次请求默认 10 秒超时，可配置 |
| **线程安全** | 写操作加锁保护，支持多线程并发调用 |
| **优雅关闭** | `close()` 或 `with` 语句自动关闭连接和线程 |

**常量配置:**

| 常量 | 值 | 说明 |
|------|-----|------|
| `_DEFAULT_TIMEOUT` | 10 | 请求超时秒数 |
| `_MAX_RECONNECT_WAIT` | 60 | 重连最大等待秒数 |
| `_RECV_TIMEOUT` | 30 | socket 读超时秒数 |
| `_PING_INTERVAL` | 150 | 心跳间隔秒数 |

#### 支持的订单类型

| 订单类型 | 必填参数 | 可选参数 |
|---------|---------|---------|
| `LIMIT` | `quantity`, `price`, `timeInForce` | `icebergQty` |
| `MARKET` | `quantity` 或 `quoteOrderQty` | — |
| `LIMIT_MAKER` | `quantity`, `price` | — |
| `STOP_LOSS` | `quantity`, `stopPrice` | `trailingDelta` |
| `STOP_LOSS_LIMIT` | `quantity`, `price`, `stopPrice`, `timeInForce` | `trailingDelta`, `icebergQty` |
| `TAKE_PROFIT` | `quantity`, `stopPrice` | `trailingDelta` |
| `TAKE_PROFIT_LIMIT` | `quantity`, `price`, `stopPrice`, `timeInForce` | `trailingDelta`, `icebergQty` |

#### CLI 启动

```bash
# 真实执行
python -m binance_toolkit engine-spot

# 模拟执行（不实际下单）
python -m binance_toolkit engine-spot --dry-run
```

#### ClickHouse 建表参考

```sql
-- Kafka 引擎表（消费 binance.trade.spot）
CREATE TABLE binance_spot_trade_queue
(
    action                     String,
    order_id                   Nullable(Int64),
    order_list_id              Nullable(Int64),
    client_order_id            Nullable(String),
    orig_client_order_id       Nullable(String),
    symbol                     String,
    side                       Nullable(String),
    type                       Nullable(String),
    time_in_force              Nullable(String),
    quantity                   Nullable(String),
    quote_order_qty            Nullable(String),
    price                      Nullable(String),
    stop_price                 Nullable(String),
    trailing_delta             Nullable(Int64),
    trailing_time              Nullable(Int64),
    iceberg_qty                Nullable(String),
    executed_qty               Nullable(String),
    cummulative_quote_qty      Nullable(String),
    status                     Nullable(String),
    working_time               Nullable(Int64),
    self_trade_prevention_mode Nullable(String),
    prevented_match_id         Nullable(Int64),
    prevented_quantity         Nullable(String),
    strategy_id                Nullable(Int64),
    strategy_type              Nullable(Int64),
    fills                      Nullable(String),
    sent_at                    Nullable(String),
    transact_at                Nullable(String),
    transact_time              Nullable(Int64),
    recorded_at                Nullable(String)
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'localhost:9092',
    kafka_topic_list  = 'binance.trade.spot',
    kafka_group_name  = 'clickhouse_spot_trade',
    kafka_format      = 'JSONEachRow';

-- 持久化表
CREATE TABLE binance_spot_trade
(
    action                     LowCardinality(String),
    order_id                   Int64,
    order_list_id              Int64,
    client_order_id            String,
    orig_client_order_id       String,
    symbol                     LowCardinality(String),
    side                       LowCardinality(String),
    type                       LowCardinality(String),
    time_in_force              LowCardinality(String),
    quantity                   Decimal(18, 8),
    quote_order_qty            Decimal(18, 8),
    price                      Decimal(18, 8),
    stop_price                 Decimal(18, 8),
    trailing_delta             Int64,
    trailing_time              Int64,
    iceberg_qty                Decimal(18, 8),
    executed_qty               Decimal(18, 8),
    cummulative_quote_qty      Decimal(18, 8),
    status                     LowCardinality(String),
    working_time               Int64,
    self_trade_prevention_mode LowCardinality(String),
    prevented_match_id         Int64,
    prevented_quantity         Decimal(18, 8),
    strategy_id                Int64,
    strategy_type              Int64,
    fills                      String,
    sent_at                    DateTime64(6, 'UTC'),
    transact_at                Nullable(DateTime64(6, 'UTC')),
    transact_time              Int64,
    recorded_at                DateTime64(6, 'UTC')
)
ENGINE = MergeTree
ORDER BY (symbol, order_id, recorded_at);

-- Materialized View（消费队列 → 持久化）
CREATE MATERIALIZED VIEW binance_spot_trade_mv TO binance_spot_trade AS
SELECT
    action,
    ifNull(order_id, 0)              AS order_id,
    ifNull(order_list_id, -1)        AS order_list_id,
    ifNull(client_order_id, '')      AS client_order_id,
    ifNull(orig_client_order_id, '') AS orig_client_order_id,
    symbol,
    ifNull(side, '')                 AS side,
    ifNull(type, '')                 AS type,
    ifNull(time_in_force, '')        AS time_in_force,
    toDecimal64(ifNull(quantity, '0'), 8)              AS quantity,
    toDecimal64(ifNull(quote_order_qty, '0'), 8)       AS quote_order_qty,
    toDecimal64(ifNull(price, '0'), 8)                 AS price,
    toDecimal64(ifNull(stop_price, '0'), 8)            AS stop_price,
    ifNull(trailing_delta, 0)        AS trailing_delta,
    ifNull(trailing_time, 0)         AS trailing_time,
    toDecimal64(ifNull(iceberg_qty, '0'), 8)           AS iceberg_qty,
    toDecimal64(ifNull(executed_qty, '0'), 8)          AS executed_qty,
    toDecimal64(ifNull(cummulative_quote_qty, '0'), 8) AS cummulative_quote_qty,
    ifNull(status, '')               AS status,
    ifNull(working_time, 0)          AS working_time,
    ifNull(self_trade_prevention_mode, '') AS self_trade_prevention_mode,
    ifNull(prevented_match_id, 0)    AS prevented_match_id,
    toDecimal64(ifNull(prevented_quantity, '0'), 8)    AS prevented_quantity,
    ifNull(strategy_id, 0)           AS strategy_id,
    ifNull(strategy_type, 0)         AS strategy_type,
    ifNull(fills, '')                AS fills,
    parseDateTimeBestEffort(ifNull(sent_at, ''))       AS sent_at,
    if(transact_at IS NULL, NULL, parseDateTimeBestEffort(transact_at)) AS transact_at,
    ifNull(transact_time, 0)         AS transact_time,
    parseDateTimeBestEffort(ifNull(recorded_at, ''))   AS recorded_at
FROM binance_spot_trade_queue;
```

### 15. 策略引擎 (ClickHouse Pull -> 多市场执行)

已内置一个最小可用策略引擎层，支持多市场信号驱动交易:

- **两个市场**: U 本位合约（`engine-futures`）+ 现货（`engine-spot`）
- **三个动作**: `PLACE_ORDER` / `CANCEL_ORDER` / `CANCEL_ALL_ORDERS`
- **一个信号源**: ClickHouse Pull（HTTP），通过 `market` 字段区分市场
- **两类运行输出**: 交易结果 Topic + 引擎审计 Topic（均写 Kafka）

#### 架构设计

引擎采用事件驱动 + 持久化状态机:

1. Pull 信号: 定时从 ClickHouse 信号表按 `signal_ts_ms` 增量拉取，按 `market` 字段过滤。
2. 信号规范化: 将原始行解析为统一 `TradingSignal` 模型。
3. 幂等去重: 使用本地 SQLite `signal_id` 主键去重，已终态信号不会重复执行。
4. 风控准入: 过期、字段合法性、名义价值阈值、每 symbol 频率限制。
5. 执行下发: 调用对应市场的 WebSocket 客户端执行下单/撤单/撤全。
6. 状态落盘: `RECEIVED -> SENT -> ACKED/FINAL` 持久化，支持重启恢复。
7. 对账补偿: 对 `SENT/ACKED/FAILED` 状态周期性 `query_order`，修正到最终状态。
8. 审计回写: 每次接收、拒绝、分发、执行、补偿都会写 Kafka 审计事件。
9. 健康暴露: 可选启动 `/health` 与 `/metrics` HTTP 端点。

#### CLI 启动

```bash
# U 本位合约引擎
python -m binance_toolkit engine-futures --port 9090           # 真实执行
python -m binance_toolkit engine-futures --port 9090 --dry-run # 演练模式

# 现货引擎
python -m binance_toolkit engine-spot              # 真实执行
python -m binance_toolkit engine-spot --dry-run    # 演练模式
```

**注意**: 两个引擎可以同时运行，各自处理对应 `market` 的信号，互不干扰。

#### 配置项

可在 `config.json` 或环境变量中配置:

| JSON 字段 | 环境变量 | 说明 |
|-----------|----------|------|
| `clickhouse_signal_url` | `CLICKHOUSE_SIGNAL_URL` | ClickHouse HTTP 地址 |
| `kafka_topic_engine_events` | `KAFKA_TOPIC_ENGINE_EVENTS` | 引擎审计 Topic |
| `clickhouse_database` | `CLICKHOUSE_DATABASE` | 数据库名 |
| `clickhouse_user` | `CLICKHOUSE_USER` | 用户名 |
| `clickhouse_password` | `CLICKHOUSE_PASSWORD` | 密码 |
| `clickhouse_signal_table` | `CLICKHOUSE_SIGNAL_TABLE` | 信号表名 |
| `clickhouse_signal_where` | `CLICKHOUSE_SIGNAL_WHERE` | 额外过滤条件 |
| `clickhouse_timeout` | `CLICKHOUSE_TIMEOUT` | Pull 超时秒数 |
| `engine_state_db_path` | `ENGINE_STATE_DB_PATH` | 本地状态库路径 |
| `engine_poll_interval_sec` | `ENGINE_POLL_INTERVAL_SEC` | Pull 周期 |
| `engine_reconcile_interval_sec` | `ENGINE_RECONCILE_INTERVAL_SEC` | 对账周期 |
| `engine_reconcile_lag_sec` | `ENGINE_RECONCILE_LAG_SEC` | 对账最小滞后 |
| `engine_reconcile_batch_size` | `ENGINE_RECONCILE_BATCH_SIZE` | 单次对账上限 |
| `engine_request_timeout` | `ENGINE_REQUEST_TIMEOUT` | 交易请求超时 |
| `engine_startup_lookback_ms` | `ENGINE_STARTUP_LOOKBACK_MS` | 首次启动回看窗口 |
| `engine_clickhouse_batch_size` | `ENGINE_CLICKHOUSE_BATCH_SIZE` | 单次 Pull 条数 |
| `engine_max_notional_per_order` | `ENGINE_MAX_NOTIONAL_PER_ORDER` | 单笔最大名义价值，0 表示不限制 |
| `engine_max_actions_per_min_symbol` | `ENGINE_MAX_ACTIONS_PER_MIN_SYMBOL` | 每 symbol 每分钟动作上限 |
| `engine_health_host` | `ENGINE_HEALTH_HOST` | 健康端点监听地址 |
| `engine_health_port` | `ENGINE_HEALTH_PORT` | 健康端点端口，0 表示关闭 |

#### ClickHouse 信号表示例

```sql
CREATE TABLE strategy_signals
(
        signal_id UUID DEFAULT generateUUIDv4(),
        strategy_id String DEFAULT 'Demo',
        market LowCardinality(String) DEFAULT 'futures',  -- 'spot' / 'futures'
        symbol String,
        action LowCardinality(String),
        signal_ts_ms Int64,
        ttl_ms Int64 DEFAULT 0,
        priority Int32 DEFAULT 0,

        side Nullable(String),
        order_type Nullable(String),
        quantity Nullable(String),
        price Nullable(String),
        time_in_force Nullable(String),
        position_side Nullable(String),
        reduce_only Nullable(String),
        close_position Nullable(String),

        order_id UUID DEFAULT generateUUIDv4(),
        orig_client_order_id UUID DEFAULT generateUUIDv4()
)
ENGINE = MergeTree
ORDER BY (signal_ts_ms, market, strategy_id, signal_id);
```

**注意:** 如果是从旧版本升级，需要执行以下 ALTER 语句添加 `market` 字段：

```sql
ALTER TABLE strategy_signals ADD COLUMN market LowCardinality(String) DEFAULT 'futures' AFTER strategy_id;
```

#### 信号字段说明

- 通用字段:
    - `signal_id`: 全局唯一信号 ID（幂等键）
    - `strategy_id`: 策略标识
    - `market`: 目标市场，`spot`（现货）或 `futures`（U本位合约）
    - `symbol`: 如 `BTCUSDT`
    - `action`: `PLACE_ORDER` / `CANCEL_ORDER` / `CANCEL_ALL_ORDERS`
    - `signal_ts_ms`: 信号时间戳（毫秒）
    - `ttl_ms`: 生存时间，0 表示不过期
    - `priority`: 同时刻优先级（数值越大越先执行）
- `PLACE_ORDER` 必填:
    - `side`: `BUY` / `SELL`
    - `order_type`: 如 `LIMIT` / `MARKET`
    - `quantity`
    - `price`（若启用了名义价值风控）
- `CANCEL_ORDER` 必填（二选一）:
    - `order_id`
    - `orig_client_order_id`
- `CANCEL_ALL_ORDERS` 必填:
    - `symbol`

#### 多市场引擎架构

引擎通过 `market` 字段区分信号所属市场，各市场引擎独立运行：

```
┌─────────────────────────────────────────────────────────────┐
│                   strategy_signals 表                       │
│  ┌─────────┬────────┬────────┬────────┬─────────┬───────┐  │
│  │signal_id│ market │ symbol │ action │  side   │ price │  │
│  ├─────────┼────────┼────────┼────────┼─────────┼───────┤  │
│  │ sig_001 │ spot   │ BTCUSDT│ PLACE  │  BUY    │ 60000 │  │
│  │ sig_002 │ futures│ BTCUSDT│ PLACE  │  SELL   │ 60100 │  │
│  └─────────┴────────┴────────┴────────┴─────────┴───────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               │               ▼
┌─────────────────┐       │     ┌─────────────────┐
│  engine-spot    │       │     │ engine-futures  │
│  (独立进程)     │       │     │  (独立进程)     │
│                 │       │     │                 │
│ WHERE market=   │       │     │ WHERE market=   │
│     'spot'      │       │     │   'futures'     │
└────────┬────────┘       │     └────────┬────────┘
         │                │              │
         ▼                │              ▼
  SpotTradeWsClient       │    FuturesTradeWsClient
         │                │              │
         ▼                │              ▼
  binance.trade.spot      │    binance.trade.usdt_futures
```

**状态隔离:** 每个引擎使用独立的 SQLite 状态数据库：
- `engine-futures`: `.state/strategy_engine_futures.db`
- `engine-spot`: `.state/strategy_engine_spot.db`

#### Kafka 审计 Topic

引擎不会直接写 ClickHouse。第二阶段里，执行日志与引擎状态变化统一写回 Kafka：

- 交易结果: `binance.trade.usdt_futures`
- 引擎审计: `binance.engine.futures`

对应的 ClickHouse Kafka 表、存储表和物化视图脚本见 `clickhouse_engine_audit_setup.sql`。

审计事件示例：

```json
{
    "event_type": "signal_executed",
    "signal_id": "sig-10001",
    "strategy_id": "trend_follow",
    "symbol": "BTCUSDT",
    "action": "PLACE_ORDER",
    "status": "FILLED",
    "reason": "order placed",
    "order_id": 123456789,
    "client_order_id": "so8e1d2a3b1234567890",
    "metrics": {
        "pulled": 10,
        "accepted": 8,
        "rejected": 1,
        "executed": 7,
        "failed": 0,
        "deduplicated": 2,
        "reconciled": 1
    },
    "recorded_at": "2026-04-15T12:00:00+00:00"
}
```

#### 健康端点

当 `engine_health_port > 0` 时，引擎会启动一个轻量 HTTP 服务：

- `/health`: 返回 JSON 运行快照
- `/metrics`: 返回 Prometheus 文本格式计数器

示例：

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/metrics
```

#### 工程保证

- 幂等: 同一 `signal_id` 只会进入一次终态。
- 重启恢复: 状态与 cursor 落地在 SQLite，重启后从断点续跑。
- 一致性补偿: 发送后异常场景通过 `query_order` 对账收敛。
- 可观测性: 引擎持续输出处理统计，并通过 Kafka 审计事件与 `/metrics` 暴露运行状态。

#### 与合约交易的差异

| 功能 | 现货 WebSocket 交易 | U 本位合约 WebSocket 交易 |
|------|---------------------|--------------------------|
| WebSocket 端点 | `wss://ws-api.binance.com:443/ws-api/v3` | `wss://fstream.binance.com/ws` |
| 下单方法 | `order.place` | `order.place` |
| 修改订单 | ❌ 不支持（使用 cancelReplace） | ✅ `order.modify` |
| 持仓方向 | ❌ 无 `positionSide` | ✅ `LONG` / `SHORT` / `BOTH` |
| 成交时间字段 | `transactTime` | `updateTime` |
| 金额下单 | ✅ `quoteOrderQty` | ❌ 仅数量下单 |
| 订单类型 | 7 种 | 10+ 种（含追踪止损等） |

---

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
