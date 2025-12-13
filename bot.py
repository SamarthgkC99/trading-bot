# bot.py - Complete with Trading Hours + Pause/Resume + Force Start/Stop

from flask import Flask, jsonify, render_template, request
from utbot_logic import get_utbot_signal
from demo_trader import (
    update_demo_trade,
    get_trade_history,
    get_order_log,
    load_trades,
    calculate_live_pl
)
from risk_manager import load_risk_config, save_risk_config
from cloud_backup import cloud_save, cloud_load
from datetime import datetime
import json
import os

app = Flask(__name__)

# -------------------------------
# Trading state file (local + cloud)
# -------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADING_STATE_FILE = os.path.join(SCRIPT_DIR, "trading_state.json")

DEFAULT_TRADING_HOURS = {
    "enabled": True,
    "start_hour": 18,
    "end_hour": 23,
    "manual_pause": False,
    "force_start": False
}

def load_trading_state():
    cloud_state = cloud_load()
    if cloud_state:
        save_trading_state(cloud_state)
        return cloud_state

    if not os.path.exists(TRADING_STATE_FILE):
        save_trading_state(DEFAULT_TRADING_HOURS)
        return DEFAULT_TRADING_HOURS

    with open(TRADING_STATE_FILE, "r") as f:
        return json.load(f)

def save_trading_state(state):
    with open(TRADING_STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)
    cloud_save(state)

def is_within_trading_hours():
    state = load_trading_state()

    if state.get("force_start"):
        return True

    if not state.get("enabled", True):
        return True

    now = datetime.now().hour
    return state["start_hour"] <= now < state["end_hour"]

def is_trading_allowed():
    state = load_trading_state()

    if state.get("force_start"):
        return True, None

    if state.get("manual_pause"):
        return False, "Trading manually paused"

    if not is_within_trading_hours():
        return False, "Outside trading hours"

    return True, None

# -------------------------------
# Routes
# -------------------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/signal", methods=["GET"])
def signal():
    try:
        allowed, reason = is_trading_allowed()
        signal_data = get_utbot_signal()

        price = signal_data.get("price", 0)
        signal_value = signal_data.get("signal", "Hold")
        atr = signal_data.get("atr", 0)
        utbot_stop = signal_data.get("utbot_stop", price)

        if not allowed:
            all_data = load_trades()
            open_trade = all_data.get("open_trade")
            live_pl = calculate_live_pl(open_trade, price)

            return jsonify({
                "signal": "Hold",
                "price": price,
                "action": reason,
                "live_pl_inr": live_pl,
                "force_start": load_trading_state().get("force_start", False)
            })

        general_status, last_closed, latest_order = update_demo_trade(
            signal_value, price, atr, utbot_stop
        )

        all_data = load_trades()
        open_trade = all_data.get("open_trade")
        live_pl = calculate_live_pl(open_trade, price)

        return jsonify({
            "price": price,
            "signal": signal_value,
            "balance": general_status["balance"],
            "holding": general_status["holding"],
            "position_type": general_status["position_type"],
            "action": general_status["action"],
            "last_closed_trade": last_closed,
            "latest_order": latest_order,
            "live_pl_inr": live_pl,
            "stop_loss": general_status.get("stop_loss"),
            "tp_levels": general_status.get("tp_levels", []),
            "force_start": load_trading_state().get("force_start", False)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------------
# ✅ REQUIRED ROUTE (FIXES 404)
# -------------------------------
@app.route("/chart-data", methods=["GET"])
def chart_data():
    data = load_trades()
    return jsonify({
        "trades": data.get("trades", []),
        "open_trade": data.get("open_trade"),
        "last_signal": data.get("last_signal")
    })

# -------------------------------
# ✅ REQUIRED ROUTE (FIXES 404)
# -------------------------------
@app.route("/history", methods=["GET"])
def history():
    return jsonify({
        "trade_history": get_trade_history(),
        "order_log": get_order_log()
    })

@app.route("/trading-control", methods=["GET", "POST"])
def trading_control():
    if request.method == "GET":
        state = load_trading_state()
        allowed, reason = is_trading_allowed()
        return jsonify({
            "state": state,
            "trading_allowed": allowed,
            "pause_reason": reason
        })

    action = request.json.get("action")
    state = load_trading_state()

    if action == "pause":
        state["manual_pause"] = True
        state["force_start"] = False
    elif action == "resume":
        state["manual_pause"] = False
        state["force_start"] = False
    elif action == "force_start":
        state["manual_pause"] = False
        state["force_start"] = True
    elif action == "force_stop":
        state["manual_pause"] = True
        state["force_start"] = False

    save_trading_state(state)
    return jsonify({"success": True})

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

# -------------------------------
# Render entry point
# -------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
