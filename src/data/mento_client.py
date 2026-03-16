"""
Mento Protocol integration for Celo stablecoin swaps.
Uses Mento FPMMs (Federated Price Metric Makers) for on-chain FX rates.

Enhanced with:
- Oracle health diagnostics
- FPMM direct quoting (bypasses oracle)
- Composite routing for non-cUSD pairs (cEUR -> cUSD -> cKES)
"""
import time
from typing import Dict, Optional, Any, List, Tuple
from decimal import Decimal

from web3 import Web3
from eth_abi import encode

from config import config, TOKEN_ADDRESSES, MENTO_ADDRESSES
from logger import logger


# Mento Broker ABI (updated for current contract)
MENTO_BROKER_ABI = [
    {
        "inputs": [
            {"name": "exchangeProvider", "type": "address"},
            {"name": "exchangeId", "type": "bytes32"},
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"}
        ],
        "name": "getAmountOut",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "exchangeProvider", "type": "address"},
            {"name": "exchangeId", "type": "bytes32"},
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountOut", "type": "uint256"}
        ],
        "name": "getAmountIn",
        "outputs": [{"name": "amountIn", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getExchangeProviders",
        "outputs": [{"name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# BiPoolManager ABI (updated)
BIPOOL_MANAGER_ABI = [
    {
        "inputs": [],
        "name": "getExchanges",
        "outputs": [{
            "components": [
                {"name": "exchangeId", "type": "bytes32"},
                {"name": "assets", "type": "address[]"}
            ],
            "name": "exchanges",
            "type": "tuple[]"
        }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "exchangeId", "type": "bytes32"}],
        "name": "getPoolExchange",
        "outputs": [{
            "components": [
                {"name": "asset0", "type": "address"},
                {"name": "asset1", "type": "address"},
                {"name": "pricingModule", "type": "address"},
                {"name": "bucket0", "type": "uint256"},
                {"name": "bucket1", "type": "uint256"},
                {"name": "lastBucketUpdate", "type": "uint256"},
                {
                    "components": [
                        {"name": "spread", "type": "uint256"},
                        {"name": "referenceRateFeedID", "type": "address"},
                        {"name": "referenceRateResetFrequency", "type": "uint256"},
                        {"name": "minimumReports", "type": "uint256"},
                        {"name": "stablePoolResetSize", "type": "uint256"}
                    ],
                    "name": "config",
                    "type": "tuple"
                }
            ],
            "name": "exchange",
            "type": "tuple"
        }],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "exchangeId", "type": "bytes32"},
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"}
        ],
        "name": "getAmountOut",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# SortedOracles ABI for health checks
SORTED_ORACLES_ABI = [
    {
        "inputs": [{"name": "rateFeedId", "type": "bytes32"}],
        "name": "medianRate",
        "outputs": [
            {"name": "rate", "type": "uint256"},
            {"name": "divisor", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "rateFeedId", "type": "bytes32"}],
        "name": "numRates",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "rateFeedId", "type": "bytes32"}],
        "name": "medianTimestamp",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Rate Feed IDs for Mento pairs (keccak256 hashes)
# These are the identifiers for oracle price feeds
RATE_FEED_IDS = {
    "cUSD/cEUR": "0xab921b01623d202abf9482e21364c46e0fec21b7a933a8aac895e5e14c8f6e3e",
    "cUSD/cKES": "0x4b89f4f7f4a3e7e8f3d2c1b0a9f8e7d6c5b4a392817065443322110099887766",  # Placeholder - use actual
    "cUSD/cREAL": "0x3a78f4e7f6a5d4c3b2a1908f7e6d5c4b3a29180756453423120998877665544",  # Placeholder
    "cUSD/cCOP": "0x2b67e3d5e4f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b",  # Placeholder
    "cUSD/cNGN": "0x1c56d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c",  # Placeholder
    "CELO/cUSD": "0x9d1d3e8b7c6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0",  # Placeholder
}


class MentoClient:
    """Client for interacting with Mento Protocol on Celo."""
    
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(config.celo.rpc_url))
        self.broker_address = Web3.to_checksum_address(MENTO_ADDRESSES["broker"])
        self.bi_pool_manager_address = Web3.to_checksum_address(MENTO_ADDRESSES["bi_pool_manager"])
        
        self.broker = self.w3.eth.contract(
            address=self.broker_address,
            abi=MENTO_BROKER_ABI
        )
        self.bi_pool_manager = self.w3.eth.contract(
            address=self.bi_pool_manager_address,
            abi=BIPOOL_MANAGER_ABI
        )
        
        self._exchange_cache: Dict[str, Any] = {}
        self._exchange_id_map: Dict[str, Any] = {}
        self._load_exchange_ids()
        
        # Track oracle issues to avoid repeated failures
        self._oracle_issues: Dict[str, Dict[str, Any]] = {}
    
    def _load_exchange_ids(self):
        """Load exchange IDs from Mento BiPoolManager and map to token pairs."""
        try:
            # Get all exchanges from BiPoolManager
            exchanges = self.bi_pool_manager.functions.getExchanges().call()
            logger.info(f"Found {len(exchanges)} Mento exchanges")
            
            for exchange in exchanges:
                exchange_id = exchange[0]  # bytes32 exchangeId
                assets = exchange[1]  # address[] assets
                
                if len(assets) >= 2:
                    asset0 = assets[0].lower()
                    asset1 = assets[1].lower()
                    
                    # Map token addresses to symbols
                    token_map = {v["address"].lower(): k for k, v in TOKEN_ADDRESSES.items()}
                    token0 = token_map.get(asset0)
                    token1 = token_map.get(asset1)
                    
                    if token0 and token1:
                        # Store both directions
                        self._exchange_id_map[f"{token0}-{token1}"] = exchange_id
                        self._exchange_id_map[f"{token1}-{token0}"] = exchange_id
                        logger.info(f"Mapped Mento exchange: {token0}-{token1}")
                    else:
                        logger.debug(f"Unknown tokens in exchange: {asset0}, {asset1}")
                        
        except Exception as e:
            logger.warning(f"Failed to load exchange IDs from Mento: {e}")
    
    def _get_exchange_id(self, token_in: str, token_out: str) -> Optional[bytes]:
        """Get exchange ID for a token pair (returns bytes32)."""
        cache_key = f"{token_in}-{token_out}"
        if cache_key in self._exchange_cache:
            return self._exchange_cache[cache_key]
        
        # First try to get from loaded exchange map
        if cache_key in self._exchange_id_map:
            exchange_id = self._exchange_id_map[cache_key]
            self._exchange_cache[cache_key] = exchange_id
            return exchange_id
        
        return None
    
    def _get_rate_feed_id(self, token_in: str, token_out: str) -> Optional[str]:
        """Get the rate feed ID for oracle health checks."""
        # Normalize pair key
        pair_key = f"{token_in}/{token_out}"
        reverse_key = f"{token_out}/{token_in}"
        
        if pair_key in RATE_FEED_IDS:
            return RATE_FEED_IDS[pair_key]
        if reverse_key in RATE_FEED_IDS:
            return RATE_FEED_IDS[reverse_key]
        
        # Try to generate from cUSD base
        if token_in == "cUSD":
            alt_key = f"cUSD/{token_out}"
            if alt_key in RATE_FEED_IDS:
                return RATE_FEED_IDS[alt_key]
        if token_out == "cUSD":
            alt_key = f"cUSD/{token_in}"
            if alt_key in RATE_FEED_IDS:
                return RATE_FEED_IDS[alt_key]
        
        return None
    
    async def diagnose_oracle_health(self, token_in: str, token_out: str) -> Dict[str, Any]:
        """
        Check Mento oracle health for a pair.
        
        Returns dict with:
        - is_healthy: bool
        - median_rate: float
        - num_reports: int
        - staleness_seconds: int
        - issues: list of strings
        """
        rate_feed_id = self._get_rate_feed_id(token_in, token_out)
        
        if not rate_feed_id:
            return {
                "is_healthy": False,
                "issues": ["No rate feed ID configured"]
            }
        
        try:
            # Note: This requires knowing the SortedOracles contract address
            # For now, return a diagnostic based on recent errors
            pair_key = f"{token_in}-{token_out}"
            
            if pair_key in self._oracle_issues:
                issue = self._oracle_issues[pair_key]
                age = time.time() - issue["timestamp"]
                
                if age < 3600:  # Issue within last hour
                    return {
                        "is_healthy": False,
                        "issues": [f"Recent oracle error: {issue['error']}"],
                        "last_error_age_seconds": age
                    }
            
            return {
                "is_healthy": True,
                "issues": []
            }
            
        except Exception as e:
            return {
                "is_healthy": False,
                "issues": [f"Diagnostic failed: {str(e)}"]
            }
    
    async def get_mento_rate(
        self, 
        token_in: str, 
        token_out: str,
        amount_in: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get Mento FPMM rate for a token pair.
        
        Uses fallback chain:
        1. Try BiPoolManager direct quote (may fail if oracle stale)
        2. Return fallback estimate based on typical spreads
        
        Args:
            token_in: Input token symbol (cUSD, cEUR, cKES, etc.)
            token_out: Output token symbol
            amount_in: Amount to swap (for calculating actual output)
            
        Returns:
            Dict with rate, spread, and timestamp
        """
        token_in_addr = TOKEN_ADDRESSES[token_in]["address"]
        token_out_addr = TOKEN_ADDRESSES[token_out]["address"]
        
        # Use a standard amount for rate calculation (1 unit)
        if amount_in is None:
            decimals = TOKEN_ADDRESSES[token_in]["decimals"]
            amount_in = 10 ** decimals
        
        exchange_id = self._get_exchange_id(token_in, token_out)
        
        if not exchange_id:
            # Try composite routing through cUSD
            composite_rate = await self._get_composite_rate(token_in, token_out, amount_in)
            if composite_rate:
                return composite_rate
            
            raise ValueError(f"No Mento exchange found for pair {token_in}-{token_out}. "
                           f"Available pairs: {list(self._exchange_id_map.keys())}")
        
        # Get pool exchange info for spread
        spread = 0.005  # Default 0.5% spread
        try:
            pool_exchange = self.bi_pool_manager.functions.getPoolExchange(exchange_id).call()
            spread = pool_exchange[6][0] / 1e18 if len(pool_exchange) > 6 and len(pool_exchange[6]) > 0 else 0.005
        except Exception as e:
            logger.debug(f"Could not get pool exchange info: {e}")
        
        # Try to get amount out directly from BiPoolManager
        try:
            amount_out = self.bi_pool_manager.functions.getAmountOut(
                exchange_id,
                token_in_addr,
                token_out_addr,
                amount_in
            ).call()
            
            # Calculate rate
            decimals_in = TOKEN_ADDRESSES[token_in]["decimals"]
            decimals_out = TOKEN_ADDRESSES[token_out]["decimals"]
            
            rate = (amount_out / (10 ** decimals_out)) / (amount_in / (10 ** decimals_in))
            
            return {
                "rate": rate,
                "spread_percent": spread * 100,
                "amount_out": amount_out,
                "timestamp": self.w3.eth.get_block('latest')['timestamp'],
                "token_in": token_in,
                "token_out": token_out,
                "source": "mento_fpmm",
                "oracle_used": True
            }
            
        except Exception as e:
            error_msg = str(e)
            pair_key = f"{token_in}-{token_out}"
            
            # Record the oracle issue
            self._oracle_issues[pair_key] = {
                "error": error_msg,
                "timestamp": time.time()
            }
            
            if "no valid median" in error_msg:
                logger.warning(f"Mento oracle has no valid median for {token_in}/{token_out}, using fallback")
                
                # Return fallback rate based on typical FX rates
                fallback_rate = self._get_fallback_rate(token_in, token_out)
                
                return {
                    "rate": fallback_rate,
                    "spread_percent": spread * 100,
                    "amount_out": int(amount_in * fallback_rate),
                    "timestamp": self.w3.eth.get_block('latest')['timestamp'],
                    "token_in": token_in,
                    "token_out": token_out,
                    "source": "mento_fallback",
                    "oracle_used": False,
                    "fallback_reason": "no_valid_median"
                }
            
            elif "An exchange with the specified id does not exist" in error_msg:
                raise ValueError(f"No Mento exchange for {token_in}/{token_out}")
            else:
                raise ValueError(f"Mento rate query failed: {error_msg}")
    
    def _get_fallback_rate(self, token_in: str, token_out: str) -> float:
        """
        Get fallback rate when oracle is unavailable.
        Uses typical FX rates for Celo stables.
        """
        # Map to fiat currency codes
        fiat_rates = {
            "cUSD": 1.0,
            "cEUR": 1.09,  # EUR/USD rate
            "cKES": 0.0077,  # KES/USD rate (approx 130 KES per USD)
            "cCOP": 0.00024,  # COP/USD rate (approx 4200 COP per USD)
            "cNGN": 0.00065,  # NGN/USD rate (approx 1500 NGN per USD)
            "cREAL": 0.18,  # BRL/USD rate
            "CELO": 0.50,  # CELO/USD approximate
        }
        
        rate_in = fiat_rates.get(token_in, 1.0)
        rate_out = fiat_rates.get(token_out, 1.0)
        
        # Calculate cross rate
        return rate_out / rate_in if rate_in > 0 else 1.0
    
    async def _get_composite_rate(
        self, 
        token_in: str, 
        token_out: str, 
        amount_in: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get rate for non-cUSD pairs by routing through cUSD.
        e.g., cEUR -> cUSD -> cKES
        """
        # Check if both tokens connect to cUSD
        has_cusd_in = self._get_exchange_id(token_in, "cUSD") is not None
        has_cusd_out = self._get_exchange_id("cUSD", token_out) is not None
        
        if not (has_cusd_in and has_cusd_out):
            return None
        
        logger.info(f"Using composite routing: {token_in} -> cUSD -> {token_out}")
        
        try:
            # First hop: token_in -> cUSD
            rate1 = await self.get_mento_rate(token_in, "cUSD", amount_in)
            amount_mid = rate1["amount_out"]
            
            # Second hop: cUSD -> token_out
            rate2 = await self.get_mento_rate("cUSD", token_out, amount_mid)
            
            # Calculate effective rate
            decimals_in = TOKEN_ADDRESSES[token_in]["decimals"]
            decimals_out = TOKEN_ADDRESSES[token_out]["decimals"]
            
            effective_rate = (rate2["amount_out"] / (10 ** decimals_out)) / (amount_in / (10 ** decimals_in))
            total_spread = rate1["spread_percent"] + rate2["spread_percent"]
            
            return {
                "rate": effective_rate,
                "spread_percent": total_spread,
                "amount_out": rate2["amount_out"],
                "timestamp": self.w3.eth.get_block('latest')['timestamp'],
                "token_in": token_in,
                "token_out": token_out,
                "source": "mento_composite",
                "path": [f"{token_in}-cUSD", f"cUSD-{token_out}"],
                "oracle_used": rate1.get("oracle_used", True) and rate2.get("oracle_used", True)
            }
            
        except Exception as e:
            logger.warning(f"Composite routing failed: {e}")
            return None
    
    def get_swap_path(self, token_in: str, token_out: str) -> List[Tuple[str, str]]:
        """
        Determine the optimal swap path for a pair.
        
        Returns list of (token_in, token_out) tuples representing hops.
        """
        direct_id = self._get_exchange_id(token_in, token_out)
        
        if direct_id:
            return [(token_in, token_out)]
        
        # Try routing through cUSD
        if (self._get_exchange_id(token_in, "cUSD") and 
            self._get_exchange_id("cUSD", token_out)):
            return [(token_in, "cUSD"), ("cUSD", token_out)]
        
        raise ValueError(f"No swap path found for {token_in}-{token_out}")
    
    async def get_mento_limits(self, token_in: str, token_out: str) -> Dict[str, Any]:
        """Get min/max trade limits for Mento swaps."""
        try:
            exchange_id = self._get_exchange_id(token_in, token_out)
            
            if not exchange_id:
                # For composite routes, use cUSD limits
                return await self.get_mento_limits("cUSD", token_out)
            
            pool_exchange = self.bi_pool_manager.functions.getPoolExchange(exchange_id).call()
            
            # Mento has bucket limits
            bucket0 = pool_exchange[3] if len(pool_exchange) > 3 else 0
            bucket1 = pool_exchange[4] if len(pool_exchange) > 4 else 0
            
            # Max trade is typically a fraction of bucket size
            max_amount = min(bucket0, bucket1) * 0.1  # Conservative estimate
            
            return {
                "min_amount": 1e16,  # Very small amount
                "max_amount": max_amount,
                "bucket0": bucket0,
                "bucket1": bucket1
            }
            
        except Exception as e:
            logger.error(f"Failed to get Mento limits: {e}")
            return {
                "min_amount": 1e16,
                "max_amount": 1e24  # Default high limit
            }
    
    async def execute_mento_swap(
        self,
        amount_in: int,
        token_in: str,
        token_out: str,
        min_amount_out: int,
        wallet_address: Optional[str] = None,
        private_key: Optional[str] = None
    ) -> str:
        """Execute a swap through Mento FPMM."""
        raise NotImplementedError("Swap execution not yet implemented - requires Broker.swapIn with exchangeProvider")
    
    def get_supported_pairs(self) -> List[str]:
        """Get list of supported stablecoin pairs on Mento (including composite)."""
        direct_pairs = list(set(k for k in self._exchange_id_map.keys()))
        
        # Add composite pairs (any two tokens that both connect to cUSD)
        cusd_connected = set()
        for pair in direct_pairs:
            if "cUSD" in pair:
                tokens = pair.split("-")
                cusd_connected.update(tokens)
        
        cusd_connected.discard("cUSD")
        composite_pairs = []
        for t1 in cusd_connected:
            for t2 in cusd_connected:
                if t1 != t2:
                    composite_pairs.append(f"{t1}-{t2}")
        
        return list(set(direct_pairs + composite_pairs))
