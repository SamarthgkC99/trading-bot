import requests
import json
import os

UPSTASH_URL = os.environ.get("UPSTASH_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {UPSTASH_TOKEN}"
}

KEY = "TRADING_STATE"

def cloud_load():
    try:
        r = requests.get(f"{UPSTASH_URL}/get/{KEY}", headers=HEADERS, timeout=5)
        data = r.json().get("result")
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None

def cloud_save(state):
    try:
        value = json.dumps(state)
        requests.post(
            f"{UPSTASH_URL}/set/{KEY}",
            headers=HEADERS,
            data=value,
            timeout=5
        )
    except Exception:
        pass
