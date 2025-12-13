import requests
import json
import os

URL = os.environ["UPSTASH_URL"]
TOKEN = os.environ["UPSTASH_TOKEN"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}"
}

KEY = "BOT_STATE"

def load_state():
    r = requests.get(f"{URL}/get/{KEY}", headers=HEADERS)
    data = r.json()
    if data["result"]:
        return json.loads(data["result"])
    return {
        "trades": [],
        "last_signal": None
    }

def save_state(state):
    value = json.dumps(state)
    requests.post(f"{URL}/set/{KEY}", headers=HEADERS, data=value)
