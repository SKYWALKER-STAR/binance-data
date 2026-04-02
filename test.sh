apiKey="hN0VASAeKrfvByaGFtppwoqgrsAgPMowGXfYESf0MxCtJYywaeiMkgmG4gbdAt30"
secretKey="4fSXwsg0q4UCCqG1TSHsxaGhLpiGEshN0RX0PuEuvIydaw1E6H0l1TJpwm1hfYub"

payload="symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1770540738"

# 对请求进行签名

signature=$(echo -n "$payload" | openssl dgst -sha256 -hmac "$secretKey")
signature=${signature#*= }    # Keep only the part after the "= "

# 发送请求

curl -H "X-MBX-APIKEY: $apiKey" -X POST "https://api.binance.com/api/v3/order?$payload&signature=$signature"

