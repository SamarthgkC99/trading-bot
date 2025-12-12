# demo_trader.py - ONLY TP1 with FULL EXIT + Force Close

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(SCRIPT_DIR, "demo_trades.json")

START_BALANCE = 10000
COINS_PER_TRADE = 0.001
BTC_USDT_RATE = 85

def load_trades():
    """Load trading data from JSON file"""
    print(f"--- Loading data from: {TRADES_FILE} ---")
    if not os.path.exists(TRADES_FILE):
        print("--- File not found. Creating new data structure. ---")
        return {
            "balance": START_BALANCE, 
            "open_trade": None, 
            "history": [], 
            "order_log": [],
            "last_signal": None 
        }
    with open(TRADES_FILE, "r") as f:
        data = json.load(f)
        print("--- Data loaded successfully. ---")
        return data

def save_trades(data):
    """Save trading data to JSON file"""
    print(f"--- Saving data to: {TRADES_FILE} ---")
    with open(TRADES_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print("--- Data saved successfully. ---")

def force_close_position(current_price, reason="Force Close"):
    """Force close any open position immediately"""
    data = load_trades()
    open_trade = data.get("open_trade")
    
    if not open_trade:
        return None
    
    # Close the position
    trade_record = close_full_position(data, open_trade, current_price, reason)
    
    # Add to order log
    log_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "side": "CLOSE",
        "action": "FORCE_CLOSE",
        "price": current_price,
        "quantity": open_trade["amount"],
        "pl_inr": trade_record['profit_inr']
    }
    
    data.setdefault("order_log", []).append(log_entry)
    save_trades(data)
    
    return trade_record

def check_tp_sl_hits(open_trade, current_price):
    """Check if TP1 or SL is hit - ONLY TP1, NO TP2/TP3"""
    if not open_trade:
        return (None, None)
    
    position_type = open_trade["type"]
    stop_loss = open_trade.get("stop_loss")
    tp1_price = open_trade.get("tp1_price")  # Single TP1 price
    
    # Check Stop-Loss
    if stop_loss:
        if position_type == "LONG" and current_price <= stop_loss:
            return ("SL", {"price": stop_loss, "reason": "Stop-Loss Hit"})
        elif position_type == "SHORT" and current_price >= stop_loss:
            return ("SL", {"price": stop_loss, "reason": "Stop-Loss Hit"})
    
    # Check ONLY TP1 - FULL EXIT
    if tp1_price:
        if position_type == "LONG" and current_price >= tp1_price:
            return ("TP1", {"price": tp1_price})
        elif position_type == "SHORT" and current_price <= tp1_price:
            return ("TP1", {"price": tp1_price})
    
    return (None, None)

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
        "partial": False
    }
    
    data["history"].append(trade_record)
    record_trade_result(profit_inr)
    data["open_trade"] = None
    
    return trade_record

def update_demo_trade(signal, price, atr_value, utbot_stop):
    """Update trading state - ONLY TP1 (FULL EXIT)"""
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
            
        elif hit_type == "TP1":
            last_closed_trade = close_full_position(data, open_trade, price, "TP1 Hit - Full Exit")
            action_message = f"✅ TP1 HIT @ ${price:.2f} | FULL EXIT | P/L: ₹{last_closed_trade['profit_inr']:.2f}"
            log_entry["action"] = "TP1_FULL_EXIT"
            log_entry["pl_inr"] = last_closed_trade['profit_inr']
            open_trade = None
        
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
            
            # Calculate ONLY TP1
            tp_levels = calculate_take_profit_levels(price, "LONG", atr_value, config)
            tp1_price = tp_levels[0]["price"] if tp_levels else None
            
            open_trade = {
                "type": "LONG",
                "entry_price": price,
                "amount": position_size,
                "original_amount": position_size,
                "stop_loss": stop_loss_price,
                "tp1_price": tp1_price,  # Store only TP1
                "tp_levels": [tp_levels[0]] if tp_levels else [],  # Keep TP1 for display
                "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy": "UT Bot #2 (KV=2, ATR=300)",
                "atr_at_entry": atr_value,
                "breakeven_moved": False
            }
            
            action_message += f"🟢 OPENED LONG @ ${price:.2f} | Size: {position_size} BTC | SL: ${stop_loss_price:.2f} | TP1: ${tp1_price:.2f}"
            log_entry["action"] = "OPEN_LONG"
            log_entry["stop_loss"] = stop_loss_price
            log_entry["tp1"] = tp1_price
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
            
            # Calculate ONLY TP1
            tp_levels = calculate_take_profit_levels(price, "SHORT", atr_value, config)
            tp1_price = tp_levels[0]["price"] if tp_levels else None
            
            open_trade = {
                "type": "SHORT",
                "entry_price": price,
                "amount": position_size,
                "original_amount": position_size,
                "stop_loss": stop_loss_price,
                "tp1_price": tp1_price,  # Store only TP1
                "tp_levels": [tp_levels[0]] if tp_levels else [],  # Keep TP1 for display
                "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "strategy": "UT Bot #1 (KV=2, ATR=1)",
                "atr_at_entry": atr_value,
                "breakeven_moved": False
            }
            
            action_message += f"🔴 OPENED SHORT @ ${price:.2f} | Size: {position_size} BTC | SL: ${stop_loss_price:.2f} | TP1: ${tp1_price:.2f}"
            log_entry["action"] = "OPEN_SHORT"
            log_entry["stop_loss"] = stop_loss_price
            log_entry["tp1"] = tp1_price
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