-- ============================================================
-- ClickHouse 消费 Kafka 账户每日快照数据建表方案
-- 适用数据来源: binance-toolkit account-snapshot --write-kafka
--
-- 数据来源 API:
--   GET /sapi/v1/accountSnapshot  (SPOT / MARGIN / FUTURES)
--
-- 整体架构:
--   Kafka Topic: binance.account.snapshot.spot
--                binance.account.snapshot.margin
--                binance.account.snapshot.futures.asset
--                binance.account.snapshot.futures.position
--       ↓
--   Kafka 引擎表  (消费入口，不持久化)
--       ↓  (Materialized View 触发)
--   ReplacingMergeTree 存储表  (持久化，支持幂等写入)
--
-- 说明:
--   Python 侧按每行数据（每个 balance / asset / position）发送一条 Kafka 消息，
--   ClickHouse 侧只需 JSONEachRow 直接写入，无需在 MV 中解析嵌套 JSON。
--   使用 ReplacingMergeTree，以 (snapshot_date, asset/symbol) 为主键，
--   重复拉取同一天的快照时自动去重（最终一致）。
-- ============================================================


-- ------------------------------------------------------------
-- Step 0: 建库
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS binance;


-- ============================================================
-- SPOT 现货账户余额快照
-- ============================================================

-- Kafka 引擎表（消费入口）
DROP TABLE IF EXISTS binance.kafka_account_snapshot_spot;
CREATE TABLE binance.kafka_account_snapshot_spot
(
    snapshot_date       String,     -- 'YYYY-MM-DD'，物化视图中转换
    update_time         Int64,      -- 毫秒时间戳
    total_asset_of_btc  String,     -- 原始字符串，转换为 Float64
    asset               String,
    free                String,
    locked              String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.account.snapshot.spot',
    kafka_group_name            = 'clickhouse_account_snapshot_spot',
    kafka_format                = 'JSONEachRow',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;

-- 存储表 (ReplacingMergeTree 支持幂等写入)
DROP TABLE IF EXISTS binance.account_snapshot_spot;
CREATE TABLE binance.account_snapshot_spot
(
    -- 快照维度
    snapshot_date       Date                        COMMENT '快照日期 (UTC)',
    update_time         DateTime64(3, 'UTC')        COMMENT '快照时间戳',
    -- 账户汇总
    total_asset_of_btc  Float64                     COMMENT '账户总资产折算 BTC',
    -- 资产明细 (每行一个币种)
    asset               LowCardinality(String)      COMMENT '资产名称, 如 BTC / USDT',
    free                Decimal(30, 8)              COMMENT '可用余额',
    locked              Decimal(30, 8)              COMMENT '锁定余额 (挂单中)',
    -- 元数据
    _insert_time        DateTime DEFAULT now()      COMMENT '写入 ClickHouse 的时间'
)
ENGINE = ReplacingMergeTree(_insert_time)
PARTITION BY toYYYYMM(snapshot_date)
ORDER BY (snapshot_date, asset)
TTL snapshot_date + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;

-- 物化视图（Kafka → 存储表）
DROP VIEW IF EXISTS binance.mv_account_snapshot_spot;
CREATE MATERIALIZED VIEW binance.mv_account_snapshot_spot
TO binance.account_snapshot_spot
AS SELECT
    toDate(snapshot_date)                               AS snapshot_date,
    toDateTime64(update_time / 1000, 3, 'UTC')          AS update_time,
    toFloat64OrZero(total_asset_of_btc)                 AS total_asset_of_btc,
    asset,
    toDecimal128OrZero(free,   8)                       AS free,
    toDecimal128OrZero(locked, 8)                       AS locked
FROM binance.kafka_account_snapshot_spot;


-- ============================================================
-- MARGIN 杠杆账户资产快照
-- ============================================================

DROP TABLE IF EXISTS binance.kafka_account_snapshot_margin;
CREATE TABLE binance.kafka_account_snapshot_margin
(
    snapshot_date               String,
    update_time                 Int64,
    margin_level                String,
    total_asset_of_btc          String,
    total_liability_of_btc      String,
    total_net_asset_of_btc      String,
    asset                       String,
    free                        String,
    locked                      String,
    borrowed                    String,
    interest                    String,
    net_asset                   String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.account.snapshot.margin',
    kafka_group_name            = 'clickhouse_account_snapshot_margin',
    kafka_format                = 'JSONEachRow',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;

DROP TABLE IF EXISTS binance.account_snapshot_margin;
CREATE TABLE binance.account_snapshot_margin
(
    -- 快照维度
    snapshot_date               Date                        COMMENT '快照日期 (UTC)',
    update_time                 DateTime64(3, 'UTC')        COMMENT '快照时间戳',
    -- 账户汇总
    margin_level                Float64                     COMMENT '当前保证金等级',
    total_asset_of_btc          Float64                     COMMENT '总资产折算 BTC',
    total_liability_of_btc      Float64                     COMMENT '总负债折算 BTC',
    total_net_asset_of_btc      Float64                     COMMENT '净资产折算 BTC',
    -- 资产明细 (每行一个币种)
    asset                       LowCardinality(String)      COMMENT '资产名称',
    free                        Decimal(30, 8)              COMMENT '可用余额',
    locked                      Decimal(30, 8)              COMMENT '锁定余额',
    borrowed                    Decimal(30, 8)              COMMENT '已借入金额',
    interest                    Decimal(30, 8)              COMMENT '利息',
    net_asset                   Decimal(30, 8)              COMMENT '净资产 (free + locked - borrowed - interest)',
    -- 元数据
    _insert_time                DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(_insert_time)
PARTITION BY toYYYYMM(snapshot_date)
ORDER BY (snapshot_date, asset)
TTL snapshot_date + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;

DROP VIEW IF EXISTS binance.mv_account_snapshot_margin;
CREATE MATERIALIZED VIEW binance.mv_account_snapshot_margin
TO binance.account_snapshot_margin
AS SELECT
    toDate(snapshot_date)                               AS snapshot_date,
    toDateTime64(update_time / 1000, 3, 'UTC')          AS update_time,
    toFloat64OrZero(margin_level)                       AS margin_level,
    toFloat64OrZero(total_asset_of_btc)                 AS total_asset_of_btc,
    toFloat64OrZero(total_liability_of_btc)             AS total_liability_of_btc,
    toFloat64OrZero(total_net_asset_of_btc)             AS total_net_asset_of_btc,
    asset,
    toDecimal128OrZero(free,     8)                     AS free,
    toDecimal128OrZero(locked,   8)                     AS locked,
    toDecimal128OrZero(borrowed, 8)                     AS borrowed,
    toDecimal128OrZero(interest, 8)                     AS interest,
    toDecimal128OrZero(net_asset, 8)                    AS net_asset
FROM binance.kafka_account_snapshot_margin;


-- ============================================================
-- FUTURES 合约账户 — 资产快照
-- ============================================================

DROP TABLE IF EXISTS binance.kafka_account_snapshot_futures_asset;
CREATE TABLE binance.kafka_account_snapshot_futures_asset
(
    snapshot_date       String,
    update_time         Int64,
    asset               String,
    wallet_balance      String,
    margin_balance      String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.account.snapshot.futures.asset',
    kafka_group_name            = 'clickhouse_account_snapshot_futures_asset',
    kafka_format                = 'JSONEachRow',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;

DROP TABLE IF EXISTS binance.account_snapshot_futures_asset;
CREATE TABLE binance.account_snapshot_futures_asset
(
    snapshot_date       Date                        COMMENT '快照日期 (UTC)',
    update_time         DateTime64(3, 'UTC')        COMMENT '快照时间戳',
    asset               LowCardinality(String)      COMMENT '资产名称, 如 USDT / BTC',
    wallet_balance      Decimal(30, 8)              COMMENT '钱包余额',
    margin_balance      Decimal(30, 8)              COMMENT '保证金余额 (非实时, 仅供参考)',
    _insert_time        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(_insert_time)
PARTITION BY toYYYYMM(snapshot_date)
ORDER BY (snapshot_date, asset)
TTL snapshot_date + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;

DROP VIEW IF EXISTS binance.mv_account_snapshot_futures_asset;
CREATE MATERIALIZED VIEW binance.mv_account_snapshot_futures_asset
TO binance.account_snapshot_futures_asset
AS SELECT
    toDate(snapshot_date)                               AS snapshot_date,
    toDateTime64(update_time / 1000, 3, 'UTC')          AS update_time,
    asset,
    toDecimal128OrZero(wallet_balance,  8)              AS wallet_balance,
    toDecimal128OrZero(margin_balance,  8)              AS margin_balance
FROM binance.kafka_account_snapshot_futures_asset;


-- ============================================================
-- FUTURES 合约账户 — 持仓快照
-- ============================================================

DROP TABLE IF EXISTS binance.kafka_account_snapshot_futures_position;
CREATE TABLE binance.kafka_account_snapshot_futures_position
(
    snapshot_date       String,
    update_time         Int64,
    symbol              String,
    entry_price         String,     -- 开仓均价
    mark_price          String,     -- 快照时的标记价格（非实时）
    position_amt        String,     -- 持仓量（正数多头，负数空头）
    unrealized_profit   String      -- 开仓时未实现盈亏（非实时，仅供参考）
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.account.snapshot.futures.position',
    kafka_group_name            = 'clickhouse_account_snapshot_futures_position',
    kafka_format                = 'JSONEachRow',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;

DROP TABLE IF EXISTS binance.account_snapshot_futures_position;
CREATE TABLE binance.account_snapshot_futures_position
(
    snapshot_date       Date                        COMMENT '快照日期 (UTC)',
    update_time         DateTime64(3, 'UTC')        COMMENT '快照时间戳',
    symbol              LowCardinality(String)      COMMENT '合约交易对, 如 BTCUSDT',
    entry_price         Decimal(30, 8)              COMMENT '开仓均价',
    mark_price          Decimal(30, 8)              COMMENT '快照时标记价格 (非实时)',
    position_amt        Decimal(30, 8)              COMMENT '持仓量 (正=多头, 负=空头)',
    unrealized_profit   Decimal(30, 8)              COMMENT '开仓时未实现盈亏 (非实时)',
    _insert_time        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(_insert_time)
PARTITION BY toYYYYMM(snapshot_date)
ORDER BY (snapshot_date, symbol)
TTL snapshot_date + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;

DROP VIEW IF EXISTS binance.mv_account_snapshot_futures_position;
CREATE MATERIALIZED VIEW binance.mv_account_snapshot_futures_position
TO binance.account_snapshot_futures_position
AS SELECT
    toDate(snapshot_date)                               AS snapshot_date,
    toDateTime64(update_time / 1000, 3, 'UTC')          AS update_time,
    symbol,
    toDecimal128OrZero(entry_price,       8)            AS entry_price,
    toDecimal128OrZero(mark_price,        8)            AS mark_price,
    toDecimal128OrZero(position_amt,      8)            AS position_amt,
    toDecimal128OrZero(unrealized_profit, 8)            AS unrealized_profit
FROM binance.kafka_account_snapshot_futures_position;


-- ============================================================
-- 常用分析查询示例
-- ============================================================

-- 查看现货账户历史余额趋势 (最近 30 天，BTC + USDT)
SELECT
    snapshot_date,
    groupArray(asset)   AS assets,
    groupArray(free)    AS free_amounts
FROM binance.account_snapshot_spot
WHERE snapshot_date >= today() - 30
  AND asset IN ('BTC', 'ETH', 'USDT')
GROUP BY snapshot_date
ORDER BY snapshot_date;

-- 各日期现货账户总 BTC 估值走势
SELECT
    snapshot_date,
    any(total_asset_of_btc)  AS total_btc
FROM binance.account_snapshot_spot
GROUP BY snapshot_date
ORDER BY snapshot_date;

-- 合约持仓历史 (某合约的开仓价变化)
SELECT
    snapshot_date,
    symbol,
    entry_price,
    position_amt,
    mark_price
FROM binance.account_snapshot_futures_position
WHERE symbol = 'BTCUSDT'
ORDER BY snapshot_date DESC
LIMIT 30;

-- 合约钱包余额日趋势
SELECT
    snapshot_date,
    asset,
    wallet_balance
FROM binance.account_snapshot_futures_asset
WHERE asset = 'USDT'
ORDER BY snapshot_date DESC
LIMIT 30;

-- 杠杆账户保证金等级日趋势
SELECT
    snapshot_date,
    any(margin_level)           AS margin_level,
    any(total_net_asset_of_btc) AS net_asset_btc
FROM binance.account_snapshot_margin
GROUP BY snapshot_date
ORDER BY snapshot_date DESC
LIMIT 30;


-- ============================================================
-- 注意事项
-- ============================================================
-- 1. 使用 ReplacingMergeTree 处理幂等写入：同一天多次采集到同一 (snapshot_date, asset)
--    时，最新写入的行（_insert_time 最大）会在后台 merge 时保留。
--    实时查询时需加 FINAL 关键字保证去重，例如：
--    SELECT * FROM binance.account_snapshot_spot FINAL WHERE snapshot_date = today();
--
-- 2. Kafka topics 对应关系:
--    binance.account.snapshot.spot             → account_snapshot_spot
--    binance.account.snapshot.margin           → account_snapshot_margin
--    binance.account.snapshot.futures.asset    → account_snapshot_futures_asset
--    binance.account.snapshot.futures.position → account_snapshot_futures_position
--
-- 3. Kafka group_name 每张表独立，避免消费 offset 互相影响。
--
-- 4. TTL 默认设为 1 年，按需调整。
--
-- 5. Decimal(30, 8) 用于精确存储加密货币数量，避免 Float64 精度损失。
