-- ============================================================
-- ClickHouse 消费 Kafka 策略引擎审计数据建表方案
-- 适用数据来源: binance-toolkit engine-futures
-- Kafka Topic: binance.engine.futures
--
-- 整体架构:
--   Kafka Topic: binance.engine.futures
--       ↓
--   Kafka 引擎表  (JSONAsString，保留原始 JSON)
--       ↓  (Materialized View 触发解析)
--   MergeTree 存储表  (结构化字段 + raw_json)
--
-- 设计说明:
-- 1. 审计事件字段会随着引擎演进而增加，不适合直接用 JSONEachRow 严格绑死列结构。
-- 2. 因此 Kafka 引擎表采用 JSONAsString，只接收原始 JSON 文本。
-- 3. 在 MV 中按需提取稳定字段，并保留 raw_json 方便后续补字段/排障。
-- ============================================================


-- ------------------------------------------------------------
-- Step 0: 建库
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS binance;


-- ------------------------------------------------------------
-- Step 1: Kafka 引擎表（消费入口）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS binance.kafka_engine_audit_raw;
CREATE TABLE binance.kafka_engine_audit_raw
(
    raw String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list           = 'localhost:9092',
    kafka_topic_list            = 'binance.engine.futures',
    kafka_group_name            = 'clickhouse_engine_audit',
    kafka_format                = 'JSONAsString',
    kafka_num_consumers         = 1,
    kafka_skip_broken_messages  = 10;


-- ------------------------------------------------------------
-- Step 2: 存储表（结构化审计事件）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS binance.engine_audit;
CREATE TABLE binance.engine_audit
(
    -- 基础事件信息
    recorded_at             DateTime64(3, 'UTC')                 COMMENT '事件记录时间',
    event_type              LowCardinality(String)               COMMENT '事件类型，如 signal_received / engine_started',
    status                  LowCardinality(Nullable(String))     COMMENT '状态字段，可为空',
    reason                  Nullable(String)                     COMMENT '原因说明，可为空',

    -- 信号维度
    signal_id               Nullable(String)                     COMMENT '信号 ID',
    strategy_id             LowCardinality(Nullable(String))     COMMENT '策略 ID',
    symbol                  LowCardinality(Nullable(String))     COMMENT '交易对',
    action                  LowCardinality(Nullable(String))     COMMENT '动作类型',
    signal_ts_ms            Nullable(Int64)                      COMMENT '信号时间戳（毫秒）',
    priority                Nullable(Int32)                      COMMENT '信号优先级',

    -- 执行/运行时补充字段
    order_id                Nullable(Int64)                      COMMENT '订单 ID',
    client_order_id         Nullable(String)                     COMMENT '客户端订单 ID',
    cursor_ms               Nullable(Int64)                      COMMENT '引擎当前 cursor',
    dry_run                 Nullable(Bool)                       COMMENT '是否 dry-run 启动',
    error                   Nullable(String)                     COMMENT '错误信息',

    -- 指标快照
    metrics_pulled          Nullable(Int64)                      COMMENT '累计拉取信号数',
    metrics_accepted        Nullable(Int64)                      COMMENT '累计接收执行数',
    metrics_rejected        Nullable(Int64)                      COMMENT '累计拒绝数',
    metrics_executed        Nullable(Int64)                      COMMENT '累计执行数',
    metrics_failed          Nullable(Int64)                      COMMENT '累计失败数',
    metrics_deduplicated    Nullable(Int64)                      COMMENT '累计去重数',
    metrics_reconciled      Nullable(Int64)                      COMMENT '累计补偿数',

    -- 原始 JSON，便于后续补字段与问题排查
    raw_json                String,
    _insert_time            DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(recorded_at)
ORDER BY (event_type, ifNull(strategy_id, ''), ifNull(symbol, ''), recorded_at)
TTL recorded_at + INTERVAL 180 DAY
SETTINGS index_granularity = 8192;


-- ------------------------------------------------------------
-- Step 3: 物化视图（解析 raw JSON → 存储表）
-- ------------------------------------------------------------
DROP VIEW IF EXISTS binance.mv_engine_audit;
CREATE MATERIALIZED VIEW binance.mv_engine_audit
TO binance.engine_audit
AS
SELECT
    parseDateTime64BestEffortOrNull(JSONExtractString(raw, 'recorded_at'))                  AS recorded_at,
    JSONExtractString(raw, 'event_type')                                                    AS event_type,
    nullIf(JSONExtractString(raw, 'status'), '')                                            AS status,
    nullIf(JSONExtractString(raw, 'reason'), '')                                            AS reason,

    nullIf(JSONExtractString(raw, 'signal_id'), '')                                         AS signal_id,
    nullIf(JSONExtractString(raw, 'strategy_id'), '')                                       AS strategy_id,
    nullIf(JSONExtractString(raw, 'symbol'), '')                                            AS symbol,
    nullIf(JSONExtractString(raw, 'action'), '')                                            AS action,
    if(JSONHas(raw, 'signal_ts_ms'), toInt64(JSONExtractInt(raw, 'signal_ts_ms')), NULL)    AS signal_ts_ms,
    if(JSONHas(raw, 'priority'), toInt32(JSONExtractInt(raw, 'priority')), NULL)            AS priority,

    if(JSONHas(raw, 'order_id'), toInt64(JSONExtractInt(raw, 'order_id')), NULL)            AS order_id,
    nullIf(JSONExtractString(raw, 'client_order_id'), '')                                   AS client_order_id,
    if(JSONHas(raw, 'cursor_ms'), toInt64(JSONExtractInt(raw, 'cursor_ms')), NULL)          AS cursor_ms,
    if(JSONHas(raw, 'dry_run'), JSONExtractBool(raw, 'dry_run'), NULL)                      AS dry_run,
    nullIf(JSONExtractString(raw, 'error'), '')                                             AS error,

    if(JSONHas(raw, 'metrics', 'pulled'), toInt64(JSONExtractInt(raw, 'metrics', 'pulled')), NULL)                    AS metrics_pulled,
    if(JSONHas(raw, 'metrics', 'accepted'), toInt64(JSONExtractInt(raw, 'metrics', 'accepted')), NULL)                AS metrics_accepted,
    if(JSONHas(raw, 'metrics', 'rejected'), toInt64(JSONExtractInt(raw, 'metrics', 'rejected')), NULL)                AS metrics_rejected,
    if(JSONHas(raw, 'metrics', 'executed'), toInt64(JSONExtractInt(raw, 'metrics', 'executed')), NULL)                AS metrics_executed,
    if(JSONHas(raw, 'metrics', 'failed'), toInt64(JSONExtractInt(raw, 'metrics', 'failed')), NULL)                    AS metrics_failed,
    if(JSONHas(raw, 'metrics', 'deduplicated'), toInt64(JSONExtractInt(raw, 'metrics', 'deduplicated')), NULL)        AS metrics_deduplicated,
    if(JSONHas(raw, 'metrics', 'reconciled'), toInt64(JSONExtractInt(raw, 'metrics', 'reconciled')), NULL)            AS metrics_reconciled,

    raw                                                                                      AS raw_json,
    now()                                                                                    AS _insert_time
FROM binance.kafka_engine_audit_raw
WHERE JSONExtractString(raw, 'event_type') != '';


-- ------------------------------------------------------------
-- Step 4: 常用查询示例
-- ------------------------------------------------------------

-- 查看最近 20 条审计事件
SELECT
    recorded_at,
    event_type,
    strategy_id,
    symbol,
    action,
    status,
    reason
FROM binance.engine_audit
ORDER BY recorded_at DESC
LIMIT 20;

-- 查看最近 1 小时每类事件数量
SELECT
    event_type,
    count() AS cnt
FROM binance.engine_audit
WHERE recorded_at >= now() - INTERVAL 1 HOUR
GROUP BY event_type
ORDER BY cnt DESC;

-- 查看最近 1 小时失败事件
SELECT
    recorded_at,
    signal_id,
    strategy_id,
    symbol,
    action,
    reason,
    error
FROM binance.engine_audit
WHERE event_type IN ('signal_failed', 'engine_loop_error', 'signal_reconcile_failed')
  AND recorded_at >= now() - INTERVAL 1 HOUR
ORDER BY recorded_at DESC;

-- 查看每个策略最近一次指标快照
SELECT
    strategy_id,
    argMax(metrics_pulled, recorded_at)       AS pulled,
    argMax(metrics_accepted, recorded_at)     AS accepted,
    argMax(metrics_rejected, recorded_at)     AS rejected,
    argMax(metrics_executed, recorded_at)     AS executed,
    argMax(metrics_failed, recorded_at)       AS failed,
    argMax(metrics_deduplicated, recorded_at) AS deduplicated,
    argMax(metrics_reconciled, recorded_at)   AS reconciled,
    max(recorded_at)                          AS last_seen
FROM binance.engine_audit
WHERE strategy_id IS NOT NULL
GROUP BY strategy_id
ORDER BY last_seen DESC;


-- ------------------------------------------------------------
-- Step 5: 清理命令（谨慎使用）
-- ------------------------------------------------------------
-- DROP VIEW IF EXISTS binance.mv_engine_audit;
-- DROP TABLE IF EXISTS binance.kafka_engine_audit_raw;
-- DROP TABLE IF EXISTS binance.engine_audit;


-- ------------------------------------------------------------
-- 注意事项
-- ------------------------------------------------------------
-- 1. 该方案使用 JSONAsString，新增审计字段时通常无需改 Kafka 引擎表。
-- 2. 若后续需要分析更多字段，可直接 ALTER TABLE + 重建 MV，或从 raw_json 回填。
-- 3. kafka_group_name 不能与其他消费者重复，否则会争抢 offset。
-- 4. recorded_at 解析失败的消息会被过滤掉（MV 的 WHERE 只过滤 event_type 为空，
--    若 recorded_at 为空会写入 NULL，建议生产侧始终带 recorded_at）。