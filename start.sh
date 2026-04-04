#!/bin/bash

#nohup /warehouse/GitRepos/biannce-api/binance/bin/python -m binance_toolkit --config config.json collect > nohup.out 2>&1 &
nohup /warehouse/GitRepos/biannce-api/binance/bin/python -m binance_toolkit --config config.json collect-mark > nohup.out 2>&1 &
