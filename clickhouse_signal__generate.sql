-- ------------------------------------------------------------
-- Step 1: 建库
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS binance;




-- ------------------------------------------------------------
-- Step 2: 建立市场趋势度量表视图（基于 K线数据计算技术指标）
-- 注意：每次查询会扫描 usdt_kline FINAL，数据量大时加 WHERE 过滤
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW binance.v_usdt_futures_regime AS
WITH base AS
(
    SELECT
        symbol,
        interval,
        open_time,

        toFloat64(high)  AS high,
        toFloat64(low)   AS low,
        toFloat64(close) AS close,

        lagInFrame(toFloat64(high))
            OVER (PARTITION BY symbol, interval ORDER BY open_time) AS prev_high,

        lagInFrame(toFloat64(low))
            OVER (PARTITION BY symbol, interval ORDER BY open_time) AS prev_low,

        lagInFrame(toFloat64(close))
            OVER (PARTITION BY symbol, interval ORDER BY open_time) AS prev_close

    FROM binance.usdt_kline
    WHERE is_closed = 1
),

tr_dm AS
(
    SELECT
        *,
        greatest(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        ) AS tr,

        high - prev_high AS up_move,
        prev_low - low   AS down_move,

        close - prev_close AS change
    FROM base
),

dm_calc AS
(
    SELECT
        *,

        if(up_move > down_move AND up_move > 0, up_move, 0) AS plus_dm,
        if(down_move > up_move AND down_move > 0, down_move, 0) AS minus_dm,

        if(change > 0, change, 0) AS gain,
        if(change < 0, -change, 0) AS loss

    FROM tr_dm
),

smooth AS
(
    SELECT
        *,

        -- ===== ATR / DI =====
        avg(tr) OVER w AS atr_14,
        avg(plus_dm) OVER w AS plus_dm_14,
        avg(minus_dm) OVER w AS minus_dm_14,

        -- ===== RSI components =====
        avg(gain) OVER w AS avg_gain,
        avg(loss) OVER w AS avg_loss

    FROM dm_calc

    WINDOW w AS
    (
        PARTITION BY symbol, interval
        ORDER BY open_time
        ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
    )
),

di_calc AS
(
    SELECT
        *,

        100 * plus_dm_14 / nullIf(atr_14,0)  AS plus_di,
        100 * minus_dm_14 / nullIf(atr_14,0) AS minus_di,

        100 * abs(
            (avg_gain / nullIf(avg_loss,0))
        ) AS rs,

        100 - (100 / (1 + (avg_gain / nullIf(avg_loss,0)))) AS rsi_14

    FROM smooth
),

dx_calc AS
(
    SELECT
        *,

        100 * abs(plus_di - minus_di)
        / nullIf(plus_di + minus_di,0) AS dx

    FROM di_calc
)

SELECT
    symbol,
    interval,
    open_time,

    high,
    low,
    close,

    atr_14,
    plus_di,
    minus_di,
    rsi_14,

    avg(
        dx
    ) OVER (
        PARTITION BY symbol, interval
        ORDER BY open_time
        ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
    ) AS adx_14

FROM dx_calc
ORDER BY open_time;


-- ------------------------------------------------------------
-- Step 3: 手动生成买入信号
-- 注意：每次查询会扫描 usdt_kline FINAL，数据量大时加 WHERE 过滤
-- ------------------------------------------------------------

INSERT INTO binance.strategy_signals
SELECT
    rand()      AS signal_id,
    'demo'      AS strategy_id,
    'futures'   AS market,
    symbol,
    'PLACE_ORDER' AS action,

    toUnixTimestamp(now()) * 1000 AS signal_ts_ms,
    60000       AS ttl_ms,        -- 60 秒有效期
    100         AS priority,
    if(adx_14 > 25 AND plus_di > minus_di, 'buy',
        if(adx_14 > 25 AND minus_di > plus_di, 'sell', 'none')
    )           AS side,
    'LIMIT'     AS order_type,
    '5'     AS quantity,
    (select round(mark_price,0) from mark_price where symbol='ETHUSDT' order by timestamp desc limit 1) AS price,
    'GTC'       AS time_in_force,
    'BOTH'      AS position_side,
    'false'     AS reduce_only,
    'false'     AS close_position,
    rand()      AS order_id,
    rand()      AS client_order_id
FROM binance.v_usdt_futures_regime where symbol = 'ETHUSDT' and interval = '1d' and open_time >= now() - INTERVAL 30 DAY order by open_time desc limit 1;