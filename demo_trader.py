# demo_trader.py - Complete with Risk Management + GitHub Storage

import json
import os
from datetime import datetime
from risk_manager import (
    load_risk_config,
    calculate_position_size,
    calculate_stop_loss,
    calculate_take_profit_levels,
    update_trailing_stop,
    can_open_trade,
    record_trade_result,
    move_stop_to_breakeven,
    get_risk_status
)

# ====== NEW IMPORT ======
from github_storage import GitHubStorage
# =========================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(SCRIPT_DIR, "demo_trades.json")

START_BALANCE = 10000
COINS_PER_TRADE = 0.001
BTC_USDT_RATE = 85

# ====== MODIFIED FUNCTION ======
def load_trades():
    """Load trading data from GitHub, with local file fallback."""
    print(f"--- Attempting to load demo_trades.json from GitHub ---")
    try:
        storage = GitHubStorage()
        data = storage.read_file("demo_trades.json")
        if data:
            print("--- Trade data loaded from GitHub successfully. ---")
            return data
    except Exception as e:
        print(f"Could not load trades from GitHub: {e}. Falling back to local file.")

    # Fallback to local file
    print(f"--- Loading trade data from local file: {TRADES_FILE} ---")
    if not os.path.exists(TRADES_FILE):
        print("--- Local trade file not found. Creating new data structure. ---")
        return {
            "balance": START_BALANCE, 
            "open_trade": None, 
            "history": [], 
            "order_log": [],
            "last_signal": None 
        }
    with open(TRADES_FILE, "r") as f:
        data = json.load(f)
        print("--- Trade data loaded from local file. ---")
        return data

# ====== MODIFIED FUNCTION ======
def save_trades(data):
    """Save trading data to GitHub and local file."""
    print(f"--- Saving trade data ---")
    # Save to GitHub
    try:
        storage = GitHubStorage()
        if storage.write_file("demo_trades.json", data):
            print("--- Trade data saved to GitHub successfully. ---")
        else:
            print("--- Failed to save trade data to GitHub. ---")
    except Exception as e:
        print(f"Error saving trades to GitHub: {e}")

    # Always save to local file as a backup within the same deployment
    with open(TRADES_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print("--- Trade data saved to local file. ---")

def check_tp_sl_hits(open_trade, current_price):
    """Check if any TP or SL levels are hit"""
    if not open_trade:
        return (None, None)
    
    position_type = open_trade["type"]
    stop_loss = open_trade.get("stop_loss")
    tp_levels = open_trade.get("tp_levels", [])
    
    if stop_loss:
        if position_type == "LONG" and current_price <= stop_loss:
            return ("SL", {"price": stop_loss, "reason": "Stop-Loss Hit"})
        elif position_type == "SHORT" and current_price >= stop_loss:
            return ("SL", {"price": stop_loss, "reason": "Stop-Loss Hit"})
    
    for i, tp in enumerate(tp_levels):
        if tp["hit"]:
            continue
        
        if position_type == "LONG" and current_price >= tp["price"]:
            return (tp["name"], {"price": tp["price"], "percentage": tp["percentage"], "index": i})
        elif position_type == "SHORT" and current_price <= tp["price"]:
            return (tp["name"], {"price": tp["price"], "percentage": tp["percentage"], "index": i})
    
    return (None, None)

def partial_close_position(data, open_trade, current_price, tp_details):
    """Close partial position when TP hit"""
    percentage_to_close = tp_details["percentage"]
    tp_index = tp_details["index"]
    
    entry_price = open_trade["entry_price"]
    original_amount = open_trade["original_amount"]
    amount_to_close = original_amount * (percentage_to_close / 100)
    
    if open_trade["type"] == "LONG":
        profit_usdt = (current_price - entry_price) * amount_to_close
    else:
        profit_usdt = (entry_price - current_price) * amount_to_close
    
    profit_inr = profit_usdt * BTC_USDT_RATE
    
    data["balance"] += profit_inr
    open_trade["tp_levels"][tp_index]["hit"] = True
    open_trade["amount"] -= amount_to_close
    
    partial_record = {
        "type": open_trade["type"],
        "entry_price": entry_price,
        "exit_price": current_price,
        "amount_closed": round(amount_to_close, 6),
        "profit_usdt": round(profit_usdt, 2),
        "profit_inr": round(profit_inr, 2),
        "tp_level": tp_details["price"],
        "tp_name": f"TP{tp_index + 1}",
        "closed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "partial": True
    }
    
    data["history"].append(partial_record)
    
    if tp_index == 0 and open_trade["stop_loss"]:
        be_stop = move_stop_to_breakeven(entry_price, open_trade["type"])
        open_trade["stop_loss"] = be_stop
        open_trade["breakeven_moved"] = True
    
    record_trade_result(profit_inr)
    
    return partial_record

def close_full_position(data, open_trade, current_price, reason):
    """Close entire position"""
    entry_price = open_trade["entry_price"]
    amount = open_trade["amount"]
    
    if open_trade["type"] == "LONG":
        profit_usdt = (current_price - entry_price) * amount
    else:
        profit_usdt = (entry_price - current_price) * amount
    
    profit_inr = profit_usdt * BTC_USDT_RATE
    balance_before = data["balance"]
    data["balance"] += profit_inr
    
    trade_record = {
        "type": open_trade["type"],
        "entry_price": entry_price,
        "exit_price": current_price,
        "amount": amount,
        "profit_usdt": round(profit_usdt, 2),
        "profit_inr": round(profit_inr, 2),
        "balance_before": round(balance_before, 2),
        "balance_after": round(data["balance"], 2),
        "closed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exit_reason": reason,
        "tp_levels_hit": [tp["name"] for tp in open_trade.get("tp_levels", []) if tp["hit"]],
        "partial": False
    }
    
    data["history"].append(trade_record)
    record_trade_result(profit_inr)
    data["open_trade"] = None
    
    return trade_record

def update_demo_trade(signal, price, atr_value, utbot_stop):
    """Update trading state with risk management"""
    signal = signal.capitalize()
    data = load_trades()
    config = load_risk_config()
    open_trade = data.get("open_trade")
    
    action_message = ""
    last_closed_trade = None
    
    log_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "side": signal,
        "price": price,
        "quantity": COINS_PER_TRADE
    }
    
    if open_trade:
        hit_type, details = check_tp_sl_hits(open_trade, price)
        
        if hit_type == "SL":
            last_closed_trade = close_full_position(data, open_trade, price, "Stop-Loss Hit")
            action_message = f"🛑 STOP-LOSS HIT @ ${price:.2f} | P/L: ₹{last_closed_trade['profit_inr']:.2f}"
            log_entry["action"] = "STOP_LOSS"
            log_entry["pl_inr"] = last_closed_trade['profit_inr']
            open_trade = None
            
        elif hit_type and hit_type.startswith("TP"):
            partial_record = partial_close_position(data, open_trade, price, details)
            action_message = f"✅ {hit_type} HIT @ ${price:.2f} | Closed {details['percentage']}% | P/L: ₹{partial_record['profit_inr']:.2f}"
            
            remaining_tps = [tp for tp in open_trade["tp_levels"] if not tp["hit"]]
            if not remaining_tps:
                remaining_close = close_full_position(data, open_trade, price, "All TPs Hit")
                action_message += f" | Closed remaining"
                open_trade = None
            
            log_entry["action"] = f"{hit_type}_HIT"
            log_entry["pl_inr"] = partial_record['profit_inr']
        
        else:
            if open_trade and open_trade.get("breakeven_moved") and config["stop_loss"]["trailing_enabled"]:
                new_stop = update_trailing_stop(
                    price, 
                    open_trade["type"], 
                    open_trade["stop_loss"], 
                    atr_value, 
                    config
                )
                if new_stop:
                    open_trade["stop_loss"] = new_stop
                    action_message = f"📈 Trailing stop updated to ${new_stop:.2f}"
                    log_entry["action"] = "TRAILING_STOP_UPDATE"
    
    if signal == "Hold":
        if not action_message:
            action_message = "Holding position. Waiting for next signal."
            log_entry["action"] = "HOLD"
    
    elif signal == "Buy":
        trade_check = can_open_trade(data["balance"])
        
        if not trade_check["allowed"]:
            action_message = f"⚠️ Cannot open BUY: {trade_check['reason']}"
            log_entry["action"] = "BLOCKED"
        
        elif open_trade and open_trade["type"] == "LONG":
            action_message = "Ignoring repeated 'Buy' signal. Already in LONG position."
            log_entry["action"] = "IGNORED"
        
        else:
            if open_trade and open_trade["type"] == "SHORT":
                last_closed_trade = close_full_position(data, open_trade, price, "Opposite Signal")
                action_message = f"CLOSED SHORT @ ${price:.2f}, P/L: ₹{last_closed_trade['profit_inr']:.2f}. | "
                log_entry["action"] = "CLOSE_SHORT"
                open_trade = None
            
            position_size = calculate_position_size(data["balance"], config)
            stop_loss_price = calculate_stop_loss(price, "LONG", atr_value, utbot_stop, config)
            tp_levels = calculate_take_profit_levels(price, "LONG", atr_value, config)
            
            open_trade = {
                "type": "LONG",
                "entry_price": price,
                "amount": position_size,
                "original_amount": position_size,
                "stop_loss": stop_loss_price,
                "tp_levels": tp_levels,
                "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy": "UT Bot #2 (KV=2, ATR=300)",
                "atr_at_entry": atr_value,
                "breakeven_moved": False
            }
            
            action_message += f"🟢 OPENED LONG @ ${price:.2f} | Size: {position_size} BTC | SL: ${stop_loss_price:.2f}"
            log_entry["action"] = "OPEN_LONG"
            log_entry["stop_loss"] = stop_loss_price
            log_entry["take_profits"] = [tp["price"] for tp in tp_levels]
            data["last_signal"] = "Buy"
    
    elif signal == "Sell":
        trade_check = can_open_trade(data["balance"])
        
        if not trade_check["allowed"]:
            action_message = f"⚠️ Cannot open SELL: {trade_check['reason']}"
            log_entry["action"] = "BLOCKED"
        
        elif open_trade and open_trade["type"] == "SHORT":
            action_message = "Ignoring repeated 'Sell' signal. Already in SHORT position."
            log_entry["action"] = "IGNORED"
        
        else:
            if open_trade and open_trade["type"] == "LONG":
                last_closed_trade = close_full_position(data, open_trade, price, "Opposite Signal")
                action_message = f"CLOSED LONG @ ${price:.2f}, P/L: ₹{last_closed_trade['profit_inr']:.2f}. | "
                log_entry["action"] = "CLOSE_LONG"
                open_trade = None
            
            position_size = calculate_position_size(data["balance"], config)
            stop_loss_price = calculate_stop_loss(price, "SHORT", atr_value, utbot_stop, config)
            tp_levels = calculate_take_profit_levels(price, "SHORT", atr_value, config)
            
            open_trade = {
                "type": "SHORT",
                "entry_price": price,
                "amount": position_size,
                "original_amount": position_size,
                "stop_loss": stop_loss_price,
                "tp_levels": tp_levels,
                "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy": "UT Bot #1 (KV=2, ATR=1)",
                "atr_at_entry": atr_value,
                "breakeven_moved": False
            }
            
            action_message += f"🔴 OPENED SHORT @ ${price:.2f} | Size: {position_size} BTC | SL: ${stop_loss_price:.2f}"
            log_entry["action"] = "OPEN_SHORT"
            log_entry["stop_loss"] = stop_loss_price
            log_entry["take_profits"] = [tp["price"] for tp in tp_levels]
            data["last_signal"] = "Sell"
    
    data.setdefault("order_log", []).append(log_entry)
    data["open_trade"] = open_trade
    save_trades(data)
    
    general_status = {
        "balance": round(data["balance"], 2),
        "holding": data["open_trade"] is not None,
        "position_type": data["open_trade"]["type"] if data["open_trade"] else None,
        "action": action_message,
        "stop_loss": data["open_trade"]["stop_loss"] if data["open_trade"] else None,
        "tp_levels": data["open_trade"]["tp_levels"] if data["open_trade"] else [],
        "position_size": data["open_trade"]["amount"] if data["open_trade"] else 0
    }
    
    return general_status, last_closed_trade, log_entry

def get_trade_history():
    """Retrieve complete trade history"""
    data = load_trades()
    return data.get("history", [])

def get_order_log():
    """Retrieve order log"""
    data = load_trades()
    return data.get("order_log", [])

def calculate_live_pl(open_trade, current_price):
    """Calculate live profit/loss for open position"""
    if not open_trade:
        return None
    
    entry_price = open_trade["entry_price"]
    amount = open_trade["amount"]
    trade_type = open_trade["type"]
    
    if trade_type == "LONG":
        profit_usdt = (current_price - entry_price) * amount
    elif trade_type == "SHORT":
        profit_usdt = (entry_price - current_price) * amount
    else:
        return None
    
    profit_inr = profit_usdt * BTC_USDT_RATE
    return round(profit_inr, 2)

def get_performance_summary():
    """Calculate trading performance statistics"""
    data = load_trades()
    history = data.get("history", [])
    
    if not history:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_profit_inr": 0,
            "win_rate": 0
        }
    
    total_trades = len(history)
    winning_trades = sum(1 for trade in history if trade["profit_inr"] > 0)
    losing_trades = sum(1 for trade in history if trade["profit_inr"] < 0)
    total_profit_inr = sum(trade["profit_inr"] for trade in history)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "total_profit_inr": round(total_profit_inr, 2),
        "win_rate": round(win_rate, 2),
        "current_balance": round(data["balance"], 2),
        "starting_balance": START_BALANCE,
        "total_return": round(data["balance"] - START_BALANCE, 2)
    }
