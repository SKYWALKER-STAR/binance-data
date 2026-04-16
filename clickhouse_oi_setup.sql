-- ============================================================
-- ClickHouse 消费 Kafka 持仓量统计数据建表方案
-- 适用数据来源: binance-toolkit fetch-oi
-- 对应 Kafka Topic: binance.oi.usdt_futures
-- 数据接口: GET /futures/data/openInterestHist (fapi.binance.com)
--
-- 整体架构:
--   Kafka Topic (binance.oi.usdt_futures)
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
-- 使用 ReplacingMergeTree，相同 (symbol, period, timestamp) 的行
-- 以 timestamp 最大的为准（幂等写入，重复拉取不会产生脏数据）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS binance.usdt_open_interest
(
    -- 唯一标识
    symbol                   LowCardinality(String),     -- 合约交易对, 如 BTCUSDT
    period                   LowCardinality(String),     -- 统计周期, 如 1h / 1d

    -- 持仓量核心字段
    sum_open_interest        Decimal(28, 8),             -- 持仓量 (合约张数)
    sum_open_interest_value  Decimal(28, 8),             -- 持仓量价值 (USDT)

    -- 时间字段
    timestamp                Int64,                      -- 原始时间戳 (ms), 用于排序和去重
    timestamp_iso            DateTime64(3, 'UTC'),       -- UTC 时间

    _insert_time             DateTime DEFAULT now()      -- 写入时间，用于排查延迟
)
ENGINE = ReplacingMergeTree(timestamp)
PARTITION BY (toYYYYMM(toDateTime(intDiv(timestamp, 1000))), period)
ORDER BY (symbol, period, timestamp)
TTL toDateTime(intDiv(timestamp, 1000)) + INTERVAL 1 YEAR  -- Binance 只提供近 1 个月, 可按需调整
SETTINGS index_granularity = 8192;

-- 设计要点:
--   ReplacingMergeTree(timestamp) — 保留 timestamp 最大的行（幂等，防止重复写入）
--   ORDER BY (symbol, period, timestamp) — 按合约+周期+时间点唯一确定一条记录
--   PARTITION BY (toYYYYMM, period) — 方便按月和周期分区管理
--   查询去重: SELECT ... FINAL 或使用 max(timestamp) GROUP BY


-- ------------------------------------------------------------
-- Step 3: 建 Kafka 引擎表（消费入口，不存储数据）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS binance.kafka_oi_usdt
(
    symbol                   String,
    period                   String,
    sum_open_interest        String,          -- 保留字符串精度，物化视图中转换
    sum_open_interest_value  String,
    timestamp                Int64,           -- ms 时间戳
    timestamp_iso            Nullable(String) -- ISO8601 字符串，可为 null
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.oi.usdt_futures',
    kafka_group_name            = 'clickhouse_oi_usdt',
    kafka_format                = 'JSONEachRow',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;


-- ------------------------------------------------------------
-- Step 4: 建 Materialized View（Kafka 引擎表 → MergeTree 存储表）
-- ------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS binance.oi_usdt_mv
TO binance.usdt_open_interest AS
SELECT
    symbol,
    period,
    toDecimal128(sum_open_interest, 8)       AS sum_open_interest,
    toDecimal128(sum_open_interest_value, 8) AS sum_open_interest_value,
    timestamp,
    toDateTime64(timestamp / 1000, 3, 'UTC') AS timestamp_iso
FROM binance.kafka_oi_usdt;


-- ------------------------------------------------------------
-- 常用查询示例
-- ------------------------------------------------------------

-- 查询最新持仓量（去重）
-- SELECT symbol, period, sum_open_interest, sum_open_interest_value, timestamp_iso
-- FROM binance.usdt_open_interest FINAL
-- WHERE symbol = 'BTCUSDT' AND period = '1h'
-- ORDER BY timestamp DESC
-- LIMIT 48;

-- 按天聚合（以每天最后一条为准）
-- SELECT
--     toDate(timestamp_iso) AS date,
--     symbol,
--     argMax(sum_open_interest, timestamp)       AS oi_at_close,
--     argMax(sum_open_interest_value, timestamp) AS oi_value_at_close
-- FROM binance.usdt_open_interest FINAL
-- WHERE symbol IN ('BTCUSDT', 'ETHUSDT')
--   AND period = '1h'
--   AND timestamp_iso >= toDateTime('2026-01-01 00:00:00')
-- GROUP BY date, symbol
-- ORDER BY date DESC, symbol;
