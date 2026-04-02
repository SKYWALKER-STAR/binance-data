#!/usr/bin/env python3

import base64
import requests
import time
import urllib.parse
from cryptography.hazmat.primitives.serialization import load_pem_private_key

# 设置身份验证：
API_KEY='8xAzqpGSMG2V3MJlaPrHY6LcZmCFsD1hNnOnyNHVhNktnYolOfQAT1NpGQ8g9JK7'
PRIVATE_KEY_PATH='/warehouse/GitRepos/biannce-api/biannce-ed25519-pri.pem'
#private_key='4fSXwsg0q4UCCqG1TSHsxaGhLpiGEshN0RX0PuEuvIydaw1E6H0l1TJpwm1hfYub'

# 加载 private key。
# 在这个例子中，private key 没有加密，但我们建议使用强密码以提高安全性。
with open(PRIVATE_KEY_PATH, 'rb') as f:
    private_key = load_pem_private_key(data=f.read(), password=bytes('l44I4cZYp*$pCn64',encoding='utf-8'))

# 设置请求参数：
params = {
    'symbol':       'BTCUSDT',
    'side':         'SELL',
    'type':         'LIMIT',
    'timeInForce':  'GTC',
    'quantity':     '1.0000000',
    'price':        '0.20',
}

# 参数中加时间戳：
timestamp = int(time.time() * 1000) # 以毫秒为单位的 UNIX 时间戳
params['timestamp'] = timestamp

# 参数中加签名：
payload = urllib.parse.urlencode(params, encoding='UTF-8')
signature = base64.b64encode(private_key.sign(payload.encode('ASCII')))
params['signature'] = signature

# 发送请求：
headers = {
    'X-MBX-APIKEY': API_KEY,
}
response = requests.post(
    'https://api.binance.com/api/v3/order',
    headers=headers,
    data=params,
)
print(response.json())
