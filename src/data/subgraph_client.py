"""
Uniswap V3 Subgraph Client for Celo.
Falls back to direct RPC calls if subgraph is unavailable.
"""
import time
from functools import lru_cache
from typing import Dict, List, Optional, Any

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential
from web3 import Web3

from config import config, POOL_ADDRESSES, TOKEN_ADDRESSES
from logger import logger

# Minimal Uniswap V3 Pool ABI for RPC calls
UNISWAP_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "fee",
        "outputs": [{"name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# ERC20 ABI for token info
ERC20_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    }
]


class SubgraphClient:
    """Client for querying Uniswap V3 subgraph on Celo with RPC fallback."""
    
    def __init__(self):
        self.endpoint = config.graph.endpoint
        self.api_key = config.graph.api_key
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Initialize Web3 for RPC fallback
        self.w3 = Web3(Web3.HTTPProvider(config.celo.rpc_url))
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True
    )
    async def _query(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """Execute a GraphQL query with retry logic."""
        if not self.endpoint:
            raise ValueError("No subgraph endpoint configured")
            
        session = await self._get_session()
        
        payload = {
            "query": query,
            "variables": variables or {}
        }
        
        headers = {
            "Content-Type": "application/json",
        }
        
        try:
            async with session.post(self.endpoint, json=payload, headers=headers) as response:
                if response.status == 429:
                    logger.warning("Rate limited by subgraph, backing off...")
                    raise aiohttp.ClientError("Rate limited")
                
                response.raise_for_status()
                data = await response.json()
                
                if "errors" in data:
                    raise ValueError(f"GraphQL errors: {data['errors']}")
                
                return data.get("data", {})
        except aiohttp.ClientError as e:
            logger.error(f"Subgraph query failed: {e}")
            raise
    
    async def get_pool_liquidity(self, pool_address: str) -> Dict[str, Any]:
        """
        Get pool liquidity data from subgraph or RPC fallback.
        
        Returns:
            Dict with liquidity, sqrtPriceX96, tick, and other pool data
        """
        # Try subgraph first if available
        if self.endpoint:
            try:
                return await self._get_pool_from_subgraph(pool_address)
            except Exception as e:
                logger.warning(f"Subgraph failed for pool {pool_address}: {e}")
        
        # Fall back to RPC
        logger.info(f"Using RPC fallback for pool {pool_address}")
        return await self._get_pool_from_rpc(pool_address)
    
    async def _get_pool_from_subgraph(self, pool_address: str) -> Dict[str, Any]:
        """Get pool data from subgraph."""
        query = """
        query getPool($poolAddress: ID!) {
            pool(id: $poolAddress) {
                id
                liquidity
                sqrtPriceX96
                tick
                token0 {
                    id
                    symbol
                    decimals
                }
                token1 {
                    id
                    symbol
                    decimals
                }
                feeTier
                volumeUSD
                txCount
            }
        }
        """
        
        result = await self._query(query, {"poolAddress": pool_address.lower()})
        pool = result.get("pool")
        
        if not pool:
            raise ValueError(f"Pool {pool_address} not found in subgraph")
        
        return {
            "liquidity": int(pool["liquidity"]),
            "sqrtPriceX96": pool["sqrtPriceX96"],
            "tick": int(pool["tick"]),
            "token0": pool["token0"],
            "token1": pool["token1"],
            "fee_tier": int(pool["feeTier"]),
            "volume_usd": float(pool["volumeUSD"]),
            "tx_count": int(pool["txCount"])
        }
    
    async def _get_pool_from_rpc(self, pool_address: str) -> Dict[str, Any]:
        """Get pool data directly from RPC."""
        try:
            pool_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(pool_address),
                abi=UNISWAP_POOL_ABI
            )
            
            # Get slot0 (contains sqrtPriceX96, tick, etc.)
            slot0 = pool_contract.functions.slot0().call()
            sqrt_price_x96 = slot0[0]
            tick = slot0[1]
            
            # Get liquidity
            liquidity = pool_contract.functions.liquidity().call()
            
            # Get token addresses
            token0_addr = pool_contract.functions.token0().call()
            token1_addr = pool_contract.functions.token1().call()
            fee = pool_contract.functions.fee().call()
            
            # Get token info
            token0_info = self._get_token_info(token0_addr)
            token1_info = self._get_token_info(token1_addr)
            
            return {
                "liquidity": liquidity,
                "sqrtPriceX96": str(sqrt_price_x96),
                "tick": tick,
                "token0": {
                    "id": token0_addr,
                    "symbol": token0_info["symbol"],
                    "decimals": token0_info["decimals"]
                },
                "token1": {
                    "id": token1_addr,
                    "symbol": token1_info["symbol"],
                    "decimals": token1_info["decimals"]
                },
                "fee_tier": fee,
                "volume_usd": 0,  # Not available via RPC
                "tx_count": 0  # Not available via RPC
            }
            
        except Exception as e:
            logger.error(f"RPC fallback failed for pool {pool_address}: {e}")
            raise
    
    def _get_token_info(self, token_address: str) -> Dict[str, Any]:
        """Get token info from cache or RPC."""
        # Check if it's a known token
        token_map = {v["address"].lower(): k for k, v in TOKEN_ADDRESSES.items()}
        symbol = token_map.get(token_address.lower())
        
        if symbol:
            return {
                "symbol": symbol,
                "decimals": TOKEN_ADDRESSES[symbol]["decimals"]
            }
        
        # Unknown token - query via RPC
        try:
            token_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            symbol = token_contract.functions.symbol().call()
            decimals = token_contract.functions.decimals().call()
            return {"symbol": symbol, "decimals": decimals}
        except Exception as e:
            logger.warning(f"Could not get token info for {token_address}: {e}")
            return {"symbol": "UNKNOWN", "decimals": 18}
    
    async def get_swap_volume_24h(self, pool_address: str) -> Dict[str, Any]:
        """
        Get 24-hour swap volume for a pool.
        Note: This requires subgraph, RPC cannot provide historical data.
        """
        if not self.endpoint:
            return {"volume_usd_24h": 0, "tx_count_24h": 0}
        
        try:
            # Get volume from pool data (cumulative)
            query = """
            query getPoolVolume($poolAddress: ID!, $timestamp: Int!) {
                pool(id: $poolAddress) {
                    volumeUSD
                    txCount
                }
                swaps(
                    where: { pool: $poolAddress, timestamp_gt: $timestamp }
                    orderBy: timestamp
                    orderDirection: desc
                    first: 1000
                ) {
                    amountUSD
                    timestamp
                }
            }
            """
            
            one_day_ago = int(time.time()) - 86400
            result = await self._query(query, {
                "poolAddress": pool_address.lower(),
                "timestamp": one_day_ago
            })
            
            swaps = result.get("swaps", [])
            volume_24h = sum(float(swap["amountUSD"]) for swap in swaps)
            
            return {
                "volume_usd_24h": volume_24h,
                "tx_count_24h": len(swaps)
            }
        except Exception as e:
            logger.warning(f"Could not get 24h volume from subgraph: {e}")
            return {"volume_usd_24h": 0, "tx_count_24h": 0}
    
    async def get_historical_rates(
        self, 
        token_in: str, 
        token_out: str, 
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get historical swap rates for trend analysis.
        Note: Requires subgraph, RPC cannot provide historical data.
        """
        if not self.endpoint:
            return []
        
        try:
            timestamp_threshold = int(time.time()) - (hours * 3600)
            
            query = """
            query getHistoricalRates($tokenIn: String!, $tokenOut: String!, $timestamp: Int!) {
                swaps(
                    where: {
                        timestamp_gt: $timestamp,
                        or: [
                            { token0: { symbol: $tokenIn }, token1: { symbol: $tokenOut } },
                            { token0: { symbol: $tokenOut }, token1: { symbol: $tokenIn } }
                        ]
                    }
                    orderBy: timestamp
                    orderDirection: asc
                    first: 1000
                ) {
                    timestamp
                    sqrtPriceX96
                    amount0
                    amount1
                    token0 {
                        symbol
                        decimals
                    }
                    token1 {
                        symbol
                        decimals
                    }
                }
            }
            """
            
            result = await self._query(query, {
                "tokenIn": token_in,
                "tokenOut": token_out,
                "timestamp": timestamp_threshold
            })
            
            swaps = result.get("swaps", [])
            rates = []
            
            for swap in swaps:
                rates.append({
                    "timestamp": int(swap["timestamp"]),
                    "sqrt_price_x96": swap["sqrtPriceX96"],
                    "token0": swap["token0"]["symbol"],
                    "token1": swap["token1"]["symbol"]
                })
            
            return rates
        except Exception as e:
            logger.warning(f"Could not get historical rates: {e}")
            return []
    
    def get_pool_address(self, token_a: str, token_b: str, fee_tier: str = "0.05") -> Optional[str]:
        """
        Get pool address for a token pair.
        
        Args:
            token_a: First token symbol
            token_b: Second token symbol
            fee_tier: Fee tier (0.05, 0.3, or 1)
            
        Returns:
            Pool address or None if not found
        """
        # Try both orderings
        key1 = f"{token_a}-{token_b}-{fee_tier}"
        key2 = f"{token_b}-{token_a}-{fee_tier}"
        
        return POOL_ADDRESSES.get(key1) or POOL_ADDRESSES.get(key2)
    
    async def calculate_price_from_sqrt_price_x96(
        self, 
        sqrt_price_x96: str, 
        token0_decimals: int, 
        token1_decimals: int
    ) -> float:
        """
        Calculate price from Uniswap V3 sqrtPriceX96.
        
        Args:
            sqrt_price_x96: sqrt(price) * 2^96 as string
            token0_decimals: Decimals of token0
            token1_decimals: Decimals of token1
            
        Returns:
            Price of token1 in terms of token0
        """
        sqrt_price = int(sqrt_price_x96)
        price = (sqrt_price ** 2) / (2 ** 192)
        
        # Adjust for decimals
        decimal_adjustment = 10 ** (token0_decimals - token1_decimals)
        price = price * decimal_adjustment
        
        return price
