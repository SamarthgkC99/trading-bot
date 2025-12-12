# risk_manager.py - Hybrid TP/SL Risk Management System

import json
import os
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RISK_CONFIG_FILE = os.path.join(SCRIPT_DIR, "risk_config.json")
RISK_STATE_FILE = os.path.join(SCRIPT_DIR, "risk_state.json")

# Default Risk Configuration
DEFAULT_RISK_CONFIG = {
    "stop_loss": {
        "enabled": True,
        "type": "hybrid",  # hybrid, atr, percentage, utbot
        "atr_multiplier": 2.0,
        "max_loss_percentage": 3.0,
        "trailing_enabled": True,
        "trailing_atr_multiplier": 1.5
    },
    "take_profit": {
        "enabled": True,
        "type": "scaled_atr",  # scaled_atr, fixed, percentage
        "levels": [
            {"percentage": 50, "atr_multiplier": 2.5, "name": "TP1"},
            {"percentage": 30, "atr_multiplier": 5.0, "name": "TP2"},
            {"percentage": 20, "atr_multiplier": 7.5, "name": "TP3"}
        ]
    },
    "position_sizing": {
        "method": "percentage",  # fixed, percentage, risk_based
        "value": 5.0,  # 5% of balance per trade
        "min_position_size": 0.0001,
        "max_position_size": 0.01
    },
    "daily_limits": {
        "enabled": True,
        "max_daily_loss": 1000.0,  # ₹1000 max loss per day
        "max_daily_trades": 20,
        "max_consecutive_losses": 5,
        "reset_hour": 0  # Reset at midnight
    },
    "account_protection": {
        "max_drawdown_percentage": 20.0,  # Stop if 20% down from peak
        "min_balance": 5000.0,  # Stop trading below this
        "emergency_stop": False
    },
    "different_rules_for_position_type": {
        "enabled": True,
        "long": {
            "tp_atr_multipliers": [3.0, 6.0, 9.0]
        },
        "short": {
            "tp_atr_multipliers": [2.0, 4.0, 6.0]
        }
    }
}

def load_risk_config():
    """Load risk configuration from file"""
    if not os.path.exists(RISK_CONFIG_FILE):
        save_risk_config(DEFAULT_RISK_CONFIG)
        return DEFAULT_RISK_CONFIG
    
    with open(RISK_CONFIG_FILE, "r") as f:
        return json.load(f)

def save_risk_config(config):
    """Save risk configuration to file"""
    with open(RISK_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_risk_state():
    """Load daily risk tracking state"""
    if not os.path.exists(RISK_STATE_FILE):
        return reset_daily_state()
    
    with open(RISK_STATE_FILE, "r") as f:
        state = json.load(f)
    
    # Check if we need to reset (new day)
    last_reset = datetime.fromisoformat(state["last_reset"])
    config = load_risk_config()
    reset_hour = config["daily_limits"]["reset_hour"]
    
    now = datetime.now()
    last_reset_date = last_reset.date()
    today = now.date()
    
    # Reset if it's a new day and past reset hour
    if today > last_reset_date or (today == last_reset_date and now.hour >= reset_hour and last_reset.hour < reset_hour):
        state = reset_daily_state()
    
    return state

def save_risk_state(state):
    """Save risk state to file"""
    with open(RISK_STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def reset_daily_state():
    """Reset daily tracking state"""
    state = {
        "daily_loss": 0.0,
        "daily_profit": 0.0,
        "daily_trades": 0,
        "consecutive_losses": 0,
        "last_reset": datetime.now().isoformat(),
        "peak_balance": 0.0
    }
    save_risk_state(state)
    return state

def calculate_position_size(balance, config):
    """Calculate position size based on configuration"""
    method = config["position_sizing"]["method"]
    value = config["position_sizing"]["value"]
    
    if method == "fixed":
        position_size = value
    elif method == "percentage":
        # Calculate based on percentage of balance
        # Assuming BTC price ~$97000, balance in INR, BTC_USDT_RATE = 85
        btc_price_inr = 97000 * 85  # Approximate
        position_value_inr = balance * (value / 100)
        position_size = position_value_inr / btc_price_inr
    else:  # risk_based
        position_size = value
    
    # Apply min/max limits
    min_size = config["position_sizing"]["min_position_size"]
    max_size = config["position_sizing"]["max_position_size"]
    
    position_size = max(min_size, min(max_size, position_size))
    
    return round(position_size, 6)

def calculate_stop_loss(entry_price, position_type, atr_value, utbot_stop, config):
    """
    Calculate stop-loss price using hybrid approach
    
    Args:
        entry_price: Entry price of the position
        position_type: "LONG" or "SHORT"
        atr_value: Current ATR value
        utbot_stop: UT Bot stop line value
        config: Risk configuration
    
    Returns:
        stop_loss_price: Calculated stop-loss price
    """
    sl_config = config["stop_loss"]
    
    if not sl_config["enabled"]:
        return None
    
    sl_type = sl_config["type"]
    
    if position_type == "LONG":
        # ATR-based stop
        sl_atr = entry_price - (atr_value * sl_config["atr_multiplier"])
        
        # Fixed percentage stop
        sl_fixed = entry_price * (1 - sl_config["max_loss_percentage"] / 100)
        
        # UT Bot stop
        sl_utbot = utbot_stop
        
        if sl_type == "hybrid":
            # Use the tighter (higher for LONG) of ATR and fixed
            sl_candidate = max(sl_atr, sl_fixed)
            # But not higher than UT Bot stop
            stop_loss = max(sl_candidate, sl_utbot) if sl_utbot else sl_candidate
        elif sl_type == "atr":
            stop_loss = sl_atr
        elif sl_type == "percentage":
            stop_loss = sl_fixed
        elif sl_type == "utbot":
            stop_loss = sl_utbot if sl_utbot else sl_fixed
        else:
            stop_loss = sl_fixed
            
    else:  # SHORT
        # ATR-based stop
        sl_atr = entry_price + (atr_value * sl_config["atr_multiplier"])
        
        # Fixed percentage stop
        sl_fixed = entry_price * (1 + sl_config["max_loss_percentage"] / 100)
        
        # UT Bot stop
        sl_utbot = utbot_stop
        
        if sl_type == "hybrid":
            # Use the tighter (lower for SHORT) of ATR and fixed
            sl_candidate = min(sl_atr, sl_fixed)
            # But not lower than UT Bot stop
            stop_loss = min(sl_candidate, sl_utbot) if sl_utbot else sl_candidate
        elif sl_type == "atr":
            stop_loss = sl_atr
        elif sl_type == "percentage":
            stop_loss = sl_fixed
        elif sl_type == "utbot":
            stop_loss = sl_utbot if sl_utbot else sl_fixed
        else:
            stop_loss = sl_fixed
    
    return round(stop_loss, 2)

def calculate_take_profit_levels(entry_price, position_type, atr_value, config):
    """
    Calculate multiple take-profit levels
    
    Returns:
        List of dicts with 'price', 'percentage', 'name'
    """
    tp_config = config["take_profit"]
    
    if not tp_config["enabled"]:
        return []
    
    levels = []
    
    # Check if using different rules for position types
    if config["different_rules_for_position_type"]["enabled"]:
        if position_type == "LONG":
            multipliers = config["different_rules_for_position_type"]["long"]["tp_atr_multipliers"]
        else:
            multipliers = config["different_rules_for_position_type"]["short"]["tp_atr_multipliers"]
        
        # Use custom multipliers
        for i, mult in enumerate(multipliers):
            if position_type == "LONG":
                tp_price = entry_price + (atr_value * mult)
            else:
                tp_price = entry_price - (atr_value * mult)
            
            # Get percentage from config or use defaults
            if i < len(tp_config["levels"]):
                percentage = tp_config["levels"][i]["percentage"]
                name = tp_config["levels"][i]["name"]
            else:
                percentage = 100 // len(multipliers)
                name = f"TP{i+1}"
            
            levels.append({
                "price": round(tp_price, 2),
                "percentage": percentage,
                "name": name,
                "hit": False
            })
    else:
        # Use standard config
        for level in tp_config["levels"]:
            if position_type == "LONG":
                tp_price = entry_price + (atr_value * level["atr_multiplier"])
            else:
                tp_price = entry_price - (atr_value * level["atr_multiplier"])
            
            levels.append({
                "price": round(tp_price, 2),
                "percentage": level["percentage"],
                "name": level["name"],
                "hit": False
            })
    
    return levels

def update_trailing_stop(current_price, position_type, stop_loss, atr_value, config):
    """
    Update trailing stop-loss
    
    Returns:
        new_stop_loss: Updated stop-loss price or None if no update
    """
    sl_config = config["stop_loss"]
    
    if not sl_config["trailing_enabled"]:
        return None
    
    trailing_distance = atr_value * sl_config["trailing_atr_multiplier"]
    
    if position_type == "LONG":
        new_stop = current_price - trailing_distance
        # Only move stop up, never down
        if new_stop > stop_loss:
            return round(new_stop, 2)
    else:  # SHORT
        new_stop = current_price + trailing_distance
        # Only move stop down, never up
        if new_stop < stop_loss:
            return round(new_stop, 2)
    
    return None

def check_daily_limits(state, config):
    """
    Check if daily limits are reached
    
    Returns:
        (allowed, reason) tuple
    """
    limits = config["daily_limits"]
    
    if not limits["enabled"]:
        return (True, None)
    
    # Check max daily loss
    if state["daily_loss"] >= limits["max_daily_loss"]:
        return (False, f"Daily loss limit reached (₹{state['daily_loss']:.2f} / ₹{limits['max_daily_loss']:.2f})")
    
    # Check max daily trades
    if state["daily_trades"] >= limits["max_daily_trades"]:
        return (False, f"Daily trade limit reached ({state['daily_trades']} / {limits['max_daily_trades']})")
    
    # Check consecutive losses
    if state["consecutive_losses"] >= limits["max_consecutive_losses"]:
        return (False, f"Max consecutive losses reached ({state['consecutive_losses']})")
    
    return (True, None)

def check_account_protection(balance, state, config):
    """
    Check account protection rules
    
    Returns:
        (allowed, reason) tuple
    """
    protection = config["account_protection"]
    
    # Check emergency stop
    if protection["emergency_stop"]:
        return (False, "Emergency stop activated")
    
    # Check minimum balance
    if balance < protection["min_balance"]:
        return (False, f"Balance below minimum (₹{balance:.2f} < ₹{protection['min_balance']:.2f})")
    
    # Check max drawdown
    if state["peak_balance"] > 0:
        drawdown_pct = ((state["peak_balance"] - balance) / state["peak_balance"]) * 100
        if drawdown_pct >= protection["max_drawdown_percentage"]:
            return (False, f"Max drawdown exceeded ({drawdown_pct:.2f}% >= {protection['max_drawdown_percentage']}%)")
    
    # Update peak balance
    if balance > state["peak_balance"]:
        state["peak_balance"] = balance
        save_risk_state(state)
    
    return (True, None)

def can_open_trade(balance):
    """
    Check if a new trade can be opened
    
    Returns:
        (allowed, reason) dict
    """
    config = load_risk_config()
    state = load_risk_state()
    
    # Check daily limits
    daily_allowed, daily_reason = check_daily_limits(state, config)
    if not daily_allowed:
        return {"allowed": False, "reason": daily_reason}
    
    # Check account protection
    account_allowed, account_reason = check_account_protection(balance, state, config)
    if not account_allowed:
        return {"allowed": False, "reason": account_reason}
    
    return {"allowed": True, "reason": None}

def record_trade_result(profit_loss):
    """Record the result of a closed trade"""
    state = load_risk_state()
    
    state["daily_trades"] += 1
    
    if profit_loss < 0:
        state["daily_loss"] += abs(profit_loss)
        state["consecutive_losses"] += 1
    else:
        state["daily_profit"] += profit_loss
        state["consecutive_losses"] = 0  # Reset on win
    
    save_risk_state(state)

def get_risk_status():
    """Get current risk management status"""
    config = load_risk_config()
    state = load_risk_state()
    
    limits = config["daily_limits"]
    
    return {
        "daily_stats": {
            "trades": f"{state['daily_trades']}/{limits['max_daily_trades']}",
            "loss": f"₹{state['daily_loss']:.2f}/₹{limits['max_daily_loss']:.2f}",
            "profit": f"₹{state['daily_profit']:.2f}",
            "consecutive_losses": f"{state['consecutive_losses']}/{limits['max_consecutive_losses']}"
        },
        "limits_usage": {
            "trades_pct": (state['daily_trades'] / limits['max_daily_trades']) * 100 if limits['max_daily_trades'] > 0 else 0,
            "loss_pct": (state['daily_loss'] / limits['max_daily_loss']) * 100 if limits['max_daily_loss'] > 0 else 0
        },
        "config": config
    }

def move_stop_to_breakeven(entry_price, position_type):
    """
    Calculate break-even stop-loss price
    Add small buffer to account for fees
    """
    buffer = 0.001  # 0.1% buffer for fees
    
    if position_type == "LONG":
        return round(entry_price * (1 + buffer), 2)
    else:  # SHORT
        return round(entry_price * (1 - buffer), 2)