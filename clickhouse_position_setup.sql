-- ============================================================
-- ClickHouse 消费 Kafka U 本位合约当前持仓数据建表方案
-- 适用数据来源: binance-toolkit futures-positions --write-kafka
--
-- 数据来源 API:
--   WebSocket v2/account.position
--
-- 整体架构:
--   Kafka Topic (binance.position.usdt_futures)
--       ↓
--   Kafka 引擎表  (消费入口，不持久化)
--       ↓  (Materialized View 触发)
--   ReplacingMergeTree 存储表  (当前持仓状态，全量覆盖)
--       ↓
--   当前持仓视图  (过滤零仓位，结果与实际持仓完全一致)
--
-- 设计原则：数据库与实际持仓始终保持一致，不多也不少
--   1. Python 侧每次写入全量持仓（含 positionAmt=0 的已平仓记录）
--   2. ReplacingMergeTree(queried_at)：以查询时间戳作为版本号
--   3. ORDER BY (symbol, position_side)：不含时间维度，同一仓位的新写入覆盖旧记录
--   4. 视图过滤 position_amt != 0：平仓后从视图中消失，与实际持仓一致
-- ============================================================


-- ------------------------------------------------------------
-- Step 0: 建库
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS binance;


-- ============================================================
-- Kafka 引擎表（消费入口，不存储数据）
-- ============================================================
DROP TABLE IF EXISTS binance.kafka_futures_position;
CREATE TABLE binance.kafka_futures_position
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
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.position.usdt_futures',
    kafka_group_name            = 'clickhouse_futures_position',
    kafka_format                = 'JSONEachRow',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;


-- ============================================================
-- 持久化存储表（ReplacingMergeTree，实现全量覆盖语义）
--
-- 核心设计：
--   ENGINE = ReplacingMergeTree(queried_at)
--     queried_at 作为版本号，版本更高（更新）的记录在 merge 时保留
--   ORDER BY (symbol, position_side)
--     不含时间维度：同一仓位 (symbol, position_side) 共用一个主键槽
--     每次全量写入后，新记录的版本号更大，最终覆盖旧记录
--   TTL toDate(queried_at) + INTERVAL 7 DAY
--     7 天后自动清理历史版本，防止旧数据无限堆积
-- ============================================================
DROP TABLE IF EXISTS binance.futures_position;
CREATE TABLE binance.futures_position
(
    symbol                     LowCardinality(String)      COMMENT '合约交易对, 如 BTCUSDT',
    position_side              LowCardinality(String)      COMMENT '持仓方向: BOTH / LONG / SHORT',
    position_amt               Decimal(18, 8)              COMMENT '持仓数量 (正=多仓, 负=空仓, 0=已平仓)',
    entry_price                Decimal(18, 8)              COMMENT '开仓均价',
    break_even_price           Decimal(18, 8)              COMMENT '盈亏平衡价格',
    mark_price                 Decimal(18, 8)              COMMENT '标记价格',
    unrealized_profit          Decimal(18, 8)              COMMENT '未实现盈亏',
    liquidation_price          Decimal(18, 8)              COMMENT '强平价格 (全仓模式为 0)',
    isolated_margin            Decimal(18, 8)              COMMENT '逐仓保证金',
    notional                   Decimal(18, 8)              COMMENT '名义价值',
    margin_asset               LowCardinality(String)      COMMENT '保证金资产',
    isolated_wallet            Decimal(18, 8)              COMMENT '逐仓钱包余额',
    initial_margin             Decimal(18, 8)              COMMENT '初始保证金',
    maint_margin               Decimal(18, 8)              COMMENT '维持保证金',
    position_initial_margin    Decimal(18, 8)              COMMENT '持仓初始保证金',
    open_order_initial_margin  Decimal(18, 8)              COMMENT '挂单初始保证金',
    adl                        Int8                        COMMENT '自动减仓队列等级',
    bid_notional               Decimal(18, 8)              COMMENT '买单名义价值',
    ask_notional               Decimal(18, 8)              COMMENT '卖单名义价值',
    update_time                Int64                       COMMENT 'Binance 持仓更新时间戳 (毫秒)',
    updated_at                 Nullable(DateTime64(6, 'UTC')) COMMENT 'Binance 持仓更新时间',
    queried_at                 DateTime64(6, 'UTC')        COMMENT '查询发起时间 (版本号)',
    recorded_at                DateTime64(6, 'UTC')        COMMENT '写入 Kafka 时间'
)
ENGINE = ReplacingMergeTree(queried_at)
ORDER BY (symbol, position_side)
TTL toDate(queried_at) + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;


-- ============================================================
-- 当前持仓视图（与实际持仓实时一致）
--
-- FINAL：强制在查询时执行去重，返回每个 (symbol, position_side)
--         queried_at 最大（最新）的那条记录（即使后台 merge 尚未完成）
-- WHERE position_amt != 0：过滤掉已平仓的零仓位记录
-- ============================================================
DROP VIEW IF EXISTS binance.v_current_futures_position;
CREATE VIEW binance.v_current_futures_position AS
SELECT
    symbol,
    position_side,
    position_amt,
    entry_price,
    break_even_price,
    mark_price,
    unrealized_profit,
    liquidation_price,
    isolated_margin,
    notional,
    margin_asset,
    initial_margin,
    maint_margin,
    position_initial_margin,
    open_order_initial_margin,
    adl,
    update_time,
    updated_at,
    queried_at
FROM binance.futures_position FINAL
WHERE position_amt != 0;


-- ============================================================
-- Materialized View（Kafka 引擎表 → 存储表）
-- ============================================================
DROP VIEW IF EXISTS binance.mv_futures_position;
CREATE MATERIALIZED VIEW binance.mv_futures_position
TO binance.futures_position
AS SELECT
    symbol,
    position_side,
    toDecimal64(ifNull(position_amt, '0'), 8)              AS position_amt,
    toDecimal64(ifNull(entry_price, '0'), 8)               AS entry_price,
    toDecimal64(ifNull(break_even_price, '0'), 8)          AS break_even_price,
    toDecimal64(ifNull(mark_price, '0'), 8)                AS mark_price,
    toDecimal64(ifNull(unrealized_profit, '0'), 8)         AS unrealized_profit,
    toDecimal64(ifNull(liquidation_price, '0'), 8)         AS liquidation_price,
    toDecimal64(ifNull(isolated_margin, '0'), 8)           AS isolated_margin,
    toDecimal64(ifNull(notional, '0'), 8)                  AS notional,
    ifNull(margin_asset, 'USDT')                           AS margin_asset,
    toDecimal64(ifNull(isolated_wallet, '0'), 8)           AS isolated_wallet,
    toDecimal64(ifNull(initial_margin, '0'), 8)            AS initial_margin,
    toDecimal64(ifNull(maint_margin, '0'), 8)              AS maint_margin,
    toDecimal64(ifNull(position_initial_margin, '0'), 8)   AS position_initial_margin,
    toDecimal64(ifNull(open_order_initial_margin, '0'), 8) AS open_order_initial_margin,
    ifNull(adl, 0)                                         AS adl,
    toDecimal64(ifNull(bid_notional, '0'), 8)              AS bid_notional,
    toDecimal64(ifNull(ask_notional, '0'), 8)              AS ask_notional,
    ifNull(update_time, 0)                                 AS update_time,
    if(updated_at IS NULL, NULL,
       parseDateTimeBestEffort(updated_at))                AS updated_at,
    parseDateTimeBestEffort(ifNull(queried_at, ''))        AS queried_at,
    parseDateTimeBestEffort(ifNull(recorded_at, ''))       AS recorded_at
FROM binance.kafka_futures_position;


-- ============================================================
-- 常用查询示例
-- ============================================================

-- 查看当前所有活跃持仓（与实际持仓完全一致）
-- SELECT *
-- FROM binance.v_current_futures_position
-- ORDER BY symbol;

-- 不使用视图时，直接查询需加 FINAL 并过滤零仓位
-- SELECT symbol, position_side, position_amt, entry_price, unrealized_profit, queried_at
-- FROM binance.futures_position FINAL
-- WHERE position_amt != 0
-- ORDER BY symbol;

-- 手动触发后台合并（可选，用于减少存储占用或加速 FINAL 查询）
-- OPTIMIZE TABLE binance.futures_position FINAL;


-- ============================================================
-- 注意事项
-- ============================================================
-- 1. Python 侧必须进行全量查询（不指定 symbol 参数），否则无法感知
--    其他合约的平仓事件，导致数据库残留已平仓的历史记录。
--
-- 2. ReplacingMergeTree 的去重在后台 merge 时发生，不是实时的。
--    实时查询时务必使用 FINAL 或通过视图 v_current_futures_position 查询。
--
-- 3. TTL 设为 7 天，自动清理历史版本。如需保留更长时间的历史快照，
--    请调整 TTL，或另建独立的历史归档表（不影响当前持仓表的覆盖语义）。
--
-- 4. account_snapshot_futures_position（每日快照表）是独立的历史日志，
--    职责与本表不同，两者互不影响。
