-- ============================================================================
-- ClickHouse 表结构：从 Kafka 消费 PnL 数据
-- ============================================================================
-- 
-- 架构说明：
-- 1. Kafka Engine 表：直接消费 Kafka 数据（不存储）
-- 2. MergeTree 目标表：实际存储数据
-- 3. Materialized View：自动将 Kafka 数据写入目标表
--
-- 使用步骤：
-- 1. 创建数据库
-- 2. 创建 Kafka Engine 表
-- 3. 创建 MergeTree 存储表
-- 4. 创建 Materialized View 连接两者
-- ============================================================================

-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS binance;

-- ============================================================================
-- 现货 PnL (Spot PnL)
-- ============================================================================

-- 1. Kafka Engine 表 - 消费 binance.pnl.spot Topic
DROP TABLE IF EXISTS binance.kafka_spot_pnl;
CREATE TABLE binance.kafka_spot_pnl
(
    `symbol`             String,
    `order_id`           String,
    `buy_price`          Float64,
    `current_price`      Float64,
    `quantity`           Float64,
    `cost`               Float64,
    `current_value`      Float64,
    `sell_value`         Float64,
    `unrealized_pnl`     Float64,
    `unrealized_pnl_pct` Float64,
    `fee_rate`           Float64,
    `timestamp`          String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'localhost:9092',  -- 修改为你的 Kafka 地址
    kafka_topic_list = 'binance.pnl.spot',
    kafka_group_name = 'clickhouse_spot_pnl_consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_max_block_size = 1048576;

-- 2. MergeTree 存储表
DROP TABLE IF EXISTS binance.spot_pnl;
CREATE TABLE binance.spot_pnl
(
    `symbol`             String        COMMENT '币种符号 (如 BTC)',
    `order_id`           String        COMMENT '关联订单ID (用于关联现货和合约交易)',
    `buy_price`          Float64       COMMENT '买入均价',
    `current_price`      Float64       COMMENT '当前价格 (index price)',
    `quantity`           Float64       COMMENT '持有数量',
    `cost`               Float64       COMMENT '买入成本 (含手续费)',
    `current_value`      Float64       COMMENT '当前市值',
    `sell_value`         Float64       COMMENT '卖出后实际到账 (扣手续费)',
    `unrealized_pnl`     Float64       COMMENT '未实现盈亏',
    `unrealized_pnl_pct` Float64       COMMENT '盈亏百分比 (%)',
    `fee_rate`           Float64       COMMENT '手续费率',
    `timestamp`          DateTime64(3) COMMENT '时间戳 (UTC)',
    
    INDEX idx_symbol symbol TYPE bloom_filter GRANULARITY 4,
    INDEX idx_order_id order_id TYPE bloom_filter GRANULARITY 4
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (order_id, symbol, timestamp)
TTL timestamp + INTERVAL 90 DAY  -- 数据保留 90 天
SETTINGS index_granularity = 8192;

-- 3. Materialized View - 自动从 Kafka 消费并写入存储表
DROP VIEW IF EXISTS binance.mv_spot_pnl;
CREATE MATERIALIZED VIEW binance.mv_spot_pnl
TO binance.spot_pnl
AS SELECT
    symbol,
    order_id,
    buy_price,
    current_price,
    quantity,
    cost,
    current_value,
    sell_value,
    unrealized_pnl,
    unrealized_pnl_pct,
    fee_rate,
    parseDateTime64BestEffort(timestamp) AS timestamp
FROM binance.kafka_spot_pnl;


-- ============================================================================
-- 合约 PnL (Futures PnL)
-- ============================================================================

-- 1. Kafka Engine 表 - 消费 binance.pnl.futures Topic
DROP TABLE IF EXISTS binance.kafka_futures_pnl;
CREATE TABLE binance.kafka_futures_pnl
(
    `symbol`                  String,
    `order_id`                String,
    `side`                    String,
    `margin_type`             String,
    `leverage`                Int32,
    `entry_price`             Float64,
    `mark_price`              Float64,
    `index_price`             Float64,
    `quantity`                Float64,
    `margin`                  Float64,
    `notional_value`          Float64,
    `unrealized_pnl`          Float64,
    `unrealized_pnl_with_fee` Float64,
    `roe`                     Float64,
    `funding_rate`            Float64,
    `fee_rate`                Float64,
    `timestamp`               String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'localhost:9092',  -- 修改为你的 Kafka 地址
    kafka_topic_list = 'binance.pnl.futures',
    kafka_group_name = 'clickhouse_futures_pnl_consumer',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_max_block_size = 1048576;

-- 2. MergeTree 存储表
DROP TABLE IF EXISTS binance.futures_pnl;
CREATE TABLE binance.futures_pnl
(
    `symbol`                  String        COMMENT '合约交易对 (如 BTCUSDT)',
    `order_id`                String        COMMENT '关联订单ID (用于关联现货和合约交易)',
    `side`                    Enum8('LONG' = 1, 'SHORT' = 2) COMMENT '持仓方向',
    `margin_type`             Enum8('USDT' = 1, 'COIN' = 2)  COMMENT '保证金类型',
    `leverage`                Int32         COMMENT '杠杆倍数',
    `entry_price`             Float64       COMMENT '开仓均价',
    `mark_price`              Float64       COMMENT '标记价格',
    `index_price`             Float64       COMMENT '指数价格',
    `quantity`                Float64       COMMENT '持仓数量',
    `margin`                  Float64       COMMENT '保证金',
    `notional_value`          Float64       COMMENT '名义价值',
    `unrealized_pnl`          Float64       COMMENT '未实现盈亏',
    `unrealized_pnl_with_fee` Float64       COMMENT '未实现盈亏 (含手续费)',
    `roe`                     Float64       COMMENT 'ROE 百分比 (%)',
    `funding_rate`            Float64       COMMENT '资金费率',
    `fee_rate`                Float64       COMMENT '手续费率',
    `timestamp`               DateTime64(3) COMMENT '时间戳 (UTC)',
    
    INDEX idx_symbol symbol TYPE bloom_filter GRANULARITY 4,
    INDEX idx_order_id order_id TYPE bloom_filter GRANULARITY 4,
    INDEX idx_side side TYPE minmax GRANULARITY 4
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (order_id, symbol, side, timestamp)
TTL timestamp + INTERVAL 90 DAY  -- 数据保留 90 天
SETTINGS index_granularity = 8192;

-- 3. Materialized View - 自动从 Kafka 消费并写入存储表
DROP VIEW IF EXISTS binance.mv_futures_pnl;
CREATE MATERIALIZED VIEW binance.mv_futures_pnl
TO binance.futures_pnl
AS SELECT
    symbol,
    order_id,
    side,
    margin_type,
    leverage,
    entry_price,
    mark_price,
    index_price,
    quantity,
    margin,
    notional_value,
    unrealized_pnl,
    unrealized_pnl_with_fee,
    roe,
    funding_rate,
    fee_rate,
    parseDateTime64BestEffort(timestamp) AS timestamp
FROM binance.kafka_futures_pnl;


-- ============================================================================
-- 常用查询示例
-- ============================================================================

-- 查询最新现货 PnL
-- SELECT * FROM binance.spot_pnl ORDER BY timestamp DESC LIMIT 10;

-- 查询最新合约 PnL
-- SELECT * FROM binance.futures_pnl ORDER BY timestamp DESC LIMIT 10;

-- 通过 order_id 关联查询现货和合约 PnL
-- SELECT 
--     s.order_id,
--     s.symbol AS spot_symbol,
--     s.unrealized_pnl AS spot_pnl,
--     f.symbol AS futures_symbol,
--     f.side AS futures_side,
--     f.unrealized_pnl AS futures_pnl,
--     (s.unrealized_pnl + f.unrealized_pnl) AS total_pnl
-- FROM binance.spot_pnl s
-- JOIN binance.futures_pnl f ON s.order_id = f.order_id
-- WHERE s.timestamp > now() - INTERVAL 1 HOUR
-- ORDER BY s.timestamp DESC
-- LIMIT 10;

-- 查询某币种的盈亏历史
-- SELECT 
--     toStartOfMinute(timestamp) AS minute,
--     symbol,
--     avg(unrealized_pnl) AS avg_pnl,
--     max(unrealized_pnl) AS max_pnl,
--     min(unrealized_pnl) AS min_pnl
-- FROM binance.spot_pnl
-- WHERE symbol = 'BTC' AND timestamp > now() - INTERVAL 1 HOUR
-- GROUP BY minute, symbol
-- ORDER BY minute DESC;

-- 查询合约 ROE 分布
-- SELECT 
--     symbol,
--     side,
--     count() AS cnt,
--     avg(roe) AS avg_roe,
--     max(roe) AS max_roe,
--     min(roe) AS min_roe
-- FROM binance.futures_pnl
-- WHERE timestamp > now() - INTERVAL 1 DAY
-- GROUP BY symbol, side
-- ORDER BY avg_roe DESC;

-- 查询总盈亏汇总 (按分钟)
-- SELECT 
--     toStartOfMinute(timestamp) AS minute,
--     sum(unrealized_pnl) AS total_pnl,
--     sum(margin) AS total_margin,
--     sum(unrealized_pnl) / sum(margin) * 100 AS total_roe_pct
-- FROM binance.futures_pnl
-- WHERE timestamp > now() - INTERVAL 1 HOUR
-- GROUP BY minute
-- ORDER BY minute DESC;


-- ============================================================================
-- 清理命令（谨慎使用）
-- ============================================================================

-- 删除所有相关表和视图
-- DROP VIEW IF EXISTS binance.mv_spot_pnl;
-- DROP VIEW IF EXISTS binance.mv_futures_pnl;
-- DROP TABLE IF EXISTS binance.kafka_spot_pnl;
-- DROP TABLE IF EXISTS binance.kafka_futures_pnl;
-- DROP TABLE IF EXISTS binance.spot_pnl;
-- DROP TABLE IF EXISTS binance.futures_pnl;
