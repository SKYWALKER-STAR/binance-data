-- ============================================================
-- Strategy Engine 信号样例数据 (ClickHouse Seed)
--
-- 用途:
-- 1) 快速向 strategy_signals 写入可测试的样例信号
-- 2) 覆盖 PLACE_ORDER / CANCEL_ORDER / CANCEL_ALL
-- 3) 包含 futures 和 spot 两种市场的样例
--
-- 建议测试顺序:
--   a) 先用 dry-run 启动引擎:
--      python -m binance_toolkit engine-futures --dry-run
--      python -m binance_toolkit engine-spot --dry-run
--   b) 执行本脚本插入信号
--   c) 查看 engine 日志 / Kafka 审计 topic
-- ============================================================

-- 可选: 如果你使用 binance 库, 先切库
-- USE binance;

-- 可选: 清理旧数据（按需打开）
-- TRUNCATE TABLE strategy_signals;

-- ============================================================
-- 合约信号样例 (market = 'futures')
-- ============================================================
INSERT INTO strategy_signals
(
    signal_id,
    strategy_id,
    market,
    symbol,
    action,
    signal_ts_ms,
    ttl_ms,
    priority,
    side,
    order_type,
    quantity,
    price,
    time_in_force,
    position_side,
    reduce_only,
    close_position,
    order_id,
    orig_client_order_id
)
WITH toInt64(toUnixTimestamp64Milli(now64(3))) AS base_ms
SELECT
    concat('sig_futures_', toString(base_ms), '_1') AS signal_id,
    'demo_trend' AS strategy_id,
    'futures' AS market,
    'BTCUSDT' AS symbol,
    'PLACE_ORDER' AS action,
    base_ms - 8000 AS signal_ts_ms,
    180000 AS ttl_ms,
    100 AS priority,
    'BUY' AS side,
    'LIMIT' AS order_type,
    '0.01' AS quantity,
    '65000' AS price,
    'GTC' AS time_in_force,
    'BOTH' AS position_side,
    'false' AS reduce_only,
    'false' AS close_position,
    CAST(NULL, 'Nullable(Int64)') AS order_id,
    CAST(NULL, 'Nullable(String)') AS orig_client_order_id
UNION ALL
SELECT
    concat('sig_futures_', toString(base_ms), '_2') AS signal_id,
    'demo_trend' AS strategy_id,
    'futures' AS market,
    'ETHUSDT' AS symbol,
    'PLACE_ORDER' AS action,
    base_ms - 7000 AS signal_ts_ms,
    180000 AS ttl_ms,
    90 AS priority,
    'SELL' AS side,
    'LIMIT' AS order_type,
    '0.05' AS quantity,
    '3500' AS price,
    'GTC' AS time_in_force,
    'BOTH' AS position_side,
    'false' AS reduce_only,
    'false' AS close_position,
    CAST(NULL, 'Nullable(Int64)') AS order_id,
    CAST(NULL, 'Nullable(String)') AS orig_client_order_id
UNION ALL
SELECT
    concat('sig_futures_', toString(base_ms), '_3') AS signal_id,
    'demo_cancel' AS strategy_id,
    'futures' AS market,
    'BTCUSDT' AS symbol,
    'CANCEL_ORDER' AS action,
    base_ms - 6000 AS signal_ts_ms,
    180000 AS ttl_ms,
    80 AS priority,
    CAST(NULL, 'Nullable(String)') AS side,
    CAST(NULL, 'Nullable(String)') AS order_type,
    CAST(NULL, 'Nullable(String)') AS quantity,
    CAST(NULL, 'Nullable(String)') AS price,
    CAST(NULL, 'Nullable(String)') AS time_in_force,
    CAST(NULL, 'Nullable(String)') AS position_side,
    CAST(NULL, 'Nullable(String)') AS reduce_only,
    CAST(NULL, 'Nullable(String)') AS close_position,
    CAST(123456789, 'Nullable(Int64)') AS order_id,
    CAST(NULL, 'Nullable(String)') AS orig_client_order_id;

-- ============================================================
-- 现货信号样例 (market = 'spot')
-- ============================================================
INSERT INTO strategy_signals
(
    signal_id,
    strategy_id,
    market,
    symbol,
    action,
    signal_ts_ms,
    ttl_ms,
    priority,
    side,
    order_type,
    quantity,
    price,
    time_in_force,
    position_side,
    reduce_only,
    close_position,
    order_id,
    orig_client_order_id
)
WITH toInt64(toUnixTimestamp64Milli(now64(3))) AS base_ms
SELECT
    concat('sig_spot_', toString(base_ms), '_1') AS signal_id,
    'demo_spot_buy' AS strategy_id,
    'spot' AS market,
    'BTCUSDT' AS symbol,
    'PLACE_ORDER' AS action,
    base_ms - 5000 AS signal_ts_ms,
    180000 AS ttl_ms,
    100 AS priority,
    'BUY' AS side,
    'LIMIT' AS order_type,
    '0.001' AS quantity,
    '65000' AS price,
    'GTC' AS time_in_force,
    CAST(NULL, 'Nullable(String)') AS position_side,
    CAST(NULL, 'Nullable(String)') AS reduce_only,
    CAST(NULL, 'Nullable(String)') AS close_position,
    CAST(NULL, 'Nullable(Int64)') AS order_id,
    CAST(NULL, 'Nullable(String)') AS orig_client_order_id
UNION ALL
SELECT
    concat('sig_spot_', toString(base_ms), '_2') AS signal_id,
    'demo_spot_sell' AS strategy_id,
    'spot' AS market,
    'ETHUSDT' AS symbol,
    'PLACE_ORDER' AS action,
    base_ms - 4000 AS signal_ts_ms,
    180000 AS ttl_ms,
    90 AS priority,
    'SELL' AS side,
    'MARKET' AS order_type,
    '0.01' AS quantity,
    CAST(NULL, 'Nullable(String)') AS price,
    CAST(NULL, 'Nullable(String)') AS time_in_force,
    CAST(NULL, 'Nullable(String)') AS position_side,
    CAST(NULL, 'Nullable(String)') AS reduce_only,
    CAST(NULL, 'Nullable(String)') AS close_position,
    CAST(NULL, 'Nullable(Int64)') AS order_id,
    CAST(NULL, 'Nullable(String)') AS orig_client_order_id
UNION ALL
SELECT
    concat('sig_spot_', toString(base_ms), '_3') AS signal_id,
    'demo_spot_cancel' AS strategy_id,
    'spot' AS market,
    'BTCUSDT' AS symbol,
    'CANCEL_ALL_ORDERS' AS action,
    base_ms - 3000 AS signal_ts_ms,
    180000 AS ttl_ms,
    80 AS priority,
    CAST(NULL, 'Nullable(String)') AS side,
    CAST(NULL, 'Nullable(String)') AS order_type,
    CAST(NULL, 'Nullable(String)') AS quantity,
    CAST(NULL, 'Nullable(String)') AS price,
    CAST(NULL, 'Nullable(String)') AS time_in_force,
    CAST(NULL, 'Nullable(String)') AS position_side,
    CAST(NULL, 'Nullable(String)') AS reduce_only,
    CAST(NULL, 'Nullable(String)') AS close_position,
    CAST(NULL, 'Nullable(Int64)') AS order_id,
    CAST(NULL, 'Nullable(String)') AS orig_client_order_id;


-- 验证刚写入的数据
SELECT
    signal_id,
    strategy_id,
    market,
    symbol,
    action,
    signal_ts_ms,
    ttl_ms,
    priority
FROM strategy_signals
WHERE signal_id LIKE 'sig_futures_%' OR signal_id LIKE 'sig_spot_%'
ORDER BY signal_ts_ms DESC
LIMIT 20;
