"""
Pre-trade simulation module for RemitAgent.
Uses eth_call (static calls) to simulate trades without spending gas.
"""
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from decimal import Decimal

from web3 import Web3
from eth_abi import encode

from config import config, TOKEN_ADDRESSES, MENTO_ADDRESSES
from logger import logger


@dataclass
class SimulationResult:
    """Result of a trade simulation."""
    success: bool
    amount_out: float
    amount_out_wei: int
    fee_cost: float
    gas_cost_eth: float
    gas_cost_usd: float
    net_profit_usd: float
    profit_percent: float
    price_impact: float
    exchange_provider: str
    error_message: Optional[str] = None
    timestamp: float = 0
    is_composite: bool = False  # True if this is a multi-hop swap
    hops: Optional[list] = None  # List of individual hop results for composite swaps


# Minimal Broker ABI for simulation
BROKER_ABI = [
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
        "inputs": [
            {"name": "exchangeProvider", "type": "address"},
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"}
        ],
        "name": "swapIn",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
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

# BiPoolManager ABI for getting exchange providers
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
    }
]


class MentoSimulator:
    """
    Simulates Mento trades using static calls (eth_call).
    No gas is spent, no state is changed.
    """
    
    def __init__(self, web3: Optional[Web3] = None):
        self.w3 = web3 or Web3(Web3.HTTPProvider(config.celo.rpc_url))
        self.broker_address = Web3.to_checksum_address(MENTO_ADDRESSES["broker"])
        self.bi_pool_manager_address = Web3.to_checksum_address(MENTO_ADDRESSES["bi_pool_manager"])
        
        self.broker = self.w3.eth.contract(
            address=self.broker_address,
            abi=BROKER_ABI
        )
        self.bi_pool_manager = self.w3.eth.contract(
            address=self.bi_pool_manager_address,
            abi=BIPOOL_MANAGER_ABI
        )
        
        # Configuration
        self.gas_price_gwei = 0.1  # Celo: ~0.1 gwei
        self.cele_price_usd = 0.5  # CELO price in USD
        self.mento_fee_percent = 0.25  # 0.25% average Mento fee
        self.traditional_remit_fee = 0.05  # 5% traditional remittance
        
        # Simulation cache
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = 30  # 30 seconds
        
        # Exchange provider cache
        self._exchange_providers: Dict[str, str] = {}
        self._exchange_id_map: Dict[str, bytes] = {}
        
        # Load exchange IDs from BiPoolManager
        self._load_exchange_ids()
    
    def _load_exchange_ids(self):
        """Load exchange IDs from Mento BiPoolManager."""
        try:
            exchanges = self.bi_pool_manager.functions.getExchanges().call()
            logger.info(f"Simulator loaded {len(exchanges)} Mento exchanges")
            
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
                        logger.debug(f"Simulator mapped: {token0}-{token1}")
                        
        except Exception as e:
            logger.warning(f"Simulator failed to load exchange IDs: {e}")
    
    def _get_cache_key(self, pair: str, amount: float) -> str:
        """Generate cache key for simulation."""
        return f"{pair}:{amount}:{int(time.time() / self._cache_ttl)}"
    
    def _get_cached(self, key: str) -> Optional[SimulationResult]:
        """Get cached simulation if valid."""
        if key in self._cache:
            cached_time, result = self._cache[key]
            if time.time() - cached_time < self._cache_ttl:
                logger.debug(f"Using cached simulation for {key}")
                return result
        return None
    
    def _set_cached(self, key: str, result: SimulationResult):
        """Cache simulation result."""
        self._cache[key] = (time.time(), result)
    
    def get_exchange_provider(self, pair: str) -> str:
        """
        Get the exchange provider address for a pair.
        Mento uses BiPoolManager as the exchange provider.
        """
        if pair in self._exchange_providers:
            return self._exchange_providers[pair]
        
        # For Mento v2, the BiPoolManager is the exchange provider
        provider = self.bi_pool_manager_address
        self._exchange_providers[pair] = provider
        
        return provider
    
    async def simulate_swap(
        self,
        pair: str,
        amount_in: float,
        use_cache: bool = True
    ) -> SimulationResult:
        """
        Simulate a swap using eth_call (no transaction, no gas cost).
        
        Supports both direct Mento exchanges and composite routing (via cUSD).
        
        Args:
            pair: Trading pair (e.g., "cUSD-cEUR")
            amount_in: Input amount in token units
            use_cache: Whether to use cached results
            
        Returns:
            SimulationResult with expected outcomes
        """
        # Check cache
        if use_cache:
            cache_key = self._get_cache_key(pair, amount_in)
            cached = self._get_cached(cache_key)
            if cached:
                return cached
        
        try:
            # Parse pair
            token_in, token_out = pair.split("-")
            
            # Check for direct exchange first
            exchange_id = self._get_exchange_id(token_in, token_out)
            
            if exchange_id:
                # Use direct swap simulation
                result = await self._simulate_direct_swap(
                    pair, token_in, token_out, amount_in, exchange_id
                )
            elif self._has_composite_path(token_in, token_out):
                # Use composite routing through cUSD
                logger.info(f"Using composite routing for {pair} (via cUSD)")
                result = await self._simulate_composite_swap(token_in, token_out, amount_in)
            else:
                # No path available
                available = list(self._exchange_id_map.keys())
                raise ValueError(f"No exchange or composite path found for {pair}. "
                               f"Available direct pairs: {available}")
            
            # Cache result
            if use_cache and result.success:
                self._set_cached(self._get_cache_key(pair, amount_in), result)
            
            return result
            
        except Exception as e:
            logger.error(f"Simulation failed for {pair}: {e}")
            return SimulationResult(
                success=False,
                amount_out=0,
                amount_out_wei=0,
                fee_cost=0,
                gas_cost_eth=0,
                gas_cost_usd=0,
                net_profit_usd=0,
                profit_percent=0,
                price_impact=0,
                exchange_provider="",
                error_message=str(e),
                timestamp=time.time()
            )
    
    async def _simulate_direct_swap(
        self,
        pair: str,
        token_in: str,
        token_out: str,
        amount_in: float,
        exchange_id: bytes
    ) -> SimulationResult:
        """
        Simulate a direct single-hop swap.
        
        Args:
            pair: Trading pair string
            token_in: Input token symbol
            token_out: Output token symbol
            amount_in: Input amount in token units
            exchange_id: Mento exchange ID
            
        Returns:
            SimulationResult
        """
        token_in_addr = TOKEN_ADDRESSES[token_in]["address"]
        token_out_addr = TOKEN_ADDRESSES[token_out]["address"]
        
        # Convert amount to wei
        decimals_in = TOKEN_ADDRESSES[token_in]["decimals"]
        decimals_out = TOKEN_ADDRESSES[token_out]["decimals"]
        amount_in_wei = int(amount_in * (10 ** decimals_in))
        
        # Get exchange provider
        exchange_provider = self.get_exchange_provider(pair)
        
        try:
            # Simulate using getAmountOut (static call)
            amount_out_wei = self.broker.functions.getAmountOut(
                exchange_provider,
                exchange_id,
                token_in_addr,
                token_out_addr,
                amount_in_wei
            ).call()
            
            amount_out = amount_out_wei / (10 ** decimals_out)
            oracle_used = True
            fallback_reason = None
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Handle oracle stale/no valid median error
            if "no valid median" in error_msg or "stale" in error_msg:
                logger.warning(f"Mento oracle has no valid median for {pair}, using fallback rate")
                
                # Use fallback rate based on typical FX rates
                fallback_rate = self._get_fallback_rate(token_in, token_out)
                amount_out = amount_in * fallback_rate
                amount_out_wei = int(amount_out * (10 ** decimals_out))
                oracle_used = False
                fallback_reason = "no_valid_median"
            else:
                # Re-raise other errors
                raise
        
        # Estimate gas
        gas_estimate = await self._estimate_gas(
            exchange_provider, exchange_id, token_in_addr, token_out_addr, amount_in_wei
        )
        
        # Calculate costs
        gas_cost_eth = (gas_estimate * self.gas_price_gwei * 1e-9)
        gas_cost_usd = gas_cost_eth * self.cele_price_usd
        
        # Mento fee
        mento_fee = amount_in * (self.mento_fee_percent / 100)
        
        # Calculate profit vs traditional remittance
        traditional_cost = amount_in * self.traditional_remit_fee
        on_chain_cost = mento_fee + gas_cost_usd
        savings = traditional_cost - on_chain_cost
        profit_percent = (savings / amount_in) * 100 if amount_in > 0 else 0
        
        result = SimulationResult(
            success=True,
            amount_out=amount_out,
            amount_out_wei=amount_out_wei,
            fee_cost=mento_fee,
            gas_cost_eth=gas_cost_eth,
            gas_cost_usd=gas_cost_usd,
            net_profit_usd=savings,
            profit_percent=profit_percent,
            price_impact=0,
            exchange_provider=exchange_provider,
            error_message=None,
            timestamp=time.time()
        )
        
        # Store oracle status as attributes (for debugging)
        result.oracle_used = oracle_used if 'oracle_used' in dir() else True
        result.fallback_reason = fallback_reason if 'fallback_reason' in dir() else None
        
        return result
    
    def _get_fallback_rate(self, token_in: str, token_out: str) -> float:
        """
        Get fallback rate when oracle is unavailable.
        Uses typical FX rates for Celo stables.
        """
        # Map to fiat currency codes (USD-based rates)
        fiat_rates = {
            "cUSD": 1.0,
            "cEUR": 1.09,      # EUR/USD rate
            "cKES": 0.0077,    # KES/USD rate (approx 130 KES per USD)
            "cCOP": 0.00024,   # COP/USD rate (approx 4200 COP per USD)
            "cNGN": 0.00065,   # NGN/USD rate (approx 1500 NGN per USD)
            "cREAL": 0.18,     # BRL/USD rate
            "CELO": 0.50,      # CELO/USD approximate
        }
        
        rate_in = fiat_rates.get(token_in, 1.0)
        rate_out = fiat_rates.get(token_out, 1.0)
        
        # Calculate cross rate (how many token_out per token_in)
        # e.g., cUSD to cKES: 0.0077 / 1.0 = 0.0077 (but we want KES per USD = 130)
        # So: rate_out / rate_in = 0.0077 / 1.0 = wrong direction
        # Correct: (1/rate_out) / (1/rate_in) = rate_in / rate_out
        return rate_in / rate_out if rate_out > 0 else 1.0
    
    async def _estimate_gas(
        self,
        exchange_provider: str,
        exchange_id: bytes,
        token_in: str,
        token_out: str,
        amount_in: int
    ) -> int:
        """Estimate gas for a swap transaction."""
        try:
            # Try to estimate gas for swapIn
            # Note: This may fail if wallet doesn't have balance/allowance
            # Fall back to default in that case
            gas = self.broker.functions.swapIn(
                exchange_provider,
                token_in,
                token_out,
                amount_in,
                0  # minAmountOut = 0 for estimation
            ).estimate_gas({'from': config.celo.wallet_address})
            
            return int(gas * 1.2)  # 20% buffer
        except Exception as e:
            logger.debug(f"Gas estimation failed: {e}, using default")
            return 200000  # Default for Mento swaps
    
    def _get_exchange_id(self, token_in: str, token_out: str) -> Optional[bytes]:
        """Get exchange ID from token pair."""
        cache_key = f"{token_in}-{token_out}"
        
        # Try direct lookup
        if cache_key in self._exchange_id_map:
            return self._exchange_id_map[cache_key]
        
        # Log available pairs for debugging
        logger.debug(f"Direct exchange not found for {cache_key}")
        
        return None
    
    def _has_composite_path(self, token_in: str, token_out: str) -> bool:
        """Check if there's a composite path through cUSD."""
        # Check if both tokens can route through cUSD
        has_cusd_in = self._get_exchange_id(token_in, "cUSD") is not None
        has_cusd_out = self._get_exchange_id("cUSD", token_out) is not None
        return has_cusd_in and has_cusd_out
    
    async def _simulate_composite_swap(
        self,
        token_in: str,
        token_out: str,
        amount_in: float
    ) -> SimulationResult:
        """
        Simulate a composite swap through cUSD (e.g., cEUR -> cUSD -> cKES).
        
        Args:
            token_in: Input token symbol
            token_out: Output token symbol
            amount_in: Input amount in token units
            
        Returns:
            SimulationResult with combined outcomes
        """
        logger.info(f"Simulating composite swap: {token_in} -> cUSD -> {token_out}")
        
        try:
            # First hop: token_in -> cUSD
            hop1_result = await self._simulate_single_swap(f"{token_in}-cUSD", amount_in)
            if not hop1_result.success:
                raise ValueError(f"First hop failed: {hop1_result.error_message}")
            
            # Second hop: cUSD -> token_out
            hop2_result = await self._simulate_single_swap(f"cUSD-{token_out}", hop1_result.amount_out)
            if not hop2_result.success:
                raise ValueError(f"Second hop failed: {hop2_result.error_message}")
            
            # Calculate combined result
            decimals_in = TOKEN_ADDRESSES[token_in]["decimals"]
            decimals_out = TOKEN_ADDRESSES[token_out]["decimals"]
            
            # Effective rate
            amount_in_wei = int(amount_in * (10 ** decimals_in))
            effective_rate = hop2_result.amount_out_wei / amount_in_wei if amount_in_wei > 0 else 0
            
            # Combined costs
            total_gas_cost_eth = hop1_result.gas_cost_eth + hop2_result.gas_cost_eth
            total_gas_cost_usd = hop1_result.gas_cost_usd + hop2_result.gas_cost_usd
            total_fee = hop1_result.fee_cost + hop2_result.fee_cost
            
            # Calculate savings vs traditional remittance
            traditional_cost = amount_in * self.traditional_remit_fee
            on_chain_cost = total_fee + total_gas_cost_usd
            savings = traditional_cost - on_chain_cost
            profit_percent = (savings / amount_in) * 100 if amount_in > 0 else 0
            
            return SimulationResult(
                success=True,
                amount_out=hop2_result.amount_out,
                amount_out_wei=hop2_result.amount_out_wei,
                fee_cost=total_fee,
                gas_cost_eth=total_gas_cost_eth,
                gas_cost_usd=total_gas_cost_usd,
                net_profit_usd=savings,
                profit_percent=profit_percent,
                price_impact=0,  # Would need pool depth data
                exchange_provider=self.bi_pool_manager_address,
                error_message=None,
                timestamp=time.time(),
                is_composite=True,
                hops=[hop1_result, hop2_result]
            )
            
        except Exception as e:
            logger.error(f"Composite simulation failed for {token_in}-{token_out}: {e}")
            return SimulationResult(
                success=False,
                amount_out=0,
                amount_out_wei=0,
                fee_cost=0,
                gas_cost_eth=0,
                gas_cost_usd=0,
                net_profit_usd=0,
                profit_percent=0,
                price_impact=0,
                exchange_provider="",
                error_message=str(e),
                timestamp=time.time()
            )
    
    async def _simulate_single_swap(
        self,
        pair: str,
        amount_in: float
    ) -> SimulationResult:
        """
        Simulate a single-hop swap (internal helper).
        
        Args:
            pair: Trading pair (e.g., "cUSD-cEUR")
            amount_in: Input amount in token units
            
        Returns:
            SimulationResult
        """
        try:
            # Parse pair
            token_in, token_out = pair.split("-")
            token_in_addr = TOKEN_ADDRESSES[token_in]["address"]
            token_out_addr = TOKEN_ADDRESSES[token_out]["address"]
            
            # Convert amount to wei
            decimals_in = TOKEN_ADDRESSES[token_in]["decimals"]
            decimals_out = TOKEN_ADDRESSES[token_out]["decimals"]
            amount_in_wei = int(amount_in * (10 ** decimals_in))
            
            # Get exchange provider
            exchange_provider = self.get_exchange_provider(pair)
            
            # Get exchange ID from pair
            exchange_id = self._get_exchange_id(token_in, token_out)
            if not exchange_id:
                raise ValueError(f"No exchange found for {pair}")
            
            try:
                # Simulate using getAmountOut (static call)
                amount_out_wei = self.broker.functions.getAmountOut(
                    exchange_provider,
                    exchange_id,
                    token_in_addr,
                    token_out_addr,
                    amount_in_wei
                ).call()
                
                amount_out = amount_out_wei / (10 ** decimals_out)
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Handle oracle stale/no valid median error
                if "no valid median" in error_msg or "stale" in error_msg:
                    logger.warning(f"Mento oracle has no valid median for {pair}, using fallback rate")
                    
                    # Use fallback rate based on typical FX rates
                    fallback_rate = self._get_fallback_rate(token_in, token_out)
                    amount_out = amount_in * fallback_rate
                    amount_out_wei = int(amount_out * (10 ** decimals_out))
                else:
                    # Re-raise other errors
                    raise
            
            # Estimate gas for single hop
            gas_estimate = 150000  # Typical for Mento swap
            
            # Calculate costs
            gas_cost_eth = (gas_estimate * self.gas_price_gwei * 1e-9)
            gas_cost_usd = gas_cost_eth * self.cele_price_usd
            
            # Mento fee (0.25% per hop)
            mento_fee = amount_in * (self.mento_fee_percent / 100)
            
            return SimulationResult(
                success=True,
                amount_out=amount_out,
                amount_out_wei=amount_out_wei,
                fee_cost=mento_fee,
                gas_cost_eth=gas_cost_eth,
                gas_cost_usd=gas_cost_usd,
                net_profit_usd=0,  # Not calculated for single hop
                profit_percent=0,
                price_impact=0,
                exchange_provider=exchange_provider,
                error_message=None,
                timestamp=time.time()
            )
            
        except Exception as e:
            return SimulationResult(
                success=False,
                amount_out=0,
                amount_out_wei=0,
                fee_cost=0,
                gas_cost_eth=0,
                gas_cost_usd=0,
                net_profit_usd=0,
                profit_percent=0,
                price_impact=0,
                exchange_provider="",
                error_message=str(e),
                timestamp=time.time()
            )
    
    def invalidate_cache(self, pair: str):
        """Invalidate cache for a pair after successful trade."""
        keys_to_remove = [k for k in self._cache.keys() if pair in k]
        for key in keys_to_remove:
            del self._cache[key]
        logger.debug(f"Invalidated cache for {pair}")


class ProfitValidator:
    """
    Validates if a simulated trade meets profit criteria.
    """
    
    def __init__(self):
        self.min_profit_usd = float(config.safety.max_trade_size_usd * 0.01)  # 1% of max trade
        self.min_profit_percent = 0.5  # 0.5%
        self.max_slippage = 0.01  # 1%
        self.max_gas_usd = 0.05  # 5 cents max gas
    
    def validate_trade(
        self, 
        simulation: SimulationResult, 
        pair: str, 
        amount: float
    ) -> Dict[str, Any]:
        """
        Validate if simulated trade meets profit criteria.
        
        Args:
            simulation: Simulation result
            pair: Trading pair
            amount: Trade amount
            
        Returns:
            Dict with should_execute, reason, confidence
        """
        decision = {
            "should_execute": False,
            "reason": "",
            "expected_profit": simulation.net_profit_usd,
            "confidence": 0.0,
            "details": {}
        }
        
        # Check 1: Simulation must succeed
        if not simulation.success:
            decision["reason"] = f"Simulation failed: {simulation.error_message}"
            decision["details"]["error"] = simulation.error_message
            return decision
        
        # Check 2: Minimum absolute profit
        if simulation.net_profit_usd < self.min_profit_usd:
            decision["reason"] = (
                f"Profit ${simulation.net_profit_usd:.2f} below minimum ${self.min_profit_usd}"
            )
            decision["details"]["profit_usd"] = simulation.net_profit_usd
            return decision
        
        # Check 3: Minimum percentage profit
        if simulation.profit_percent < self.min_profit_percent:
            decision["reason"] = (
                f"Profit {simulation.profit_percent:.2f}% below threshold {self.min_profit_percent}%"
            )
            decision["details"]["profit_percent"] = simulation.profit_percent
            return decision
        
        # Check 4: Price impact (if available)
        if simulation.price_impact > self.max_slippage:
            decision["reason"] = (
                f"Price impact {simulation.price_impact:.2%} exceeds max {self.max_slippage:.2%}"
            )
            decision["details"]["price_impact"] = simulation.price_impact
            return decision
        
        # Check 5: Gas cost sanity check
        if simulation.gas_cost_usd > self.max_gas_usd:
            decision["reason"] = f"Gas cost ${simulation.gas_cost_usd:.4f} unusually high"
            decision["details"]["gas_cost"] = simulation.gas_cost_usd
            return decision
        
        # All checks passed
        decision["should_execute"] = True
        decision["confidence"] = min(simulation.profit_percent / 5.0, 1.0)
        decision["reason"] = (
            f"Expected profit: ${simulation.net_profit_usd:.2f} "
            f"({simulation.profit_percent:.2f}%) | "
            f"Gas: ${simulation.gas_cost_usd:.4f}"
        )
        decision["details"] = {
            "amount_out": simulation.amount_out,
            "fee_cost": simulation.fee_cost,
            "gas_cost": simulation.gas_cost_usd,
            "net_profit": simulation.net_profit_usd
        }
        
        return decision
