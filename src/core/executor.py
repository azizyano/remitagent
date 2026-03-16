"""
Transaction execution module for RemitAgent.
Handles actual Mento swap execution with safety features.
"""
import asyncio
from typing import Optional, Dict, Any
from decimal import Decimal

from web3 import Web3
from web3.types import TxReceipt

from config import config, TOKEN_ADDRESSES, MENTO_ADDRESSES
from logger import logger, log_trade_executed, log_trade_failed


# Mento Broker ABI for swap execution
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
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"}
        ],
        "name": "swapIn",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# ERC20 ABI for approvals
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]


class TransactionExecutor:
    """
    Handles transaction execution with safety features.
    Uses async locking for nonce management on Celo.
    """
    
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(config.celo.rpc_url))
        self.nonce_lock = asyncio.Lock()
        self.wallet_address = config.celo.wallet_address
        self.private_key = config.celo.private_key
        
        # Mento contracts
        self.broker_address = Web3.to_checksum_address(MENTO_ADDRESSES["broker"])
        self.bi_pool_manager_address = Web3.to_checksum_address(MENTO_ADDRESSES["bi_pool_manager"])
        self.broker = self.w3.eth.contract(
            address=self.broker_address,
            abi=BROKER_ABI
        )
    
    async def send_transaction(
        self,
        tx_params: Dict[str, Any],
        wait_for_receipt: bool = True,
        timeout: int = 60
    ) -> str:
        """
        Send a transaction with nonce management.
        
        Args:
            tx_params: Transaction parameters
            wait_for_receipt: Whether to wait for receipt
            timeout: Timeout in seconds
            
        Returns:
            Transaction hash
        """
        if not self.wallet_address or not self.private_key:
            raise ValueError("Wallet not configured for transaction execution")
        
        async with self.nonce_lock:
            try:
                # Get fresh nonce
                nonce = self.w3.eth.get_transaction_count(self.wallet_address)
                tx_params['nonce'] = nonce
                
                # Ensure gas price is set
                if 'gasPrice' not in tx_params:
                    tx_params['gasPrice'] = self.w3.eth.gas_price
                
                # Estimate gas if not set
                if 'gas' not in tx_params:
                    try:
                        tx_params['gas'] = self.w3.eth.estimate_gas(tx_params)
                        # Add buffer
                        tx_params['gas'] = int(tx_params['gas'] * 1.2)
                    except Exception as e:
                        logger.warning(f"Gas estimation failed, using default: {e}")
                        tx_params['gas'] = 200000
                
                # Sign transaction
                signed_tx = self.w3.eth.account.sign_transaction(tx_params, self.private_key)
                
                # Send transaction
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                tx_hash_hex = tx_hash.hex()
                
                logger.info(f"Transaction sent: {tx_hash_hex}")
                
                if wait_for_receipt:
                    receipt = await self._wait_for_receipt(tx_hash_hex, timeout)
                    if receipt['status'] != 1:
                        raise Exception(f"Transaction failed: {receipt}")
                
                return tx_hash_hex
                
            except Exception as e:
                logger.error(f"Transaction failed: {e}")
                raise
    
    async def _wait_for_receipt(
        self, 
        tx_hash: str, 
        timeout: int = 60
    ) -> TxReceipt:
        """Wait for transaction receipt with timeout."""
        start_time = asyncio.get_event_loop().time()
        
        while True:
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt:
                    return receipt
            except Exception:
                pass
            
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError(f"Transaction receipt timeout after {timeout}s")
            
            await asyncio.sleep(1)  # Celo has 1s block time
    
    async def check_token_allowance(
        self, 
        token_address: str, 
        amount: int
    ) -> bool:
        """Check if token allowance is sufficient."""
        if not self.wallet_address:
            return False
        
        token_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        
        allowance = token_contract.functions.allowance(
            self.wallet_address,
            self.broker_address
        ).call()
        
        return allowance >= amount
    
    async def approve_token(
        self, 
        token_address: str, 
        amount: int
    ) -> str:
        """Approve token spending for Mento broker."""
        token_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        
        # Build approval transaction
        tx_params = {
            'to': Web3.to_checksum_address(token_address),
            'data': token_contract.encodeABI('approve', [self.broker_address, amount]),
            'from': self.wallet_address,
            'gas': 100000,
            'gasPrice': self.w3.eth.gas_price,
            'value': 0
        }
        
        tx_hash = await self.send_transaction(tx_params)
        logger.info(f"Approval transaction: {tx_hash}")
        
        return tx_hash
    
    async def check_balance(
        self, 
        token_address: str
    ) -> int:
        """Check token balance."""
        if not self.wallet_address:
            return 0
        
        token_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
        
        return token_contract.functions.balanceOf(self.wallet_address).call()
    
    async def execute_mento_swap(
        self,
        pair: str,
        amount_in: float,
        min_amount_out: float,
        exchange_provider: str,
        exchange_id: str,
        slippage_percent: float = 0.5,
        is_composite: bool = False,
        hops: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Execute a swap through Mento Broker.
        
        Args:
            pair: Trading pair (e.g., "cUSD-cEUR")
            amount_in: Amount to swap (in token units)
            min_amount_out: Minimum amount to receive
            exchange_provider: Exchange provider address
            exchange_id: Exchange ID (bytes32)
            slippage_percent: Slippage tolerance
            is_composite: Whether this is a composite (multi-hop) swap
            hops: List of hop configurations for composite swaps
            
        Returns:
            Dict with transaction hash(es) and details
        """
        try:
            # Handle composite swaps (multi-hop through cUSD)
            if is_composite and hops:
                return await self._execute_composite_swap(pair, amount_in, hops, slippage_percent)
            
            # Handle direct single-hop swap
            return await self._execute_single_swap(
                pair, amount_in, min_amount_out, exchange_provider, exchange_id, slippage_percent
            )
            
        except Exception as e:
            log_trade_failed(str(e), pair, amount_in)
            raise
    
    async def _execute_single_swap(
        self,
        pair: str,
        amount_in: float,
        min_amount_out: float,
        exchange_provider: str,
        exchange_id: str,
        slippage_percent: float = 0.5
    ) -> Dict[str, Any]:
        """Execute a single-hop swap."""
        # Parse pair
        token_in, token_out = pair.split("-")
        token_in_addr = TOKEN_ADDRESSES[token_in]["address"]
        token_out_addr = TOKEN_ADDRESSES[token_out]["address"]
        
        decimals_in = TOKEN_ADDRESSES[token_in]["decimals"]
        decimals_out = TOKEN_ADDRESSES[token_out]["decimals"]
        
        amount_in_wei = int(amount_in * (10 ** decimals_in))
        min_amount_out_wei = int(min_amount_out * (10 ** decimals_out))
        
        # Check balance
        balance = await self.check_balance(token_in_addr)
        if balance < amount_in_wei:
            raise ValueError(
                f"Insufficient balance: {balance / (10 ** decimals_in)} < {amount_in}"
            )
        
        # Check and approve allowance if needed
        if not await self.check_token_allowance(token_in_addr, amount_in_wei):
            logger.info(f"Approving {token_in} for Mento broker...")
            await self.approve_token(token_in_addr, amount_in_wei)
        
        # Build swap transaction
        tx_params = {
            'to': self.broker_address,
            'data': self.broker.encodeABI('swapIn', [
                Web3.to_checksum_address(exchange_provider),
                Web3.to_checksum_address(token_in_addr),
                Web3.to_checksum_address(token_out_addr),
                amount_in_wei,
                min_amount_out_wei
            ]),
            'from': self.wallet_address,
            'gas': 200000,
            'gasPrice': self.w3.eth.gas_price,
            'value': 0
        }
        
        # Send transaction
        tx_hash = await self.send_transaction(tx_params)
        
        # Log trade
        log_trade_executed(tx_hash, pair, amount_in, 0)
        
        return {
            "success": True,
            "tx_hash": tx_hash,
            "pair": pair,
            "amount_in": amount_in,
            "token_in": token_in,
            "token_out": token_out,
            "is_composite": False
        }
    
    async def _execute_composite_swap(
        self,
        pair: str,
        amount_in: float,
        hops: list,
        slippage_percent: float = 0.5
    ) -> Dict[str, Any]:
        """
        Execute a composite (multi-hop) swap through cUSD.
        
        Args:
            pair: Original trading pair (e.g., "cEUR-cKES")
            amount_in: Input amount
            hops: List of hop configurations with pair, amount_in, min_amount_out
            slippage_percent: Slippage tolerance for each hop
            
        Returns:
            Dict with transaction hashes and details
        """
        logger.info(f"Executing composite swap: {pair} in {len(hops)} hops")
        
        tx_hashes = []
        current_amount = amount_in
        
        for i, hop in enumerate(hops):
            hop_pair = hop.get("pair")
            hop_amount = hop.get("amount_in", current_amount)
            hop_min_out = hop.get("min_amount_out", 0)
            hop_provider = hop.get("exchange_provider", self.bi_pool_manager_address)
            hop_exchange_id = hop.get("exchange_id", b'\x00' * 32)
            
            logger.info(f"Executing hop {i+1}/{len(hops)}: {hop_pair} with {hop_amount}")
            
            result = await self._execute_single_swap(
                pair=hop_pair,
                amount_in=hop_amount,
                min_amount_out=hop_min_out,
                exchange_provider=hop_provider,
                exchange_id=hop_exchange_id,
                slippage_percent=slippage_percent
            )
            
            tx_hashes.append(result["tx_hash"])
            
            # Update current amount for next hop (would need actual output from receipt)
            # For now, use expected output
            current_amount = hop.get("expected_amount_out", hop_amount * 0.997)  # Approximate
        
        log_trade_executed(tx_hashes[0], pair, amount_in, 0)  # Log first tx as primary
        
        return {
            "success": True,
            "tx_hashes": tx_hashes,
            "primary_tx_hash": tx_hashes[0],
            "pair": pair,
            "amount_in": amount_in,
            "is_composite": True,
            "num_hops": len(hops)
        }
    
    def get_gas_cost_estimate(self, gas_limit: int = 200000) -> Dict[str, Any]:
        """Estimate gas cost for a transaction."""
        try:
            gas_price = self.w3.eth.gas_price
            gas_price_gwei = self.w3.from_wei(gas_price, 'gwei')
            
            # Estimate cost in CELO and USD
            cost_wei = gas_price * gas_limit
            cost_celo = self.w3.from_wei(cost_wei, 'ether')
            
            # Rough USD estimate (CELO ~ $0.50)
            cost_usd = float(cost_celo) * 0.5
            
            return {
                "gas_price_wei": gas_price,
                "gas_price_gwei": float(gas_price_gwei),
                "gas_limit": gas_limit,
                "cost_celo": float(cost_celo),
                "cost_usd": cost_usd
            }
            
        except Exception as e:
            logger.error(f"Failed to estimate gas: {e}")
            return {
                "gas_price_gwei": 0,
                "cost_celo": 0,
                "cost_usd": 0,
                "error": str(e)
            }
