from __future__ import annotations

import argparse
import base64
import requests
import time
import urllib.parse
from cryptography.hazmat.primitives.serialization import load_pem_private_key

API_KEY='8xAzqpGSMG2V3MJlaPrHY6LcZmCFsD1hNnOnyNHVhNktnYolOfQAT1NpGQ8g9JK7'
PRIVATE_KEY_PATH='/warehouse/GitRepos/biannce-api/biannce-ed25519-pri.pem'
BASE_URL='https://api.binance.com'

def _ping_server():
    response = requests.get(
      'https://api.binance.com/api/v3/ping',
    )
    print(response.json())

def _exchange_info():
    params = {
      'symbol': 'BNBBTC',
    }
    response = requests.get(
      'https://api.binance.com/api/v3/exchangeInfo',
      params=params
    )
    print(response.json())

def _klines_info():
    params = {
      'symbol': 'BNBBTC',
      'interval': '1s'
    }
    response = requests.get(
      'https://api.binance.com/api/v3/klines',
      params=params
    )
    print(response.json())

def _latest_price():
    params = {
      'symbol': 'BTCUSDT',
    }
    response = requests.get(
      'https://api.binance.com/api/v3/ticker/price',
      params=params
    )
    print(response.json())

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Biannce general api")
    parser.add_argument(
        "--api-func",
        default=None,
        choices=["ping", "exinfo", "klines", "price"],
        help="write into a specific measurement (table-style): ping|exinfo",
    )
    return parser.parse_args()

def main():
    args = _parse_args()
    if args.api_func == "ping":
        _ping_server()
        return
    elif args.api_func == "exinfo":
        _exchange_info()
        return
    elif args.api_func == "klines":
        _klines_info()
        return
    elif args.api_func == "price":
        _latest_price()
        return

if __name__ == '__main__':
    main()

