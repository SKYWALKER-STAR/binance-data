#!/bin/bash

nohup /warehouse/GitRepos/biannce-api/biannce/bin/python -m binance_toolkit --config config.json collect > nohup.out 2>&1 &
