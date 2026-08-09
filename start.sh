#!/bin/bash


source /etc/profile
proxy_on

#nohup /warehouse/GitRepos/biannce-api/binance/bin/python -m binance_toolkit --config config.json collect > nohup.out 2>&1 &
#nohup /warehouse/GitRepos/biannce-api/binance/bin/python -m binance_toolkit --config config.json collect-mark > nohup.out 2>&1 &
#nohup /warehouse/GitRepos/biannce-api/binance/bin/python -m binance_toolkit --config config.json ws-mark-price-coin --write-kafka --sample-interval 60 > nohup-lastfundingrate-coin.out 2>&1 &
#nohup /warehouse/GitRepos/biannce-api/binance/bin/python -m binance_toolkit --config config.json ws-mark-price-usdt --write-kafka --sample-interval 60 > nohup-lastfundingrate-usdt.out 2>&1 &
#
nohup /warehouse/GitRepos/biannce-api/binance/bin/python \
	-m binance_toolkit \
	--config config.json \
	ws-kline-usdt \
	--symbol SNDKUSDT,SOLUSDT,NVDAUSDT \
	--write-kafka \
	--interval 1m > nohup-usdt-kline-1m.out 2>&1 &

nohup /warehouse/GitRepos/biannce-api/binance/bin/python \
	-m binance_toolkit \
	--config config.json \
	ws-mark-price-usdt \
	--symbol SNDKUSDT,SOLUSDT,NVDAUSDT\
	--write-kafka \
	--sample-interval 60 \
	--speed 3s > nohup-usdt-mark-price-1m.out 2>&1 &

