-- ============================================================
-- U 本位合约当前持仓表
-- 适用数据来源: binance-toolkit futures-positions --write-clickhouse
--
-- 设计原则：
--   不保留历史数据。Python 每次查询后执行 TRUNCATE + INSERT，
--   表中始终只有本次查询到的活跃持仓（positionAmt != 0）。
--   空仓时表为空。
-- ============================================================


-- ------------------------------------------------------------
-- Step 1: 清理之前错误建立的冗余旧表/视图
-- ------------------------------------------------------------
DROP VIEW IF EXISTS binance.mv_futures_position;
DROP TABLE IF EXISTS binance.futures_position;
DROP TABLE IF EXISTS binance.kafka_futures_position;
DROP VIEW IF EXISTS binance.v_current_futures_position;
DROP VIEW IF EXISTS v_current_futures_position;


-- ------------------------------------------------------------
-- Step 2: 当前持仓表（Python 直写，TRUNCATE + INSERT 语义）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS current_futures_position
(
    symbol                    String,
    position_side             String,
    position_amt              Float64,
    entry_price               Float64,
    break_even_price          Float64,
    mark_price                Float64,
    unrealized_profit         Float64,
    liquidation_price         Float64,
    isolated_margin           Float64,
    notional                  Float64,
    margin_asset              String,
    isolated_wallet           Float64,
    initial_margin            Float64,
    maint_margin              Float64,
    position_initial_margin   Float64,
    open_order_initial_margin Float64,
    adl                       Int32,
    bid_notional              Float64,
    ask_notional              Float64,
    update_time               Int64,
    updated_at                DateTime64(3, 'UTC'),
    queried_at                DateTime64(3, 'UTC')
)
ENGINE = MergeTree()
ORDER BY (symbol, position_side);


-- ------------------------------------------------------------
-- 常用查询
-- ------------------------------------------------------------

-- 查看当前所有活跃持仓（与实际持仓完全一致）
-- SELECT *
-- FROM current_futures_position
-- ORDER BY symbol;


-- ============================================================
-- 注意事项
-- ============================================================
-- 1. 使用 --write-clickhouse 参数，而非 --write-kafka：
--      python -m binance_toolkit futures-positions --write-clickhouse
--
-- 2. 不要加 --symbol 参数，否则只写入指定合约，其他合约的
--    平仓状态将无法被感知（表不会被清空为空仓）。
--
-- 3. config.json 中需配置 clickhouse_signal_url（ClickHouse HTTP 地址，
--    如 http://localhost:8123），以及 clickhouse_database（默认 default）。
