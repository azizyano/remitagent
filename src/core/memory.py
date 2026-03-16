"""
Agent Memory System for RemitAgent.
Stores experiences, outcomes, and learned strategies for adaptive behavior.
"""
import json
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

from logger import logger


@dataclass
class TradeExperience:
    """Records a single trade experience for learning."""
    timestamp: str
    pair: str
    direction: str
    source: str  # 'mento', 'curve', 'uniswap_v3', '0x'
    amount_usd: float
    expected_rate: float
    actual_rate: float
    expected_savings_percent: float
    gas_cost_usd: float
    slippage_percent: float
    success: bool
    execution_time_ms: int
    market_conditions: Dict[str, Any] = field(default_factory=dict)
    error_reason: Optional[str] = None


@dataclass
class CorridorPerformance:
    """Tracks performance metrics for a specific corridor."""
    pair: str
    total_attempts: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_volume_usd: float = 0.0
    total_gas_cost_usd: float = 0.0
    avg_slippage_percent: float = 0.0
    avg_execution_time_ms: float = 0.0
    best_source: str = "mento"
    last_trade_timestamp: Optional[str] = None
    success_rate_by_source: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    def update(self, experience: TradeExperience):
        """Update metrics with a new experience."""
        self.total_attempts += 1
        self.last_trade_timestamp = experience.timestamp
        
        if experience.success:
            self.successful_trades += 1
            self.total_volume_usd += experience.amount_usd
        else:
            self.failed_trades += 1
        
        self.total_gas_cost_usd += experience.gas_cost_usd
        
        # Update running averages
        n = self.total_attempts
        self.avg_slippage_percent = (
            (self.avg_slippage_percent * (n - 1) + experience.slippage_percent) / n
        )
        self.avg_execution_time_ms = (
            (self.avg_execution_time_ms * (n - 1) + experience.execution_time_ms) / n
        )
        
        # Track success by source
        source = experience.source
        if source not in self.success_rate_by_source:
            self.success_rate_by_source[source] = {"success": 0, "total": 0}
        
        self.success_rate_by_source[source]["total"] += 1
        if experience.success:
            self.success_rate_by_source[source]["success"] += 1
        
        # Determine best source
        best_rate = 0.0
        for src, stats in self.success_rate_by_source.items():
            rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0
            if rate > best_rate and stats["total"] >= 3:  # Min sample size
                best_rate = rate
                self.best_source = src


@dataclass
class StrategyParameters:
    """Learned parameters that adapt based on experience."""
    # Thresholds
    min_spread_threshold: float = 0.5  # Base threshold
    adaptive_threshold: float = 0.5  # Adjusted based on success rate
    
    # Source preferences (0-1 scores)
    source_preferences: Dict[str, float] = field(default_factory=lambda: {
        "mento": 1.0,
        "curve": 0.8,
        "uniswap_v3": 0.6,
        "0x": 0.7
    })
    
    # Timing parameters
    optimal_check_interval: int = 300  # seconds
    cooldown_multiplier: float = 1.0
    
    # Risk parameters
    max_slippage_tolerance: float = 0.5
    volatility_adjustment: float = 1.0
    
    # Learning state
    last_adaptation: Optional[str] = None
    adaptation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def adapt_threshold(self, success_rate: float, recent_spreads: List[float]):
        """Adapt threshold based on success rate and market conditions."""
        old_threshold = self.adaptive_threshold
        
        if success_rate > 0.8:
            # High success - can be more aggressive (lower threshold)
            self.adaptive_threshold = max(0.3, self.adaptive_threshold * 0.95)
        elif success_rate < 0.5:
            # Low success - be more conservative (higher threshold)
            self.adaptive_threshold = min(2.0, self.adaptive_threshold * 1.1)
        
        # Adjust for recent spread volatility
        if recent_spreads:
            avg_spread = sum(recent_spreads) / len(recent_spreads)
            if avg_spread < self.adaptive_threshold:
                # Spreads are tight - need to be more sensitive
                self.adaptive_threshold = max(0.2, avg_spread * 0.8)
        
        return old_threshold != self.adaptive_threshold
    
    def adjust_source_preference(self, source: str, outcome: str):
        """Adjust preference for a liquidity source based on outcome."""
        current = self.source_preferences.get(source, 0.5)
        
        if outcome == "success":
            self.source_preferences[source] = min(1.0, current + 0.05)
        elif outcome == "high_slippage":
            self.source_preferences[source] = max(0.1, current - 0.1)
        elif outcome == "failure":
            self.source_preferences[source] = max(0.0, current - 0.15)


class AgentMemory:
    """
    Persistent memory system for the RemitAgent.
    Stores experiences and learned strategies.
    """
    
    def __init__(self, memory_file: str = "data/agent_memory.json"):
        self.memory_file = Path(memory_file)
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        
        # In-memory storage
        self.experiences: List[TradeExperience] = []
        self.corridors: Dict[str, CorridorPerformance] = {}
        self.strategy = StrategyParameters()
        
        # Load persisted memory
        self._load()
    
    def _load(self):
        """Load memory from disk."""
        if not self.memory_file.exists():
            logger.info("No previous memory found, starting fresh")
            return
        
        try:
            with open(self.memory_file, 'r') as f:
                data = json.load(f)
            
            # Load experiences (last 100 only)
            for exp_data in data.get("experiences", [])[-100:]:
                self.experiences.append(TradeExperience(**exp_data))
            
            # Load corridor performance
            for pair, corr_data in data.get("corridors", {}).items():
                self.corridors[pair] = CorridorPerformance(**corr_data)
            
            # Load strategy
            if "strategy" in data:
                strat_data = data["strategy"]
                self.strategy = StrategyParameters(**strat_data)
            
            logger.info(f"Loaded {len(self.experiences)} experiences, "
                       f"{len(self.corridors)} corridors from memory")
            
        except Exception as e:
            logger.error(f"Failed to load memory: {e}")
    
    def save(self):
        """Save memory to disk."""
        try:
            data = {
                "experiences": [asdict(e) for e in self.experiences[-100:]],
                "corridors": {
                    pair: asdict(corr) 
                    for pair, corr in self.corridors.items()
                },
                "strategy": asdict(self.strategy),
                "last_saved": datetime.utcnow().isoformat()
            }
            
            with open(self.memory_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("Memory saved")
            
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
    
    def record_experience(self, experience: TradeExperience):
        """Record a new trade experience."""
        self.experiences.append(experience)
        
        # Update corridor performance
        pair = experience.pair
        if pair not in self.corridors:
            self.corridors[pair] = CorridorPerformance(pair=pair)
        
        self.corridors[pair].update(experience)
        
        # Auto-save every 10 experiences
        if len(self.experiences) % 10 == 0:
            self.save()
    
    def get_corridor_performance(self, pair: str) -> Optional[CorridorPerformance]:
        """Get performance metrics for a corridor."""
        return self.corridors.get(pair)
    
    def get_recent_experiences(
        self, 
        pair: Optional[str] = None, 
        hours: int = 24,
        successful_only: bool = False
    ) -> List[TradeExperience]:
        """Get recent experiences with optional filtering."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        results = []
        for exp in reversed(self.experiences):
            exp_time = datetime.fromisoformat(exp.timestamp)
            if exp_time < cutoff:
                break
            
            if pair and exp.pair != pair:
                continue
            
            if successful_only and not exp.success:
                continue
            
            results.append(exp)
        
        return results
    
    def get_success_rate(self, pair: Optional[str] = None, hours: int = 24) -> float:
        """Calculate success rate for a pair or overall."""
        experiences = self.get_recent_experiences(pair, hours)
        
        if not experiences:
            return 0.5  # Neutral default
        
        successful = sum(1 for e in experiences if e.success)
        return successful / len(experiences)
    
    def get_best_liquidity_source(self, pair: str) -> str:
        """Get the best performing liquidity source for a pair."""
        corridor = self.corridors.get(pair)
        if corridor:
            return corridor.best_source
        
        # Default preference based on strategy
        preferences = self.strategy.source_preferences
        return max(preferences, key=preferences.get)
    
    def get_learning_summary(self) -> Dict[str, Any]:
        """Get a summary of what the agent has learned."""
        total_trades = len([e for e in self.experiences if e.success])
        total_failed = len([e for e in self.experiences if not e.success])
        
        return {
            "total_experiences": len(self.experiences),
            "successful_trades": total_trades,
            "failed_trades": total_failed,
            "overall_success_rate": (
                total_trades / (total_trades + total_failed) 
                if (total_trades + total_failed) > 0 else 0
            ),
            "corridors_learned": list(self.corridors.keys()),
            "current_adaptive_threshold": self.strategy.adaptive_threshold,
            "source_preferences": self.strategy.source_preferences,
            "best_performing_corridor": (
                max(self.corridors.values(), key=lambda c: c.successful_trades).pair
                if self.corridors else None
            )
        }
