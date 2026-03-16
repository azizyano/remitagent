"""
Off-chain FX Rate Oracle for RemitAgent.
Priority: 1) Frankfurter (EUR base, majors) 2) FloatRates (emerging) 3) ExchangeRate-API 4) Manual cache

Supports both major currencies (EUR, USD, GBP) and emerging markets (KES, COP, NGN, etc.)
"""
from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
import asyncio

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config
from logger import logger


# Currencies supported by each source
FRANKFURTER_CURRENCIES = {
    'AUD', 'BGN', 'BRL', 'CAD', 'CHF', 'CNY', 'CZK', 'DKK', 'EUR', 'GBP',
    'HKD', 'HRK', 'HUF', 'IDR', 'ILS', 'INR', 'ISK', 'JPY', 'KRW', 'MXN',
    'MYR', 'NOK', 'NZD', 'PHP', 'PLN', 'RON', 'RUB', 'SEK', 'SGD', 'THB',
    'TRY', 'USD', 'ZAR'
}

EMERGING_CURRENCIES = {
    'KES',  # Kenyan Shilling
    'COP',  # Colombian Peso
    'NGN',  # Nigerian Naira
    'BRL',  # Brazilian Real (also in Frankfurter)
    'ZAR',  # South African Rand (also in Frankfurter)
    'MXN',  # Mexican Peso (also in Frankfurter)
    'IDR',  # Indonesian Rupiah
    'PHP',  # Philippine Peso
    'VND',  # Vietnamese Dong
    'EGP',  # Egyptian Pound
    'GHS',  # Ghanaian Cedi (new Mento stable)
    'TZS',  # Tanzanian Shilling
    'UGX',  # Ugandan Shilling
    'RWF',  # Rwandan Franc
    'ETB',  # Ethiopian Birr
    'XOF',  # West African CFA (new Mento stable)
    'XAF',  # Central African CFA
}


class FXOracle:
    """
    Off-chain FX rate oracle with multiple fallback sources.
    Provides real-world fiat exchange rates for arbitrage detection.
    """
    
    def __init__(self):
        self.frankfurter_url = config.fx.frankfurter_url
        self.exchange_rate_api_key = config.fx.exchange_rate_api_key
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 minutes
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _get_cache_key(self, base: str, quote: str) -> str:
        """Generate cache key for a currency pair."""
        return f"{base.upper()}/{quote.upper()}"
    
    def _get_cached_rate(self, base: str, quote: str) -> Optional[Dict[str, Any]]:
        """Get cached rate if still valid."""
        cache_key = self._get_cache_key(base, quote)
        cached = self._cache.get(cache_key)
        
        if cached:
            age = (datetime.utcnow() - cached["timestamp"]).total_seconds()
            if age < self._cache_ttl:
                return cached
        
        return None
    
    def _set_cached_rate(self, base: str, quote: str, rate: float):
        """Cache a rate with timestamp."""
        cache_key = self._get_cache_key(base, quote)
        self._cache[cache_key] = {
            "rate": rate,
            "timestamp": datetime.utcnow()
        }
        # Also cache inverse
        inverse_key = self._get_cache_key(quote, base)
        self._cache[inverse_key] = {
            "rate": 1.0 / rate if rate > 0 else 0,
            "timestamp": datetime.utcnow()
        }
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True
    )
    async def _fetch_frankfurter(self, base: str, quote: str) -> float:
        """Fetch rate from Frankfurter API (EUR-based, majors only)."""
        # Check if currencies are supported
        if base.upper() not in FRANKFURTER_CURRENCIES or quote.upper() not in FRANKFURTER_CURRENCIES:
            raise ValueError(f"Frankfurter doesn't support {base}/{quote}")
        
        session = await self._get_session()
        
        # Frankfurter uses EUR as base, so we may need conversion
        if base.upper() == "EUR":
            url = f"{self.frankfurter_url}/latest"
            params = {"to": quote.upper()}
        elif quote.upper() == "EUR":
            url = f"{self.frankfurter_url}/latest"
            params = {"from": base.upper()}
        else:
            # Need cross-rate through EUR
            url = f"{self.frankfurter_url}/latest"
            params = {"from": base.upper(), "to": quote.upper()}
        
        async with session.get(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            
            rates = data.get("rates", {})
            if quote.upper() in rates:
                return rates[quote.upper()]
            
            raise ValueError(f"Rate not found for {base}/{quote}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True
    )
    async def _fetch_floatrates(self, base: str, quote: str) -> float:
        """
        Fetch rate from FloatRates API (supports 150+ currencies including KES, COP, NGN).
        Free, no API key required.
        """
        session = await self._get_session()
        
        # FloatRates uses USD as base for most queries
        base_lower = base.lower()
        quote_upper = quote.upper()
        
        url = f"https://floatrates.com/daily/{base_lower}.json"
        
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
            
            # FloatRates returns dict with currency codes as keys
            if quote_lower := quote.lower():
                if quote_lower in data:
                    return float(data[quote_lower]['rate'])
            
            raise ValueError(f"Currency {quote} not found in FloatRates")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True
    )
    async def _fetch_open_er_api(self, base: str, quote: str) -> float:
        """
        Fetch rate from Open Exchange Rates API (free tier).
        Supports many currencies including emerging markets.
        """
        session = await self._get_session()
        
        url = f"https://open.er-api.com/v6/latest/{base.upper()}"
        
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
            
            if data.get("result") == "success":
                rates = data.get("rates", {})
                if quote.upper() in rates:
                    return float(rates[quote.upper()])
            
            raise ValueError(f"Rate not found for {base}/{quote}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True
    )
    async def _fetch_exchangerate_api(self, base: str, quote: str) -> float:
        """Fetch rate from ExchangeRate-API."""
        session = await self._get_session()
        
        if self.exchange_rate_api_key:
            url = f"https://v6.exchangerate-api.com/v6/{self.exchange_rate_api_key}/latest/{base.upper()}"
        else:
            # Use free tier without API key
            url = f"https://api.exchangerate-api.com/v4/latest/{base.upper()}"
        
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
            
            rates = data.get("rates", {})
            if quote.upper() in rates:
                return rates[quote.upper()]
            
            raise ValueError(f"Rate not found for {base}/{quote}")
    
    async def get_fiat_rate(self, base_currency: str, quote_currency: str) -> Dict[str, Any]:
        """
        Get fiat exchange rate with fallback priority.
        
        Strategy:
        1. Check cache
        2. For majors (EUR, USD, GBP): Try Frankfurter first
        3. For emerging (KES, COP, NGN): Try FloatRates first
        4. Fallback to Open.ER-API (supports most currencies)
        5. Last resort: ExchangeRate-API
        
        Args:
            base_currency: Base currency code (USD, EUR, KES)
            quote_currency: Quote currency code
            
        Returns:
            Dict with mid_rate and timestamp
        """
        # Check cache first
        cached = self._get_cached_rate(base_currency, quote_currency)
        if cached:
            return {
                "mid_rate": cached["rate"],
                "timestamp": cached["timestamp"],
                "source": "cache"
            }
        
        is_emerging = (
            base_currency.upper() in EMERGING_CURRENCIES or 
            quote_currency.upper() in EMERGING_CURRENCIES
        )
        
        errors = []
        
        # For emerging markets, try FloatRates first
        if is_emerging:
            try:
                rate = await self._fetch_floatrates(base_currency, quote_currency)
                self._set_cached_rate(base_currency, quote_currency, rate)
                return {
                    "mid_rate": rate,
                    "timestamp": datetime.utcnow(),
                    "source": "floatrates"
                }
            except Exception as e:
                errors.append(f"FloatRates: {e}")
            
            # Try Open.ER-API (good for emerging markets)
            try:
                rate = await self._fetch_open_er_api(base_currency, quote_currency)
                self._set_cached_rate(base_currency, quote_currency, rate)
                return {
                    "mid_rate": rate,
                    "timestamp": datetime.utcnow(),
                    "source": "open_er_api"
                }
            except Exception as e:
                errors.append(f"Open.ER-API: {e}")
        
        # For majors, try Frankfurter first
        if not is_emerging:
            try:
                rate = await self._fetch_frankfurter(base_currency, quote_currency)
                self._set_cached_rate(base_currency, quote_currency, rate)
                return {
                    "mid_rate": rate,
                    "timestamp": datetime.utcnow(),
                    "source": "frankfurter"
                }
            except Exception as e:
                errors.append(f"Frankfurter: {e}")
        
        # Try ExchangeRate-API as fallback
        try:
            rate = await self._fetch_exchangerate_api(base_currency, quote_currency)
            self._set_cached_rate(base_currency, quote_currency, rate)
            return {
                "mid_rate": rate,
                "timestamp": datetime.utcnow(),
                "source": "exchangerate-api"
            }
        except Exception as e:
            errors.append(f"ExchangeRate-API: {e}")
        
        # If Frankfurter failed for majors, try FloatRates
        if not is_emerging:
            try:
                rate = await self._fetch_floatrates(base_currency, quote_currency)
                self._set_cached_rate(base_currency, quote_currency, rate)
                return {
                    "mid_rate": rate,
                    "timestamp": datetime.utcnow(),
                    "source": "floatrates_fallback"
                }
            except Exception as e:
                errors.append(f"FloatRates fallback: {e}")
        
        logger.error(f"All FX sources failed for {base_currency}/{quote_currency}: {errors}")
        raise ValueError(f"All FX sources failed for {base_currency}/{quote_currency}")
    
    async def get_rate_with_fallback(self, base: str, quote: str) -> float:
        """Convenience method that just returns the rate."""
        result = await self.get_fiat_rate(base, quote)
        return result["mid_rate"]
    
    def calculate_implied_fx(
        self, 
        onchain_rate: float, 
        fiat_rate: float
    ) -> Dict[str, Any]:
        """
        Calculate premium/discount between on-chain and fiat rates.
        
        Args:
            onchain_rate: On-chain exchange rate
            fiat_rate: Fiat exchange rate
            
        Returns:
            Dict with premium/discount percentage
        """
        if fiat_rate == 0:
            return {"premium_percent": 0, "discount_percent": 0}
        
        difference = onchain_rate - fiat_rate
        premium_percent = (difference / fiat_rate) * 100
        
        return {
            "onchain_rate": onchain_rate,
            "fiat_rate": fiat_rate,
            "difference": difference,
            "premium_percent": premium_percent,
            "is_premium": premium_percent > 0,
            "is_discount": premium_percent < 0
        }
    
    async def detect_arbitrage(
        self,
        mento_rate: float,
        uniswap_rate: float,
        fiat_rate: float,
        pair: str
    ) -> Dict[str, Any]:
        """
        Detect arbitrage opportunity between Mento, Uniswap, and fiat rates.
        
        Args:
            mento_rate: Mento FPMM rate
            uniswap_rate: Uniswap V3 rate
            fiat_rate: Fiat FX rate
            pair: Trading pair (e.g., "cUSD-cEUR")
            
        Returns:
            Arbitrage detection result
        """
        # Calculate spreads with safety checks for zero rates
        mento_fiat_diff = abs(mento_rate - fiat_rate) / fiat_rate * 100 if fiat_rate > 0 else 0
        uniswap_fiat_diff = abs(uniswap_rate - fiat_rate) / fiat_rate * 100 if fiat_rate > 0 else 0
        
        min_rate = min(mento_rate, uniswap_rate)
        mento_uniswap_diff = abs(mento_rate - uniswap_rate) / min_rate * 100 if min_rate > 0 else 0
        
        # Determine direction
        if mento_uniswap_diff < 0.1 or min_rate == 0:
            direction = "no_opportunity"
        elif mento_rate < uniswap_rate:
            # Mento is cheaper, buy on Mento, sell on Uniswap
            direction = "mento_to_uniswap"
        else:
            # Uniswap is cheaper, buy on Uniswap, sell on Mento
            direction = "uniswap_to_mento"
        
        # Calculate potential profit (simplified)
        spread_percent = mento_uniswap_diff
        profit_usd = 0  # Would need trade size to calculate
        
        # Determine confidence based on liquidity (placeholder)
        confidence = "high" if spread_percent > 1.0 else "medium" if spread_percent > 0.5 else "low"
        
        return {
            "pair": pair,
            "direction": direction,
            "spread_percent": spread_percent,
            "profit_usd": profit_usd,
            "confidence": confidence,
            "rates": {
                "mento": mento_rate,
                "uniswap": uniswap_rate,
                "fiat": fiat_rate
            },
            "differences": {
                "mento_vs_fiat": mento_fiat_diff,
                "uniswap_vs_fiat": uniswap_fiat_diff,
                "mento_vs_uniswap": mento_uniswap_diff
            }
        }
    
    def map_stablecoin_to_fiat(self, stablecoin: str) -> str:
        """
        Map Celo stablecoin symbol to fiat currency code.
        
        Args:
            stablecoin: Stablecoin symbol (cUSD, cEUR, cKES, USDm, axlUSDC)
            
        Returns:
            Fiat currency code
        """
        mapping = {
            # Legacy c-prefix tokens
            "cUSD": "USD",
            "cEUR": "EUR",
            "cREAL": "BRL",
            "cKES": "KES",
            "cCOP": "COP",
            "cNGN": "NGN",
            # New m-suffix tokens (Mento v2)
            "USDm": "USD",
            "EURm": "EUR",
            "BRLm": "BRL",
            "KESm": "KES",
            "COPm": "COP",
            "NGNm": "NGN",
            "GHSm": "GHS",
            "XOFm": "XOF",
            "ZARm": "ZAR",
            "AUDm": "AUD",
            "CHFm": "CHF",
            "CADm": "CAD",
            "PHPm": "PHP",
            "JPYm": "JPY",
            # Bridged stables
            "axlUSDC": "USD",
            "USDC": "USD",
            "USDT": "USD",
            # Native token
            "CELO": "USD"  # CELO priced in USD
        }
        return mapping.get(stablecoin, stablecoin.replace("c", "").replace("m", ""))
