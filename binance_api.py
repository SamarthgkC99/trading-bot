"""
Binance Public API - Fixed for Render deployment
Handles 451 errors and DNS failures with multiple fallback endpoints
"""

import requests
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class BinancePublicAPI:
    """Reliable Binance public API client with multiple fallback endpoints"""
    
    # Multiple endpoints for fallback (Render-friendly)
    ENDPOINTS = [
        "https://api.binance.com",
        "https://api1.binance.com", 
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://data.binance.com",
    ]
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        })
        self.last_working_endpoint = None
    
    def _make_request(self, path: str, params: dict, timeout: int = 10) -> Optional[dict]:
        """Try each endpoint until one works"""
        # Try last working endpoint first
        endpoints_to_try = self.ENDPOINTS.copy()
        if self.last_working_endpoint:
            endpoints_to_try.remove(self.last_working_endpoint)
            endpoints_to_try.insert(0, self.last_working_endpoint)
        
        for endpoint in endpoints_to_try:
            try:
                url = f"{endpoint}{path}"
                response = self.session.get(url, params=params, timeout=timeout)
                
                if response.status_code == 200:
                    self.last_working_endpoint = endpoint
                    logger.info(f"✓ Success with {endpoint}")
                    return response.json()
                    
                elif response.status_code == 451:
                    logger.warning(f"✗ {endpoint} returned 451 (blocked)")
                    continue
                    
                else:
                    logger.warning(f"✗ {endpoint} returned {response.status_code}")
                    continue
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"✗ {endpoint} connection failed")
                continue
                
            except requests.exceptions.Timeout:
                logger.warning(f"✗ {endpoint} timeout")
                continue
                
            except Exception as e:
                logger.warning(f"✗ {endpoint} error: {str(e)}")
                continue
        
        logger.error("✗ All Binance endpoints failed")
        return None
    
    def get_price(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """Get current price - SIMPLEST METHOD"""
        data = self._make_request("/api/v3/ticker/price", {"symbol": symbol})
        if data:
            return float(data['price'])
        return None
    
    def get_klines(self, symbol: str = "BTCUSDT", interval: str = "5m", limit: int = 350) -> Optional[List[List]]:
        """
        Get candlestick data
        
        Returns raw klines data (list of lists) compatible with existing code
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        
        data = self._make_request("/api/v3/klines", params)
        return data if data else None
    
    def get_24h_stats(self, symbol: str = "BTCUSDT") -> Optional[Dict]:
        """Get 24h statistics"""
        data = self._make_request("/api/v3/ticker/24hr", {"symbol": symbol})
        
        if data:
            return {
                'price': float(data['lastPrice']),
                'high': float(data['highPrice']),
                'low': float(data['lowPrice']),
                'volume': float(data['volume']),
                'change_percent': float(data['priceChangePercent'])
            }
        return None


# Singleton instance
_api_instance = None

def get_binance_api():
    """Get or create Binance API instance"""
    global _api_instance
    if _api_instance is None:
        _api_instance = BinancePublicAPI()
    return _api_instance