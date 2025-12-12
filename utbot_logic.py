# utbot_logic.py - Fixed with reliable Binance API

import pandas as pd
import logging
from binance_api import get_binance_api

logger = logging.getLogger(__name__)

def fetch_btc_data():
    """Fetches the latest 5-minute Kline data for BTCUSDT from Binance."""
    try:
        api = get_binance_api()
        data = api.get_klines(symbol="BTCUSDT", interval="5m", limit=350)
        
        if not data:
            logger.error("Failed to fetch klines from all Binance endpoints")
            return pd.DataFrame()
        
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume", 
            "c", "q", "n", "t", "v", "ignore"
        ])
        
        for col in ["close", "high", "low", "open"]:
            df[col] = df[col].astype(float)
        
        logger.info(f"✓ Fetched {len(df)} candles successfully")
        return df
        
    except Exception as e:
        logger.error(f"Error in fetch_btc_data: {e}")
        return pd.DataFrame()

def calc_utbot(df, keyvalue, atr_period):
    """Calculates the UT Bot trailing stop and signals."""
    if df.empty:
        return df

    df["tr"] = df["high"] - df["low"]
    df["atr"] = df["tr"].rolling(atr_period).mean()
    nLoss = keyvalue * df["atr"]

    xATRTrailingStop = [df["close"].iloc[0]]
    pos = [0]
    
    for i in range(1, len(df)):
        prev_stop = xATRTrailingStop[-1]
        src = df["close"].iloc[i]
        src1 = df["close"].iloc[i - 1]

        if src > prev_stop and src1 > prev_stop:
            new_stop = max(prev_stop, src - nLoss.iloc[i])
        elif src < prev_stop and src1 < prev_stop:
            new_stop = min(prev_stop, src + nLoss.iloc[i])
        else:
            new_stop = src - nLoss.iloc[i] if src > prev_stop else src + nLoss.iloc[i]

        xATRTrailingStop.append(new_stop)

        if src1 < prev_stop and src > prev_stop:
            pos.append(1)
        elif src1 > prev_stop and src < prev_stop:
            pos.append(-1)
        else:
            pos.append(pos[-1])

    df["stop"] = xATRTrailingStop
    df["pos"] = pos
    return df

def get_current_price():
    """Fetches only the current price for BTCUSDT."""
    try:
        api = get_binance_api()
        price = api.get_price("BTCUSDT")
        
        if price:
            logger.info(f"✓ Current BTC price: ${price:,.2f}")
            return price
        else:
            logger.error("Failed to fetch current price from all endpoints")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching current price: {e}")
        return None

def calculate_atr_stable(df, period=14):
    """Calculate a stable ATR for risk management"""
    if df.empty:
        return None
    
    df = df.copy()
    df["tr"] = df["high"] - df["low"]
    df["atr"] = df["tr"].rolling(period).mean()
    
    return df["atr"].iloc[-1] if not df["atr"].isna().all() else None

def get_utbot_signal():
    """Generates the final UT Bot signal with ATR and stop values"""
    df = fetch_btc_data()
    
    if df.empty:
        logger.error("No data fetched from Binance!")
        return {
            "signal": "No Data", 
            "price": 0, 
            "atr": 0, 
            "utbot_stop": 0
        }

    df1 = calc_utbot(df.copy(), 2, 1)
    df2 = calc_utbot(df.copy(), 2, 300)

    latest_price = df["close"].iloc[-1]
    latest_signal = "Hold"

    signal1 = df1["pos"].iloc[-1]
    signal2 = df2["pos"].iloc[-1]

    stop1 = df1["stop"].iloc[-1]
    stop2 = df2["stop"].iloc[-1]

    atr_stable = calculate_atr_stable(df, period=14)
    
    if atr_stable is None or pd.isna(atr_stable):
        atr_stable = 0
        logger.warning("ATR calculation returned None, defaulting to 0")

    print(f"\n{'='*70}")
    print(f"BTCUSDT: ${latest_price:.2f}")
    print(f"ATR (14-period): ${atr_stable:.2f}")
    print(f"{'='*70}")

    utbot_stop = None

    if signal2 == 1:
        latest_signal = "Buy"
        utbot_stop = stop2
        print(f"✅ UT Bot #2 (KV=2, ATR=300) [Buy Only]: BUY Signal Detected")
        print(f"   Stop Line: ${stop2:.2f}")
    else:
        print(f"⬜ UT Bot #2 (KV=2, ATR=300) [Buy Only]: Hold")
    
    if signal1 == -1:
        latest_signal = "Sell"
        utbot_stop = stop1
        print(f"✅ UT Bot #1 (KV=2, ATR=1) [Sell Only]: SELL Signal Detected")
        print(f"   Stop Line: ${stop1:.2f}")
    else:
        print(f"⬜ UT Bot #1 (KV=2, ATR=1) [Sell Only]: Hold")

    print(f"{'='*70}")
    print(f"Final Signal: {latest_signal}")
    print(f"{'='*70}\n")
    
    return {
        "signal": latest_signal, 
        "price": float(latest_price),
        "atr": float(atr_stable) if atr_stable else 0.0,
        "utbot_stop": float(utbot_stop) if utbot_stop else float(latest_price)
    }