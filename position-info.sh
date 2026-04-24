#!/bin/bash
source /etc/profile
proxy_on
cd /warehouse/GitRepos/biannce-api/ && nohup /warehouse/GitRepos/biannce-api/binance/bin/python -m binance_toolkit --config config.json futures-positions --write-clickhouse > /warehouse/GitRepos/biannce-api/nohup-futures-positions.out 2>&1 &
