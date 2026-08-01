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
-- BTCUSDT 卖出信号生成视图（基于市场趋势度量和资金费率生成交易信号）
-- ------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS binance.strategy_BTCUSDT_SELL
To binance.strategy_signal AS
WITH 
regime AS
	(
		SELECT 
			argMax(rsi_14,open_time) AS rsi_14,
			argMax(adx_14,open_time) AS adx_14,
			(argMax(atr_14,open_time)/argMax(close,open_time)) * 100 as atr_prct
		FROM v_usdt_futures_regime
		WHERE symbol = 'BTCUSDT'
	),
market AS
	(
		SELECT 
			argMax(last_funding_rate,timestamp) AS lr
		FROM  mark_price
		WHERE symbol='BTCUSDT'
	)
SELECT 
    generateUUIDv4()						AS signal_id,
    'BTCUSDT_ARB'							AS strategy_id,
    'futures'								AS market,
    'BTCUSDT'								AS symbol,
    'PLACE_ORDER' 							AS action,
    toUnixTimestamp(now()) * 1000 			AS signal_ts_ms,
    60000       							AS ttl_ms,        -- 60 秒有效
    100         							AS priority,
    'SELL'									AS side,
    'LIMIT' 								AS order_type,
    p.position_amt						 	AS quantity, --后期通过仓位计算
    round(p.mark_price * 0.999,2)			AS price,
    'GTC'       AS time_in_force,
    'BOTH'      AS position_side,
    'false'     AS reduce_only,
    'false'     AS close_position,
    generateUUIDv4()      					AS order_id,
    generateUUIDv4()      					AS client_order_id
FROM current_futures_position p
CROSS JOIN regime
CROSS JOIN market
WHERE 
	p.position_amt > 0
AND
	p.symbol = 'BTCUSDT'
AND
(
	(
		regime.rsi_14 > 70
		AND
		regime.adx_14 < 20
		AND
		regime.atr_prct > 2
	) OR
	(
		market.lr < 0.02
	)
)



-- ------------------------------------------------------------
-- ETHUSDT 卖出信号生成视图（基于市场趋势度量和资金费率生成交易信号）
-- ------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS binance.strategy_ETHUSDT_SELL
TO binance.strategy_signals
AS
WITH 
regime AS
	(
		SELECT 
			argMax(rsi_14,open_time) AS rsi_14,
			argMax(adx_14,open_time) AS adx_14,
			(argMax(atr_14,open_time)/argMax(close,open_time)) * 100 as atr_prct
		FROM v_usdt_futures_regime
		WHERE symbol = 'ETHUSDT'
	),
market AS
	(
		SELECT 
			abs(argMax(last_funding_rate,timestamp)*3*365) AS lr_annualized
		FROM  mark_price
		WHERE symbol='ETHUSDT'
	)
SELECT 
    generateUUIDv4()						AS signal_id,
    'ETHUSDT_FUNDING_ARB_SELL'							AS strategy_id,
    'futures'								AS market,
    'ETHUSDT'								AS symbol,
    'PLACE_ORDER' 							AS action,
    toUnixTimestamp(now()) * 1000 			AS signal_ts_ms,
    60000       							AS ttl_ms,        -- 60 秒有效
    100         							AS priority,
    'SELL'									AS side,
    'LIMIT' 								AS order_type,
    p.position_amt						 	AS quantity, 
    round(p.mark_price * 0.998,2)			AS price,
    'GTC'       AS time_in_force,
    'BOTH'      AS position_side,
    'false'     AS reduce_only,
    'false'     AS close_position,
    generateUUIDv4()      					AS order_id,
    generateUUIDv4()      					AS orig_client_order_id
FROM current_futures_position p
CROSS JOIN regime
CROSS JOIN market
WHERE 
	p.position_amt > 0
AND
	p.symbol = 'ETHUSDT'
AND
(
	(
		regime.rsi_14 > 70
		AND
		regime.adx_14 < 20
		AND
		regime.atr_prct > 2
	) OR
		market.lr_annualized < 5
);


-- ------------------------------------------------------------
-- BTCUSDT 买入信号生成视图（基于市场趋势度量和资金费率生成交易信号）
-- ------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS binance.strategy_BTCUSDT_BUY
To binance.strategy_signal AS
WITH
wallet AS
(
    SELECT 
        argMax(wallet_balance,update_time) AS wallet_balance
    FROM account_snapshot_futures_asset
)
SELECT
    generateUUIDv4()                    AS signal_id,
    'BTC_FUNDING_ARB_BUY'               AS strategy_id,
    'BTCUSDT'                           AS symbol,
    'PLACE_ORDER'                       AS action,
    'BUY'                               AS side,
    'LIMIT'                             AS order_type,
    toUnixTimestamp(now()) * 1000       AS signal_ts_ms,
    60000                               AS ttl_ms,
    50                                  AS priority,
    round(wallet.wallet_balance/m.mark_price,8)  AS quantity,
    round(m.mark_price * 1.001,2)         AS price,
    'GTC'                               AS time_in_force,
    generateUUIDv4()      				AS order_id,
    generateUUIDv4()      				AS client_order_id
FROM
(
    SELECT
        argMax(mark_price,timestamp) AS mark_price,
        argMax(last_funding_rate,timestamp) AS funding_rate
    FROM mark_price
    WHERE symbol='BTCUSDT'
) m
CROSS JOIN wallet
WHERE
funding_rate > 0.002
AND
wallet_balance > 1000