# bot.py - Complete with Trading Hours + Pause/Resume + Force Start/Stop

from flask import Flask, jsonify, render_template, request
from utbot_logic import get_utbot_signal, fetch_btc_data, calc_utbot
from demo_trader import (
    update_demo_trade, 
    get_trade_history,
    get_order_log,
    load_trades,
    calculate_live_pl,
    force_close_position
)
from risk_manager import get_risk_status, load_risk_config, save_risk_config
from cloud_backup import cloud_save, cloud_load  # ✅ ADDED
import pandas as pd
from datetime import datetime
import json
import os

app = Flask(__name__)

# Global trading state file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADING_STATE_FILE = os.path.join(SCRIPT_DIR, "trading_state.json")

# Default trading hours
DEFAULT_TRADING_HOURS = {
    "enabled": True,
    "start_hour": 18,
    "end_hour": 23,
    "manual_pause": False,
    "force_start": False
}

def load_trading_state():
    """Load trading state (pause/resume, hours, force start)"""

    # 1️⃣ Try cloud first (Render redeploy safe)
    cloud_state = cloud_load()
    if cloud_state:
        save_trading_state(cloud_state)
        return cloud_state

    # 2️⃣ Fallback to local file
    if not os.path.exists(TRADING_STATE_FILE):
        save_trading_state(DEFAULT_TRADING_HOURS)
        return DEFAULT_TRADING_HOURS

    with open(TRADING_STATE_FILE, "r") as f:
        return json.load(f)

def save_trading_state(state):
    """Save trading state"""
    with open(TRADING_STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

    # 🔁 Backup to cloud
    cloud_save(state)

def is_within_trading_hours():
    state = load_trading_state()

    if state.get("force_start", False):
        return True

    if not state.get("enabled", True):
        return True

    current_hour = datetime.now().hour
    start_hour = state.get("start_hour", 18)
    end_hour = state.get("end_hour", 23)

    return start_hour <= current_hour < end_hour

def is_trading_allowed():
    state = load_trading_state()

    if state.get("force_start", False):
        return True, None

    if state.get("manual_pause", False):
        return False, "Trading manually paused"

    if not is_within_trading_hours():
        return False, "Outside trading hours"

    return True, None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signal', methods=['GET'])
def signal():
    try:
        allowed, reason = is_trading_allowed()
        signal_data = get_utbot_signal()

        signal_generated = signal_data.get("signal", "Hold")
        price = signal_data.get("price", 0)
        atr = signal_data.get("atr", 0)
        utbot_stop = signal_data.get("utbot_stop", price)

        if not allowed:
            all_data = load_trades()
            current_open_trade = all_data.get("open_trade")
            live_pl = calculate_live_pl(current_open_trade, price)

            return jsonify({
                "signal": "Hold",
                "price": price,
                "action": reason,
                "live_pl_inr": live_pl,
                "force_start": load_trading_state().get("force_start", False)
            })

        general_status, last_closed_trade, latest_log_entry = update_demo_trade(
            signal_generated, price, atr, utbot_stop
        )

        all_data = load_trades()
        current_open_trade = all_data.get("open_trade")
        live_pl = calculate_live_pl(current_open_trade, price)

        return jsonify({
            "price": price,
            "signal": signal_generated,
            "balance": general_status["balance"],
            "holding": general_status["holding"],
            "position_type": general_status["position_type"],
            "action": general_status["action"],
            "last_closed_trade": last_closed_trade,
            "latest_order": latest_log_entry,
            "live_pl_inr": live_pl,
            "stop_loss": general_status.get("stop_loss"),
            "tp_levels": general_status.get("tp_levels", []),
            "force_start": load_trading_state().get("force_start", False)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/trading-control', methods=['GET', 'POST'])
def trading_control():
    if request.method == 'GET':
        state = load_trading_state()
        allowed, reason = is_trading_allowed()
        return jsonify({
            "state": state,
            "trading_allowed": allowed,
            "pause_reason": reason
        })

    elif request.method == 'POST':
        state = load_trading_state()
        action = request.json.get("action")

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

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
