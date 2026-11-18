"""Envía un paquete de ejemplo a tu bot.  Uso:
    python send_example.py example_long_entry.json https://TU-APP.up.railway.app TU_SECRET
    python send_example.py example_long_entry.json http://localhost:8000 TU_SECRET
"""
import json
import sys

import httpx

path, base, secret = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
body = open(path, encoding="utf-8").read()
r = httpx.post(f"{base}/webhook", params={"secret": secret}, content=body, headers={"Content-Type": "text/plain"}, timeout=15)
print(r.status_code, r.text)
