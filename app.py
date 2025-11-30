# bot.py - Complete with Trading Hours + Pause/Resume + GitHub Storage

from flask import Flask, jsonify, render_template, request
from utbot_logic import get_utbot_signal, fetch_btc_data, calc_utbot
from demo_trader import (
    update_demo_trade, 
    get_trade_history,
    get_order_log,
    load_trades,
    calculate_live_pl
)
from risk_manager import get_risk_status, load_risk_config, save_risk_config
import pandas as pd
from datetime import datetime
import json
import os

# ====== NEW IMPORT ======
from github_storage import GitHubStorage
# =========================

app = Flask(__name__)

# Global trading state file (used as a local fallback)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADING_STATE_FILE = os.path.join(SCRIPT_DIR, "trading_state.json")

# Default trading hours: 6 PM (18:00) to 11 PM (23:00)
DEFAULT_TRADING_HOURS = {
    "enabled": True,
    "start_hour": 18,
    "end_hour": 23,
    "manual_pause": False
}

# ====== MODIFIED FUNCTION ======
def load_trading_state():
    """Load trading state from GitHub, with local file fallback."""
    print("--- Attempting to load trading_state.json from GitHub ---")
    try:
        storage = GitHubStorage()
        state = storage.read_file("trading_state.json")
        if state:
            print("--- Trading state loaded from GitHub successfully. ---")
            return state
    except Exception as e:
        print(f"Could not load trading_state from GitHub: {e}. Falling back to local file.")

    # Fallback to local file
    print(f"--- Loading trading state from local file: {TRADING_STATE_FILE} ---")
    if not os.path.exists(TRADING_STATE_FILE):
        print("--- Local trading state file not found. Creating new default state. ---")
        save_trading_state(DEFAULT_TRADING_HOURS) # This will save locally
        return DEFAULT_TRADING_HOURS
    
    with open(TRADING_STATE_FILE, "r") as f:
        return json.load(f)

# ====== MODIFIED FUNCTION ======
def save_trading_state(state):
    """Save trading state to GitHub and local file."""
    print("--- Saving trading state ---")
    # Save to GitHub
    try:
        storage = GitHubStorage()
        if storage.write_file("trading_state.json", state):
            print("--- Trading state saved to GitHub successfully. ---")
        else:
            print("--- Failed to save trading state to GitHub. ---")
    except Exception as e:
        print(f"Error saving trading_state to GitHub: {e}")

    # Always save to local file as a backup within the same deployment
    with open(TRADING_STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)
    print("--- Trading state saved to local file. ---")

def is_within_trading_hours():
    """Check if current time is within allowed trading hours"""
    state = load_trading_state()
    
    if not state.get("enabled", True):
        return True
    
    current_hour = datetime.now().hour
    start_hour = state.get("start_hour", 18)
    end_hour = state.get("end_hour", 23)
    
    return start_hour <= current_hour < end_hour

def is_trading_allowed():
    """Check if trading is allowed (hours + manual pause)"""
    state = load_trading_state()
    
    if state.get("manual_pause", False):
        return False, "Trading manually paused"
    
    if not is_within_trading_hours():
        current_hour = datetime.now().hour
        start_hour = state.get("start_hour", 18)
        end_hour = state.get("end_hour", 23)
        return False, f"Outside trading hours ({start_hour}:00 - {end_hour}:00). Current: {current_hour}:00"
    
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

        if signal_generated == "No Data" or price == 0:
            return jsonify({"error": "Could not generate signal"}), 500

        if not allowed:
            all_data = load_trades()
            current_open_trade = all_data.get("open_trade")
            live_pl_inr = calculate_live_pl(current_open_trade, price)
            
            risk_status = get_risk_status()
            
            response_data = {
                "price": price,
                "signal": "Hold",
                "balance": all_data["balance"],
                "holding": current_open_trade is not None,
                "position_type": current_open_trade["type"] if current_open_trade else None,
                "action": f"⏸️ PAUSED: {reason}",
                "last_closed_trade": None,
                "latest_order": None,
                "live_pl_inr": live_pl_inr,
                "stop_loss": current_open_trade["stop_loss"] if current_open_trade else None,
                "tp_levels": current_open_trade.get("tp_levels", []) if current_open_trade else [],
                "position_size": current_open_trade["amount"] if current_open_trade else 0,
                "atr": atr,
                "risk_status": risk_status,
                "trading_allowed": False,
                "pause_reason": reason,
                "strategy_info": {
                    "buy_strategy": "UT Bot #2 (KV=2, ATR=300)",
                    "sell_strategy": "UT Bot #1 (KV=2, ATR=1)"
                }
            }
            
            return jsonify(response_data)

        general_status, last_closed_trade, latest_log_entry = update_demo_trade(
            signal_generated, price, atr, utbot_stop
        )
        
        all_data = load_trades()
        current_open_trade = all_data.get("open_trade")
        live_pl_inr = calculate_live_pl(current_open_trade, price)
        
        risk_status = get_risk_status()
        
        response_data = {
            "price": price,
            "signal": signal_generated,
            "balance": general_status["balance"],
            "holding": general_status["holding"],
            "position_type": general_status["position_type"],
            "action": general_status["action"],
            "last_closed_trade": last_closed_trade,
            "latest_order": latest_log_entry,
            "live_pl_inr": live_pl_inr,
            "stop_loss": general_status.get("stop_loss"),
            "tp_levels": general_status.get("tp_levels", []),
            "position_size": general_status.get("position_size", 0),
            "atr": atr,
            "risk_status": risk_status,
            "trading_allowed": True,
            "pause_reason": None,
            "strategy_info": {
                "buy_strategy": "UT Bot #2 (KV=2, ATR=300)",
                "sell_strategy": "UT Bot #1 (KV=2, ATR=1)"
            }
        }

        return jsonify(response_data)

    except Exception as e:
        print(f"An error occurred in /signal route: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/chart-data', methods=['GET'])
def chart_data():
    """Returns candlestick data with UT Bot indicators"""
    try:
        df = fetch_btc_data()
        if df.empty:
            return jsonify({"error": "No data"}), 500

        df1 = calc_utbot(df.copy(), 2, 1)
        
        candles = []
        for idx, row in df.iterrows():
            candles.append({
                "time": int(row['time']) // 1000,
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
            })
        
        stop_line = []
        for idx, row in df1.iterrows():
            stop_line.append({
                "time": int(row['time']) // 1000,
                "value": float(row['stop'])
            })
        
        atr_line = []
        for idx, row in df1.iterrows():
            if pd.notna(row['atr']):
                atr_line.append({
                    "time": int(row['time']) // 1000,
                    "value": float(row['close']) - float(row['atr'])
                })
        
        return jsonify({
            "candles": candles,
            "stop_line": stop_line,
            "atr_line": atr_line
        })

    except Exception as e:
        print(f"Error in /chart-data route: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/history', methods=['GET'])
def history():
    """Returns complete trade history"""
    trade_history = get_trade_history()
    return jsonify(trade_history)

@app.route('/orders', methods=['GET'])
def orders():
    """Returns order log in reverse chronological order"""
    order_log = get_order_log()
    return jsonify(list(reversed(order_log)))

@app.route('/status', methods=['GET'])
def status():
    """Returns current trading status"""
    try:
        data = load_trades()
        current_open_trade = data.get("open_trade")
        
        from utbot_logic import get_current_price
        current_price = get_current_price()
        
        if current_price:
            live_pl_inr = calculate_live_pl(current_open_trade, current_price)
        else:
            live_pl_inr = None
        
        risk_status = get_risk_status()
        
        status_data = {
            "balance": round(data["balance"], 2),
            "has_open_trade": current_open_trade is not None,
            "open_trade": current_open_trade,
            "current_price": current_price,
            "live_pl_inr": live_pl_inr,
            "last_signal": data.get("last_signal"),
            "total_trades": len(data.get("history", [])),
            "risk_status": risk_status
        }
        
        return jsonify(status_data)
    
    except Exception as e:
        print(f"Error in /status route: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/risk-config', methods=['GET', 'POST'])
def risk_config():
    """Get or update risk management configuration"""
    if request.method == 'GET':
        config = load_risk_config()
        return jsonify(config)
    
    elif request.method == 'POST':
        try:
            new_config = request.json
            save_risk_config(new_config)
            return jsonify({"success": True, "message": "Risk configuration updated"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

@app.route('/risk-status', methods=['GET'])
def risk_status_endpoint():
    """Get current risk management status"""
    try:
        status = get_risk_status()
        return jsonify(status)
    except Exception as e:
        print(f"Error in /risk-status route: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/trading-control', methods=['GET', 'POST'])
def trading_control():
    """Get or update trading control (pause/resume, hours)"""
    if request.method == 'GET':
        state = load_trading_state()
        allowed, reason = is_trading_allowed()
        
        return jsonify({
            "state": state,
            "trading_allowed": allowed,
            "pause_reason": reason,
            "current_time": datetime.now().strftime("%H:%M:%S")
        })
    
    elif request.method == 'POST':
        try:
            action = request.json.get("action")
            
            if action == "pause":
                state = load_trading_state()
                state["manual_pause"] = True
                save_trading_state(state)
                return jsonify({"success": True, "message": "Trading paused manually"})
            
            elif action == "resume":
                state = load_trading_state()
                state["manual_pause"] = False
                save_trading_state(state)
                return jsonify({"success": True, "message": "Trading resumed"})
            
            elif action == "update_hours":
                state = load_trading_state()
                state["start_hour"] = request.json.get("start_hour", 18)
                state["end_hour"] = request.json.get("end_hour", 23)
                state["enabled"] = request.json.get("enabled", True)
                save_trading_state(state)
                return jsonify({"success": True, "message": "Trading hours updated"})
            
            else:
                return jsonify({"success": False, "error": "Invalid action"}), 400
                
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 UT Bot Trading System with Risk Management Started")
    print("="*60)
    print("📊 Dashboard: http://localhost:5000")
    print("📈 Chart Data: /chart-data")
    print("⚙️  Risk Config: /risk-config")
    print("📉 Risk Status: /risk-status")
    print("⏯️  Trading Control: /trading-control")
    print("="*60)
    
    state = load_trading_state()
    if state.get("enabled", True):
        print(f"⏰ Trading Hours: {state.get('start_hour', 18)}:00 - {state.get('end_hour', 23)}:00")
    else:
        print("⏰ Trading Hours: Disabled (24/7 trading)")
    
    if state.get("manual_pause", False):
        print("⏸️  Status: PAUSED")
    else:
        print("▶️  Status: ACTIVE")
    
    print("="*60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
