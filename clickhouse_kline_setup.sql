-- ============================================================
-- ClickHouse 消费 Kafka K线数据建表方案
-- 适用数据来源: binance-toolkit ws-kline-usdt
-- 对应 Kafka Topic: binance.kline.usdt_futures
--
-- 整体架构:
--   Kafka Topic (binance.kline.usdt_futures)
--       ↓
--   Kafka 引擎表  (消费入口，不持久化)
--       ↓  (Materialized View 触发)
--   MergeTree 存储表  (真正的持久化存储)
-- ============================================================


-- ------------------------------------------------------------
-- Step 1: 建库
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS binance;


-- ------------------------------------------------------------
-- Step 2: 建存储表 (MergeTree)
-- 使用 ReplacingMergeTree，相同 (symbol, interval, open_time) 的行
-- 以 event_time 最大的为准（即最新的 K线更新覆盖旧的进行中 K线）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS binance.usdt_kline
(
    -- K线唯一标识
    symbol              LowCardinality(String),         -- 合约交易对, 如 BTCUSDT
    interval            LowCardinality(String),         -- K线间隔, 如 1d / 1h
    open_time           DateTime64(3, 'UTC'),            -- K线开盘时间 (ms → DateTime64)
    close_time          DateTime64(3, 'UTC'),            -- K线收盘时间 (ms)

    -- OHLCV
    open                Decimal(28, 8),
    high                Decimal(28, 8),
    low                 Decimal(28, 8),
    close               Decimal(28, 8),
    volume              Decimal(28, 8),                 -- 成交量 (基础资产)
    quote_volume        Decimal(28, 8),                 -- 成交额 (计价资产)
    trade_count         Int64,                          -- 成交笔数
    taker_buy_volume    Decimal(28, 8),                 -- 主动买入成交量
    taker_buy_quote_volume Decimal(28, 8),              -- 主动买入成交额

    -- 状态
    is_closed           Bool,                           -- 是否已收盘

    -- 时间辅助字段
    event_time          Int64,                          -- 原始事件时间戳 (ms), 用于去重排序
    timestamp           DateTime64(3, 'UTC'),           -- 事件 UTC 时间
    _insert_time        DateTime DEFAULT now()          -- 写入时间，用于排查延迟
)
ENGINE = ReplacingMergeTree(event_time)
PARTITION BY (toYYYYMM(open_time), interval)           -- 按月 + 间隔分区
ORDER BY (symbol, interval, open_time)                 -- 主键：合约 + 间隔 + 开盘时间
TTL open_time + INTERVAL 3 YEAR                        -- 可选：保留 3 年历史数据
SETTINGS index_granularity = 8192;

-- 设计要点:
--   ReplacingMergeTree(event_time) — 保留 event_time 最大的行（最新 K线状态）
--   ORDER BY (symbol, interval, open_time) — 按合约+间隔+开盘时间唯一确定一根K线
--   PARTITION BY (toYYYYMM, interval) — 方便按月和间隔分区管理
--   is_closed = true 的行是最终状态，ReplacingMergeTree 后台合并时会去重


-- ------------------------------------------------------------
-- Step 3: 建 Kafka 引擎表（消费入口，不存储数据）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS binance.kafka_kline_usdt
(
    symbol                     String,
    interval                   String,
    open_time                  Int64,          -- ms 时间戳
    close_time                 Int64,          -- ms 时间戳
    open                       String,         -- 保留字符串精度，物化视图中转换
    high                       String,
    low                        String,
    close                      String,
    volume                     String,
    quote_volume               String,
    trade_count                Int64,
    taker_buy_volume           String,
    taker_buy_quote_volume     String,
    is_closed                  Bool,
    event_time                 Int64,          -- ms 时间戳
    timestamp                  Nullable(String)   -- ISO8601 字符串，可为 null
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.kline.usdt_futures',
    kafka_group_name            = 'clickhouse_kline_usdt',
    kafka_format                = 'JSONEachRow',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;


-- ------------------------------------------------------------
-- Step 4: 建 Materialized View（Kafka 引擎表 → MergeTree 存储表）
-- ------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS binance.kline_usdt_mv
TO binance.usdt_kline AS
SELECT
    symbol,
    interval,
    toDateTime64(open_time  / 1000, 3, 'UTC')  AS open_time,
    toDateTime64(close_time / 1000, 3, 'UTC')  AS close_time,
    toDecimal128(open,  8)                      AS open,
    toDecimal128(high,  8)                      AS high,
    toDecimal128(low,   8)                      AS low,
    toDecimal128(close, 8)                      AS close,
    toDecimal128(volume, 8)                     AS volume,
    toDecimal128(quote_volume, 8)               AS quote_volume,
    trade_count,
    toDecimal128(taker_buy_volume, 8)           AS taker_buy_volume,
    toDecimal128(taker_buy_quote_volume, 8)     AS taker_buy_quote_volume,
    is_closed,
    event_time,
    toDateTime64(event_time / 1000, 3, 'UTC')  AS timestamp
FROM binance.kafka_kline_usdt;


-- ============================================================
-- 常用查询示例
-- ============================================================

-- 查询 BTCUSDT 最近 30 天日 K 线（仅已收盘）
-- SELECT *
-- FROM binance.usdt_kline FINAL
-- WHERE symbol = 'BTCUSDT'
--   AND interval = '1d'
--   AND is_closed = true
-- ORDER BY open_time DESC
-- LIMIT 30;

-- 查询所有合约某一天的日 K 线
-- SELECT symbol, open_time, open, high, low, close, volume
-- FROM binance.usdt_kline FINAL
-- WHERE interval = '1d'
--   AND open_time = toDateTime64('2026-04-15 00:00:00', 3, 'UTC')
--   AND is_closed = true
-- ORDER BY symbol;

-- 统计每个合约的日成交量均值（最近 30 天）
-- SELECT symbol,
--        avg(volume)       AS avg_volume,
--        avg(quote_volume) AS avg_quote_volume
-- FROM binance.usdt_kline FINAL
-- WHERE interval = '1d'
--   AND open_time >= now() - INTERVAL 30 DAY
--   AND is_closed = true
-- GROUP BY symbol
-- ORDER BY avg_quote_volume DESC;
