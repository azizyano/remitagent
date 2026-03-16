"""
Safety and Risk Management for RemitAgent.
Implements guards and checks before trade execution.
"""
import asyncio
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

from web3 import Web3

from config import config, TOKEN_ADDRESSES
from logger import logger, log_risk_check_failed


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    passed: bool
    reason: Optional[str] = None
    details: Dict[str, Any] = None


class RiskManager:
    """
    Manages risk checks and safety guards for the agent.
    All checks must pass before a trade is executed.
    """
    
    def __init__(self):
        self.safety_config = config.safety
        self.w3 = Web3(Web3.HTTPProvider(config.celo.rpc_url))
        
        # Track last trade time per pair for cooldown
        self._last_trade_time: Dict[str, datetime] = {}
        
        # Track pending transactions
        self._pending_transactions: set = set()
        self._nonce_lock = asyncio.Lock()
    
    async def run_all_checks(
        self,
        pair: str,
        trade_amount_usd: float,
        pool_liquidity: float,
        volume_24h: float,
        gas_price_gwei: float,
        wallet_address: str
    ) -> RiskCheckResult:
        """
        Run all risk checks before trade execution.
        
        Args:
            pair: Trading pair
            trade_amount_usd: Trade amount in USD
            pool_liquidity: Pool liquidity in USD
            volume_24h: 24h volume in USD
            gas_price_gwei: Current gas price in Gwei
            wallet_address: Wallet address
            
        Returns:
            RiskCheckResult with pass/fail status
        """
        checks = [
            ("emergency_stop", self._check_emergency_stop()),
            ("trade_size", self._check_trade_size(trade_amount_usd)),
            ("liquidity_depth", self._check_liquidity_depth(pool_liquidity)),
            ("volume", self._check_volume(volume_24h)),
            ("gas_price", self._check_gas_price(gas_price_gwei)),
            ("wallet_balance", await self._check_wallet_balance(wallet_address, trade_amount_usd)),
            ("cooldown", self._check_cooldown(pair)),
            ("pending_transactions", await self._check_pending_transactions(wallet_address)),
        ]
        
        for check_name, result in checks:
            if isinstance(result, asyncio.Future) or asyncio.iscoroutine(result):
                result = await result
            
            if not result.passed:
                log_risk_check_failed(check_name, result.reason)
                return result
        
        return RiskCheckResult(passed=True, details={"checks_passed": len(checks)})
    
    def _check_emergency_stop(self) -> RiskCheckResult:
        """Check if emergency stop file exists."""
        if config.is_emergency_stop():
            return RiskCheckResult(
                passed=False,
                reason="Emergency stop is active"
            )
        return RiskCheckResult(passed=True)
    
    def _check_trade_size(self, trade_amount_usd: float) -> RiskCheckResult:
        """Check if trade size is within limits."""
        max_size = self.safety_config.max_trade_size_usd
        
        if trade_amount_usd > max_size:
            return RiskCheckResult(
                passed=False,
                reason=f"Trade size ${trade_amount_usd:.2f} exceeds max ${max_size:.2f}"
            )
        return RiskCheckResult(passed=True)
    
    def _check_liquidity_depth(self, pool_liquidity: float) -> RiskCheckResult:
        """Check if pool has sufficient liquidity."""
        min_liquidity = self.safety_config.min_liquidity_depth
        
        if pool_liquidity < min_liquidity:
            return RiskCheckResult(
                passed=False,
                reason=f"Pool liquidity ${pool_liquidity:.2f} below minimum ${min_liquidity:.2f}"
            )
        return RiskCheckResult(passed=True)
    
    def _check_volume(self, volume_24h: float) -> RiskCheckResult:
        """Check if pool has sufficient 24h volume."""
        min_volume = 1000  # $1000 minimum
        
        if volume_24h < min_volume:
            return RiskCheckResult(
                passed=False,
                reason=f"24h volume ${volume_24h:.2f} below minimum ${min_volume:.2f}"
            )
        return RiskCheckResult(passed=True)
    
    def _check_gas_price(self, gas_price_gwei: float) -> RiskCheckResult:
        """Check if gas price is reasonable."""
        max_gas = 10  # 10 Gwei max on Celo
        
        if gas_price_gwei > max_gas:
            return RiskCheckResult(
                passed=False,
                reason=f"Gas price {gas_price_gwei:.2f} Gwei exceeds max {max_gas} Gwei"
            )
        return RiskCheckResult(passed=True)
    
    async def _check_wallet_balance(
        self, 
        wallet_address: str, 
        trade_amount_usd: float
    ) -> RiskCheckResult:
        """Check if wallet has sufficient balance."""
        try:
            # Get CELO balance for gas
            celo_balance = self.w3.eth.get_balance(wallet_address)
            celo_balance_eth = self.w3.from_wei(celo_balance, 'ether')
            
            # Estimate gas cost (generous estimate)
            gas_buffer = 0.01  # 0.01 CELO for gas
            
            if celo_balance_eth < gas_buffer:
                return RiskCheckResult(
                    passed=False,
                    reason=f"Insufficient CELO for gas: {celo_balance_eth:.4f} CELO"
                )
            
            return RiskCheckResult(
                passed=True,
                details={"celo_balance": celo_balance_eth}
            )
            
        except Exception as e:
            return RiskCheckResult(
                passed=False,
                reason=f"Failed to check wallet balance: {e}"
            )
    
    def _check_cooldown(self, pair: str) -> RiskCheckResult:
        """Check if pair is in cooldown period."""
        last_trade = self._last_trade_time.get(pair)
        
        if last_trade:
            elapsed = (datetime.utcnow() - last_trade).total_seconds() / 60
            cooldown = self.safety_config.cooldown_minutes
            
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                return RiskCheckResult(
                    passed=False,
                    reason=f"Pair {pair} in cooldown. {remaining:.1f} minutes remaining"
                )
        
        return RiskCheckResult(passed=True)
    
    async def _check_pending_transactions(self, wallet_address: str) -> RiskCheckResult:
        """Check for pending transactions."""
        try:
            # Get nonce from chain and from pending
            current_nonce = self.w3.eth.get_transaction_count(wallet_address)
            pending_nonce = self.w3.eth.get_transaction_count(wallet_address, 'pending')
            
            if pending_nonce > current_nonce:
                return RiskCheckResult(
                    passed=False,
                    reason=f"Has {pending_nonce - current_nonce} pending transaction(s)"
                )
            
            return RiskCheckResult(passed=True)
            
        except Exception as e:
            return RiskCheckResult(
                passed=False,
                reason=f"Failed to check pending transactions: {e}"
            )
    
    def record_trade(self, pair: str):
        """Record trade time for cooldown tracking."""
        self._last_trade_time[pair] = datetime.utcnow()
        logger.info(f"Recorded trade for {pair} at {self._last_trade_time[pair]}")
    
    async def get_next_nonce(self, wallet_address: str) -> int:
        """
        Get next nonce with locking to prevent collisions.
        
        Args:
            wallet_address: Wallet address
            
        Returns:
            Next available nonce
        """
        async with self._nonce_lock:
            return self.w3.eth.get_transaction_count(wallet_address)
    
    def calculate_min_amount_out(
        self,
        amount_in: float,
        expected_rate: float,
        token_out_decimals: int
    ) -> int:
        """
        Calculate minimum amount out with slippage protection.
        
        Args:
            amount_in: Input amount
            expected_rate: Expected output rate
            token_out_decimals: Decimals of output token
            
        Returns:
            Minimum amount out (in wei)
        """
        slippage = self.safety_config.slippage_protection / 100
        expected_out = amount_in * expected_rate
        min_out = expected_out * (1 - slippage)
        
        return int(min_out * (10 ** token_out_decimals))
    
    def is_safe_to_trade(
        self,
        spread_percent: float,
        threshold: float
    ) -> bool:
        """
        Quick check if spread is sufficient for trading.
        
        Args:
            spread_percent: Detected spread percentage
            threshold: Minimum threshold
            
        Returns:
            True if safe to proceed with detailed checks
        """
        # Add buffer for safety
        safety_buffer = 0.1  # 0.1% buffer
        return spread_percent >= (threshold + safety_buffer)
