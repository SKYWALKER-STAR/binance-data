-- ============================================================
-- ClickHouse 消费 Kafka 标记价格数据建表方案
-- 适用数据来源: binance-toolkit ws-mark-price-coin / ws-mark-price-usdt
--
-- 整体架构:
--   Kafka Topic (coin/usdt)
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
-- 所有合约（COIN-M 和 USDT-M）共用一张表，通过 contract_type 区分
-- ------------------------------------------------------------
CREATE TABLE binance.mark_price
(
    -- 时间戳，毫秒精度，UTC
    timestamp           DateTime64(3, 'UTC'),
    -- 合约标识
    symbol              LowCardinality(String),
    contract_type       LowCardinality(String),     -- 'COIN' | 'USDT'
    -- 价格字段
    mark_price          Float64,
    index_price         Float64,
    -- 资金费率（永续合约才有，交割合约为 NULL）
    last_funding_rate   Nullable(Float32),
    -- 下次资金费时间（毫秒时间戳）
    next_funding_time   Nullable(Int64),
    -- 写入时间，用于排查延迟
    _insert_time        DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)                    -- 按月分区，便于 DROP PARTITION 清理
ORDER BY (contract_type, symbol, timestamp)         -- 覆盖最常见查询：按合约取时间序列
TTL timestamp + INTERVAL 1 YEAR                     -- 可选：数据保留 1 年后自动删除
SETTINGS index_granularity = 8192;

-- 设计要点：
--   LowCardinality(String)    symbol / contract_type 取值少，压缩率高，查询快
--   ORDER BY (contract_type, symbol, timestamp)  按合约取时间序列的最优索引
--   PARTITION BY toYYYYMM     按月分区，便于历史数据管理
--   Nullable(Float32)         资金费率可选，交割合约无此字段


-- ------------------------------------------------------------
-- Step 3: 建 Kafka 引擎表（消费入口，不存储数据）
-- ------------------------------------------------------------

-- 币本位 COIN-M（对应 Topic: binance.mark_price.coin）
CREATE TABLE binance.kafka_mark_price_coin
(
    timestamp           String,             -- ISO8601 字符串，物化视图中转换
    symbol              String,
    contract_type       String,
    mark_price          Float64,
    index_price         Float64,
    last_funding_rate   Nullable(Float32),
    next_funding_time   Nullable(Int64)
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list       = 'localhost:9092',
    kafka_topic_list        = 'binance.mark_price.coin',
    kafka_group_name        = 'clickhouse_mark_price_coin',
    kafka_format            = 'JSONEachRow',
    kafka_num_consumers     = 1,
    kafka_skip_broken_messages = 10;    -- 跳过解析失败的消息，避免卡住管道


-- U本位 USDT-M（对应 Topic: binance.mark_price.usdt）
CREATE TABLE binance.kafka_mark_price_usdt
(
    timestamp           String,
    symbol              String,
    contract_type       String,
    mark_price          Float64,
    index_price         Float64,
    last_funding_rate   Nullable(Float32),
    next_funding_time   Nullable(Int64)
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list       = 'localhost:9092',
    kafka_topic_list        = 'binance.mark_price.usdt',
    kafka_group_name        = 'clickhouse_mark_price_usdt',
    kafka_format            = 'JSONEachRow',
    kafka_num_consumers     = 2,            -- USDT 合约数量多，用 2 个消费者
    kafka_skip_broken_messages = 10;


-- ------------------------------------------------------------
-- Step 4: 建物化视图（Kafka 引擎表 → MergeTree 存储表）
-- ------------------------------------------------------------

-- 币本位
CREATE MATERIALIZED VIEW binance.mv_mark_price_coin
TO binance.mark_price
AS
SELECT
    parseDateTimeBestEffort(timestamp) AS timestamp,    -- ISO8601 字符串转 DateTime64
    symbol,
    contract_type,
    mark_price,
    index_price,
    last_funding_rate,
    next_funding_time
FROM binance.kafka_mark_price_coin;


-- U本位
CREATE MATERIALIZED VIEW binance.mv_mark_price_usdt
TO binance.mark_price
AS
SELECT
    parseDateTimeBestEffort(timestamp) AS timestamp,
    symbol,
    contract_type,
    mark_price,
    index_price,
    last_funding_rate,
    next_funding_time
FROM binance.kafka_mark_price_usdt;


-- ------------------------------------------------------------
-- Step 5: 验证查询
-- ------------------------------------------------------------

-- 查看最近写入的数据
SELECT
    symbol,
    contract_type,
    mark_price,
    index_price,
    last_funding_rate,
    timestamp
FROM binance.mark_price
ORDER BY timestamp DESC
LIMIT 20;

-- 统计每个合约今日数据量
SELECT
    contract_type,
    symbol,
    count()        AS cnt,
    min(timestamp) AS first_ts,
    max(timestamp) AS last_ts
FROM binance.mark_price
WHERE timestamp >= today()
GROUP BY contract_type, symbol
ORDER BY cnt DESC;

-- 查询 BTCUSDT 最近 1 小时的价格与资金费率走势（按分钟聚合）
SELECT
    toStartOfMinute(timestamp) AS minute,
    avg(mark_price)            AS avg_mark,
    avg(last_funding_rate)     AS avg_fr
FROM binance.mark_price
WHERE symbol = 'BTCUSDT'
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY minute
ORDER BY minute;


-- ------------------------------------------------------------
-- 注意事项
-- ------------------------------------------------------------
-- 1. kafka_skip_broken_messages: 遇到解析失败的消息跳过，避免坏消息卡住消费管道
-- 2. kafka_group_name 不能与其他消费者重复，否则会争抢 offset
-- 3. Kafka 引擎表不能直接查到历史数据，仅作消费入口；历史数据查 mark_price 表
-- 4. last_funding_rate / next_funding_time 是可选字段，消息中缺失时自动填 NULL
--    （需保证字段声明为 Nullable，否则会报错）
-- 5. timestamp 在 Kafka 消息中为 ISO8601 字符串（如 2026-04-09T12:00:00+00:00），
--    parseDateTimeBestEffort() 可自动处理时区偏移
-- 6. 如需修改 kafka_broker_list，将 'localhost:9092' 替换为实际地址，
--    多个 broker 用逗号分隔，如 'broker1:9092,broker2:9092'
