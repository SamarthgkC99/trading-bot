# utbot_logic.py
# Rewritten to use Binance Vision mirror (data-api.binance.vision) with CoinGecko fallback.
# Provides: fetch_btc_data(), get_current_price(), calc_utbot(), calculate_atr_stable(), get_utbot_signal()

import requests
import pandas as pd
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Primary (non-blocked) endpoints (Binance Vision mirror)
BINANCE_VISION_KLINES = "https://data-api.binance.vision/api/v3/klines"
BINANCE_VISION_TICKER_PRICE = "https://data-api.binance.vision/api/v3/ticker/price"

# Fallback provider (CoinGecko)
COINGECKO_OHLC = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"
COINGECKO_PRICE = "https://api.coingecko.com/api/v3/simple/price"

REQUEST_TIMEOUT = 10
RETRY_ATTEMPTS = 3
RETRY_DELAY = 1.0  # seconds


def _request_with_retries(url: str, params: dict = None, headers: dict = None):
    """Simple requests.get wrapper with retries and logging."""
    last_exc = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            # Log non-200 for debugging
            logger.warning(f"Request to {url} returned status {resp.status_code}: {resp.text[:200]}")
            last_exc = Exception(f"Status {resp.status_code}")
        except Exception as e:
            logger.warning(f"Request attempt {attempt} to {url} failed: {e}")
            last_exc = e
        time.sleep(RETRY_DELAY * attempt)
    logger.error(f"All {RETRY_ATTEMPTS} attempts failed for {url}")
    raise last_exc


def fetch_btc_data(limit: int = 350, interval: str = "5m") -> pd.DataFrame:
    """
    Fetch latest klines for BTCUSDT.
    Primary: Binance Vision mirror (same kline format as Binance).
    Fallback: CoinGecko OHLC (converted to Binance-like kline format).
    Returns a pandas DataFrame with columns: time, open, high, low, close, volume, ...
    """
    # Try Binance Vision first
    try:
        params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
        resp = _request_with_retries(BINANCE_VISION_KLINES, params=params)
        data = resp.json()  # list of lists (kline arrays)
        if not data:
            logger.warning("Binance Vision returned empty klines")
            raise ValueError("empty data from binance vision")

        # Columns according to Binance API kline spec
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ])
        # Convert numeric columns to floats
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        # time is already milliseconds since epoch in Binance API
        logger.info(f"✓ Fetched {len(df)} candles from Binance Vision")
        return df

    except Exception as e:
        logger.warning(f"Binance Vision klines failed: {e}. Falling back to CoinGecko.")

    # Fallback: CoinGecko OHLC (returns [timestamp, open, high, low, close])
    try:
        params = {"vs_currency": "usd", "days": "1"}  # days=1 provides recent data; adjust if needed
        resp = _request_with_retries(COINGECKO_OHLC, params=params)
        data = resp.json()
        if not data:
            logger.error("CoinGecko returned empty OHLC data")
            return pd.DataFrame()

        # CoinGecko returns timestamps in milliseconds and OHLC: [time, o, h, l, c]
        # We'll convert to Binance-like kline rows; volume and other fields unavailable -> set to 0 or NaN
        rows = []
        for row in data:
            ts_ms, o, h, l, c = row
            rows.append([
                ts_ms,                # time
                float(o),             # open
                float(h),             # high
                float(l),             # low
                float(c),             # close
                0.0,                  # volume (unknown)
                None, None, None, None, None, None
            ])
        df = pd.DataFrame(rows, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
        ])
        logger.info(f"✓ Fetched {len(df)} candles from CoinGecko (fallback)")
        return df

    except Exception as e:
        logger.error(f"Fallback CoinGecko OHLC failed: {e}")
        return pd.DataFrame()


def get_current_price() -> Optional[float]:
    """
    Get current BTC price.
    Primary: Binance Vision ticker price endpoint.
    Fallback: CoinGecko simple/price endpoint.
    """
    # Binance Vision ticker price
    try:
        params = {"symbol": "BTCUSDT"}
        resp = _request_with_retries(BINANCE_VISION_TICKER_PRICE, params=params)
        data = resp.json()
        # data example: {"symbol":"BTCUSDT","price":"43500.12"}
        if isinstance(data, dict) and "price" in data:
            price = float(data["price"])
            logger.info(f"✓ Current BTC price from Binance Vision: {price}")
            return price
        logger.warning("Unexpected Binance Vision ticker response format")
    except Exception as e:
        logger.warning(f"Binance Vision ticker failed: {e}")

    # CoinGecko fallback
    try:
        params = {"ids": "bitcoin", "vs_currencies": "usd"}
        resp = _request_with_retries(COINGECKO_PRICE, params=params)
        data = resp.json()
        # data example: {"bitcoin": {"usd": 43500.12}}
        price = float(data.get("bitcoin", {}).get("usd", 0))
        if price > 0:
            logger.info(f"✓ Current BTC price from CoinGecko: {price}")
            return price
        logger.error("CoinGecko returned no price for bitcoin")
    except Exception as e:
        logger.error(f"CoinGecko price fallback failed: {e}")

    return None


def calc_utbot(df: pd.DataFrame, keyvalue: int, atr_period: int) -> pd.DataFrame:
    """
    Calculates a simple UT Bot trailing stop and signal position similar to your previous logic.
    Expects df with columns: 'time', 'open', 'high', 'low', 'close'
    Returns the df with additional columns: 'tr', 'atr', 'stop', 'pos'
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    # Ensure numeric types
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # True range and ATR
    df["tr"] = df["high"] - df["low"]
    df["atr"] = df["tr"].rolling(atr_period).mean()
    nLoss = keyvalue * df["atr"]

    # Initialize trailing stop and position arrays
    xATRTrailingStop = [df["close"].iloc[0]]
    pos = [0]

    for i in range(1, len(df)):
        prev_stop = xATRTrailingStop[-1]
        src = df["close"].iloc[i]
        src1 = df["close"].iloc[i - 1]

        # if both current and previous close are above previous stop -> long mode
        if (src > prev_stop) and (src1 > prev_stop):
            new_stop = max(prev_stop, src - nLoss.iloc[i])
        # if both below -> short mode
        elif (src < prev_stop) and (src1 < prev_stop):
            new_stop = min(prev_stop, src + nLoss.iloc[i])
        else:
            # switch: if src > prev_stop use long-style stop else short-style stop
            new_stop = src - nLoss.iloc[i] if src > prev_stop else src + nLoss.iloc[i]

        xATRTrailingStop.append(new_stop)

        # position detection (1 long, -1 short, carry forward previous)
        if (src1 < prev_stop) and (src > prev_stop):
            pos.append(1)
        elif (src1 > prev_stop) and (src < prev_stop):
            pos.append(-1)
        else:
            pos.append(pos[-1])

    df["stop"] = xATRTrailingStop
    df["pos"] = pos
    return df


def calculate_atr_stable(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Return stable ATR value for risk management (last value)."""
    if df is None or df.empty:
        return None
    df2 = df.copy()
    df2["tr"] = df2["high"] - df2["low"]
    df2["atr"] = df2["tr"].rolling(period).mean()
    if df2["atr"].isna().all():
        return None
    return float(df2["atr"].iloc[-1])


def get_utbot_signal():
    """
    Generate a UT Bot style signal using the fetched data.
    Returns dict: {signal, price, atr, utbot_stop}
    """
    try:
        df = fetch_btc_data()
        if df is None or df.empty:
            logger.error("No data fetched for signal generation")
            return {"signal": "No Data", "price": 0, "atr": 0, "utbot_stop": 0}

        # compute UT Bot stop/positions for two parameter sets to emulate your logic
        df1 = calc_utbot(df.copy(), 2, 1)    # fast
        df2 = calc_utbot(df.copy(), 2, 300)  # slow (buy-only)
        latest_price = float(df["close"].iloc[-1])

        signal1 = int(df1["pos"].iloc[-1]) if "pos" in df1.columns else 0
        signal2 = int(df2["pos"].iloc[-1]) if "pos" in df2.columns else 0
        stop1 = float(df1["stop"].iloc[-1]) if "stop" in df1.columns else latest_price
        stop2 = float(df2["stop"].iloc[-1]) if "stop" in df2.columns else latest_price

        atr_stable = calculate_atr_stable(df, period=14)
        if atr_stable is None:
            atr_stable = 0.0

        latest_signal = "Hold"
        utbot_stop = latest_price

        # Your original priority: if slow says Buy -> Buy, if fast says Sell -> Sell (override)
        if signal2 == 1:
            latest_signal = "Buy"
            utbot_stop = stop2

        if signal1 == -1:
            latest_signal = "Sell"
            utbot_stop = stop1

        # Log summary
        logger.info(f"Signal: {latest_signal} | Price: {latest_price} | ATR(14): {atr_stable:.6f}")

        return {
            "signal": latest_signal,
            "price": float(latest_price),
            "atr": float(atr_stable),
            "utbot_stop": float(utbot_stop),
        }

    except Exception as e:
        logger.error(f"Error in get_utbot_signal: {e}", exc_info=True)
        return {"signal": "No Data", "price": 0, "atr": 0, "utbot_stop": 0}
