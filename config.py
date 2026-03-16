"""
Configuration module for RemitAgent.
Loads and validates environment variables with type safety.
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class CeloConfig:
    """Celo blockchain configuration."""
    rpc_url: str = field(default_factory=lambda: os.getenv("CELO_RPC_URL", "https://forno.celo.org"))
    private_key: Optional[str] = field(default_factory=lambda: os.getenv("CELO_PRIVATE_KEY"))
    wallet_address: Optional[str] = field(default_factory=lambda: os.getenv("CELO_WALLET_ADDRESS"))
    
    def validate(self) -> bool:
        """Validate Celo configuration."""
        if not self.wallet_address:
            raise ValueError("CELO_WALLET_ADDRESS is required")
        return True


@dataclass
class GraphConfig:
    """The Graph configuration for Uniswap V3 subgraph."""
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("GRAPH_API_KEY"))
    # Uniswap V3 Celo subgraph on The Graph Network
    # https://thegraph.com/explorer/subgraphs/5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV?view=Overview
    subgraph_id: str = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"
    
    @property
    def endpoint(self) -> str:
        """Construct the subgraph endpoint URL."""
        if self.api_key:
            return f"https://gateway.thegraph.com/api/{self.api_key}/subgraphs/id/{self.subgraph_id}"
        # No API key - will need to use RPC fallback
        return None


@dataclass
class ZeroXConfig:
    """0x API configuration for DEX aggregation."""
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("ZEROX_API_KEY"))
    base_url: str = "https://api.0x.org"
    chain_id: int = 42220  # Celo Mainnet
    
    @property
    def headers(self) -> dict:
        """Get headers for 0x API requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["0x-api-key"] = self.api_key
        return headers


@dataclass
class FXConfig:
    """Off-chain FX rate oracle configuration."""
    exchange_rate_api_key: Optional[str] = field(default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY"))
    frankfurter_url: str = field(default_factory=lambda: os.getenv("FRANKFURTER_URL", "https://api.frankfurter.app"))


@dataclass
class NotificationConfig:
    """Notification system configuration."""
    telegram_bot_token: Optional[str] = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: Optional[str] = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID"))
    
    @property
    def enabled(self) -> bool:
        """Check if notifications are enabled."""
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@dataclass
class AgentConfig:
    """Agent behavior configuration."""
    min_spread_threshold: float = field(default_factory=lambda: float(os.getenv("MIN_SPREAD_THRESHOLD", "0.5")))
    check_interval_seconds: int = field(default_factory=lambda: int(os.getenv("CHECK_INTERVAL_SECONDS", "300")))
    # Target pairs for arbitrage
    # - Direct Mento pairs: cUSD-cEUR, cUSD-cKES, etc.
    # - Composite pairs (route through cUSD): cEUR-cKES, cEUR-cCOP, etc.
    # - Cross-DEX pairs: cUSD-axlUSDC (Mento vs Curve)
    target_pairs: List[str] = field(default_factory=lambda: os.getenv(
        "TARGET_PAIRS", 
        "cUSD-cEUR,cUSD-cKES,cUSD-cCOP,cUSD-cNGN,cUSD-cREAL,cEUR-cKES,cEUR-cCOP,cEUR-cNGN,cKES-cCOP,cUSD-axlUSDC"
    ).split(","))


@dataclass
class SafetyConfig:
    """Safety and risk management configuration."""
    slippage_protection: float = field(default_factory=lambda: float(os.getenv("SLIPPAGE_PROTECTION", "0.5")))
    max_trade_size_usd: float = field(default_factory=lambda: float(os.getenv("MAX_TRADE_SIZE_USD", "1000")))
    min_liquidity_depth: float = field(default_factory=lambda: float(os.getenv("MIN_LIQUIDITY_DEPTH", "10000")))
    cooldown_minutes: int = field(default_factory=lambda: int(os.getenv("COOLDOWN_MINUTES", "15")))
    emergency_stop_file: str = field(default_factory=lambda: os.getenv("EMERGENCY_STOP_FILE", "/tmp/remitagent_stop"))


class Config:
    """Main configuration class that aggregates all config sections."""
    
    def __init__(self):
        self.celo = CeloConfig()
        self.graph = GraphConfig()
        self.zerox = ZeroXConfig()
        self.fx = FXConfig()
        self.notifications = NotificationConfig()
        self.agent = AgentConfig()
        self.safety = SafetyConfig()
    
    def validate(self) -> bool:
        """Validate all configuration sections."""
        try:
            self.celo.validate()
            return True
        except ValueError as e:
            raise ValueError(f"Configuration validation failed: {e}")
    
    def is_emergency_stop(self) -> bool:
        """Check if emergency stop file exists."""
        return Path(self.safety.emergency_stop_file).exists()


# Token addresses for Celo Mainnet
TOKEN_ADDRESSES = {
    # Legacy Mento tokens (c-prefix) - being migrated to m-suffix
    "cUSD": {
        "address": "0x765DE816845861e75A25fCA122bb6898B8B1282a",
        "decimals": 18,
        "symbol": "cUSD"
    },
    "cEUR": {
        "address": "0xD8763CBa276a3738E6DE85b4b3bF5FDed6D6cA73",
        "decimals": 18,
        "symbol": "cEUR"
    },
    "cREAL": {
        "address": "0xe8537a3d056DA446677B9E9d6c5dB704EaAb4787",
        "decimals": 18,
        "symbol": "cREAL"
    },
    "cKES": {
        "address": "0x456a3D042C0DbD3db53D5489e98dFb038553B0d0",
        "decimals": 18,
        "symbol": "cKES"
    },
    "cCOP": {
        "address": "0x8a567e2ae79ca692bd748ab832081c45de4041ea",
        "decimals": 18,
        "symbol": "cCOP"
    },
    "cNGN": {
        "address": "0x832f8ebc9b82012a7cbab6e564df9c7272b0d710",
        "decimals": 18,
        "symbol": "cNGN"
    },
    # New Mento tokens (m-suffix) - future-proofing
    "USDm": {
        "address": "0xcebA9300f2b948710d2653dD7B07f33A8B32118C",
        "decimals": 18,
        "symbol": "USDm"
    },
    "EURm": {
        "address": "0xE4F356EcBe573F492ED73b061c8C8ec846F0972d",
        "decimals": 18,
        "symbol": "EURm"
    },
    # Bridged stables for Curve arbitrage
    "axlUSDC": {
        "address": "0xEB466342C4d449BC9f53A865D5Cb90586f405215",
        "decimals": 6,
        "symbol": "axlUSDC"
    },
    "CELO": {
        "address": "0x471EcE3750Da237f93B8E339c536989b8978a438",
        "decimals": 18,
        "symbol": "CELO"
    }
}

# Uniswap V3 Pool Addresses on Celo
# Source: https://celoscan.io/ and Uniswap V3 factory
POOL_ADDRESSES = {
    # High priority - active arbitrage pools
    "cUSD-cEUR-0.05": "0x1f18CD7D1c7Ba0DbE3D9AbE0D3eC84Ce1ad10066",  # Main arbitrage pool
    "cUSD-CELO-0.3": "0x079e7A44F42E9cd2442C3B9536244be634e8f888",   # High liquidity CELO pool
    "cEUR-CELO-0.3": "0x7FaF167615419228F3F7D71d52d840daB154913c",   # cEUR/CELO pool
    "cUSD-CELO-0.05": "0x524375d0c6a04439128428F400B00eAE81a2e9E4",  # Low fee CELO pool
}

# Mento Broker addresses (Celo Mainnet)
# Source: https://github.com/mento-protocol/mento-sdk/blob/main/src/core/constants/addresses.ts
MENTO_ADDRESSES = {
    "broker": "0x777A8255cA72412f0d706dc03C9D1987306B4CaD",
    "bi_pool_manager": "0x22d9db95E6Ae61c104A7B6F6C78D7993B94ec901"
}

# Curve Finance on Celo
CURVE_ADDRESSES = {
    "cUSD-axlUSDC_pool": "0x854ec4ede802e120fdf38fc12f1e46e1f139331E",
    "triCrypto_pool": "0x998395fEd3d9E65B4F6c57AAB9225bE891cF34e3"  # CELO/cUSD/axlUSDC
}

# Additional DEX routers
DEX_ROUTERS = {
    "ubeswap": "0xE3D8bd6Aed4F159bc8000a9cD47Cffdb96D0b6Df",
    "sushiswap": "0x1421bDe4B10e8dd459b3BCb598810B1337B568a7"
}


# Create global config instance
config = Config()
