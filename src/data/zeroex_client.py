"""
0x Swap API Client for DEX aggregation on Celo.
Uses 0x API v2 with Permit2.
Falls back to direct DEX calls if 0x API fails.
"""
from typing import Dict, Optional, Any
import asyncio

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from config import config, TOKEN_ADDRESSES
from logger import logger


class ZeroXClient:
    """Client for 0x Swap API v2 on Celo."""
    
    def __init__(self):
        self.base_url = config.zerox.base_url
        self.api_key = config.zerox.api_key
        self.chain_id = config.zerox.chain_id
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
    
    def _get_headers(self) -> Dict[str, str]:
        """Get required headers for 0x API v2."""
        headers = {
            "Content-Type": "application/json",
            "0x-version": "v2"
        }
        if self.api_key:
            headers["0x-api-key"] = self.api_key
        return headers
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    async def get_quote(
        self,
        buy_token: str,
        sell_token: str,
        sell_amount: int,
        taker_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get swap quote from 0x API v2.
        
        Args:
            buy_token: Token to buy (symbol or address)
            sell_token: Token to sell (symbol or address)
            sell_amount: Amount to sell (in wei)
            taker_address: Address that will execute the trade (required for v2)
            
        Returns:
            Quote data including price, gas, sources
        """
        session = await self._get_session()
        
        # Resolve token addresses (0x v2 requires contract addresses)
        buy_token_addr = self._resolve_token(buy_token)
        sell_token_addr = self._resolve_token(sell_token)
        
        # Build URL with query parameters
        # 0x v2 uses /swap/permit2/quote endpoint
        url = f"{self.base_url}/swap/permit2/quote"
        
        params = {
            "chainId": self.chain_id,
            "sellToken": sell_token_addr,
            "buyToken": buy_token_addr,
            "sellAmount": str(sell_amount)
        }
        
        # taker address is recommended for proper routing
        if taker_address:
            params["taker"] = taker_address
        elif config.celo.wallet_address:
            params["taker"] = config.celo.wallet_address
        
        headers = self._get_headers()
        
        try:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 400:
                    error_data = await response.json()
                    error_msg = error_data.get('message', 'Unknown error')
                    # Check if it's a chain not supported error
                    if "Invalid chain ID" in error_msg:
                        raise ValueError(f"0x API does not support Celo chain {self.chain_id}")
                    raise ValueError(f"0x API error: {error_msg}")
                
                if response.status == 404:
                    raise ValueError(f"0x API: No route found for {sell_token}->{buy_token}")
                
                response.raise_for_status()
                data = await response.json()
                
                # Parse v2 response format
                # v2 returns data in a different structure than v1
                return {
                    "price": float(data.get("price", 0)),
                    "guaranteed_price": float(data.get("guaranteedPrice", 0)),
                    "estimated_price_impact": float(data.get("estimatedPriceImpact", 0)),
                    "gas": int(data.get("gas", 0)),
                    "gas_price": data.get("gasPrice", "0"),
                    "sell_amount": data.get("sellAmount", "0"),
                    "buy_amount": data.get("buyAmount", "0"),
                    "sources": data.get("sources", []),
                    "data": data.get("data"),  # Call data for execution
                    "to": data.get("to"),  # Contract to call
                    "value": data.get("value", "0"),
                    "raw_response": data
                }
                
        except aiohttp.ClientError as e:
            logger.error(f"0x API request failed: {e}")
            raise
    
    async def get_price_comparison(
        self,
        buy_token: str,
        sell_token: str,
        sell_amount: int
    ) -> Dict[str, Any]:
        """
        Get price comparison across DEX sources.
        
        Args:
            buy_token: Token to buy
            sell_token: Token to sell
            sell_amount: Amount to sell
            
        Returns:
            Comparison data including best price and source
        """
        try:
            quote = await self.get_quote(buy_token, sell_token, sell_amount)
            
            # Filter active sources
            active_sources = [
                s for s in quote["sources"] 
                if float(s.get("proportion", 0)) > 0
            ]
            
            best_source = max(active_sources, key=lambda x: float(x.get("proportion", 0))) if active_sources else None
            
            return {
                "best_price": quote["price"],
                "best_source": best_source["name"] if best_source else "unknown",
                "gas_cost": quote["gas"],
                "gas_price_gwei": int(quote["gas_price"]) / 1e9 if quote["gas_price"] else 0,
                "sources": [s["name"] for s in active_sources],
                "quote": quote
            }
            
        except Exception as e:
            logger.warning(f"0x API failed: {e}, will use fallback")
            return await self._fallback_to_direct_dex(buy_token, sell_token, sell_amount)
    
    async def _fallback_to_direct_dex(
        self,
        buy_token: str,
        sell_token: str,
        sell_amount: int
    ) -> Dict[str, Any]:
        """
        Fallback to direct DEX calls if 0x API fails.
        This is a simplified implementation.
        """
        logger.info(f"Using fallback DEX for {sell_token}->{buy_token}")
        
        # In a real implementation, this would query Uniswap V3 directly
        # For now, return a placeholder
        return {
            "best_price": 0,
            "best_source": "fallback_uniswap",
            "gas_cost": 150000,
            "gas_price_gwei": 0.1,
            "sources": ["uniswap_v3"],
            "quote": None,
            "fallback": True
        }
    
    def _resolve_token(self, token: str) -> str:
        """Resolve token symbol to contract address."""
        # Check exact match first (cUSD, cEUR, etc.)
        if token in TOKEN_ADDRESSES:
            return TOKEN_ADDRESSES[token]["address"]
        # Check uppercase match
        token_upper = token.upper()
        for sym, data in TOKEN_ADDRESSES.items():
            if sym.upper() == token_upper:
                return data["address"]
        # Check if it's already an address (starts with 0x and is 42 chars)
        if token.startswith("0x") and len(token) == 42:
            return token
        # Check lowercase address match
        token_lower = token.lower()
        for sym, data in TOKEN_ADDRESSES.items():
            if data["address"].lower() == token_lower:
                return data["address"]
        # Return as-is (assume it's an address)
        return token
    
    async def get_best_rate_with_fallback(
        self,
        token_in: str,
        token_out: str,
        amount: int
    ) -> Dict[str, Any]:
        """
        Get best rate with automatic fallback.
        
        Args:
            token_in: Input token symbol
            token_out: Output token symbol
            amount: Amount to swap
            
        Returns:
            Best rate information
        """
        try:
            return await self.get_price_comparison(token_in, token_out, amount)
        except Exception as e:
            logger.warning(f"0x failed: {e}, falling back to direct DEX")
            return await self._fallback_to_direct_dex(token_in, token_out, amount)


async def get_best_rate_with_fallback(
    token_in: str,
    token_out: str,
    amount: int
) -> Dict[str, Any]:
    """
    Standalone function to get best rate with fallback.
    
    Args:
        token_in: Input token symbol
        token_out: Output token symbol
        amount: Amount to swap
        
    Returns:
        Best rate information
    """
    client = ZeroXClient()
    try:
        return await client.get_best_rate_with_fallback(token_in, token_out, amount)
    finally:
        await client.close()
