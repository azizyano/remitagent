"""
Planner Module for RemitAgent.
Implements autonomous decision-making with explicit goal interpretation and tool selection.
"""
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from logger import logger


class ActionType(Enum):
    """Types of actions the agent can take."""
    EXECUTE_MENTO_SWAP = "execute_mento_swap"
    EXECUTE_CURVE_SWAP = "execute_curve_swap"
    EXECUTE_UNISWAP_V3_SWAP = "execute_uniswap_v3_swap"
    EXECUTE_0X_SWAP = "execute_0x_swap"
    WAIT = "wait"
    MONITOR = "monitor"
    INVESTIGATE = "investigate"


class LiquiditySource(Enum):
    """Available liquidity sources."""
    MENTO = "mento"
    CURVE = "curve"
    UNISWAP_V3 = "uniswap_v3"
    ZEROX = "0x"


@dataclass
class Tool:
    """Represents a tool the agent can use."""
    name: str
    description: str
    liquidity_source: LiquiditySource
    cost_model: str  # 'fixed_spread', 'amm_curve', 'aggregator_fee'
    speed_rating: int  # 1-5, 5 being fastest
    reliability_score: float  # 0-1 based on historical data
    best_for: List[str]  # e.g., ['stable-stable', 'large_amounts']
    limitations: List[str]  # e.g., ['limited_pairs', 'high_gas']


@dataclass
class Goal:
    """Agent's interpreted goal."""
    original_intent: str
    corridor: str
    amount_usd: float
    primary_objective: str  # 'maximize_savings', 'minimize_time', 'minimize_slippage'
    constraints: Dict[str, Any] = field(default_factory=dict)
    deadline: Optional[datetime] = None


@dataclass
class Plan:
    """A generated execution plan."""
    goal: Goal
    steps: List[Dict[str, Any]]
    primary_action: ActionType
    selected_tool: Tool
    expected_outcome: Dict[str, Any]
    confidence_score: float
    risk_assessment: Dict[str, Any]
    alternatives: List[Dict[str, Any]]
    reasoning: str


class ToolRegistry:
    """Registry of available tools for the agent."""
    
    def __init__(self, memory=None):
        self.memory = memory
        self._tools: Dict[LiquiditySource, Tool] = {}
        self._initialize_tools()
    
    def _initialize_tools(self):
        """Initialize the tool registry with Celo-specific knowledge."""
        
        # Mento - Primary tool for Celo stablecoins
        self._tools[LiquiditySource.MENTO] = Tool(
            name="Mento FPMM",
            description="Mento Protocol Federated Price Metric Maker for stablecoin swaps",
            liquidity_source=LiquiditySource.MENTO,
            cost_model="fixed_spread",
            speed_rating=5,
            reliability_score=0.95,
            best_for=[
                "stable-stable", 
                "cUSD-cEUR", "cUSD-cKES", "cUSD-cCOP", "cUSD-cNGN",
                "fx_corridors", "large_amounts", "predictable_rates"
            ],
            limitations=["celo_native_only", "no_celo_token_swaps"]
        )
        
        # Curve - Deep liquidity for cUSD/USDC
        self._tools[LiquiditySource.CURVE] = Tool(
            name="Curve StableSwap",
            description="Curve Finance stableswap for cUSD/USDCet ($20M TVL)",
            liquidity_source=LiquiditySource.CURVE,
            cost_model="amm_curve",
            speed_rating=4,
            reliability_score=0.90,
            best_for=["cUSD-USDC", "exit_to_usdc", "deep_liquidity"],
            limitations=["limited_pairs", " ethereum_bridge_risk"]
        )
        
        # Uniswap V3 - For CELO collateral moves
        self._tools[LiquiditySource.UNISWAP_V3] = Tool(
            name="Uniswap V3",
            description="Uniswap V3 concentrated liquidity on Celo",
            liquidity_source=LiquiditySource.UNISWAP_V3,
            cost_model="amm_curve",
            speed_rating=4,
            reliability_score=0.75,
            best_for=["CELO-cUSD", "CELO-cEUR", "speculative_pairs"],
            limitations=["limited_liquidity", "concentrated_liquidity_risk"]
        )
        
        # 0x - Aggregator fallback
        self._tools[LiquiditySource.ZEROX] = Tool(
            name="0x API",
            description="0x DEX aggregator for best route discovery",
            liquidity_source=LiquiditySource.ZEROX,
            cost_model="aggregator_fee",
            speed_rating=3,
            reliability_score=0.70,
            best_for=["route_optimization", "multi_hop", "price_discovery"],
            limitations=["api_dependency", "limited_celo_support", "rate_limits"]
        )
        
        # Update reliability scores from memory if available
        if self.memory:
            for source in LiquiditySource:
                perf = self._get_historical_performance(source.value)
                if perf:
                    self._tools[source].reliability_score = perf
    
    def _get_historical_performance(self, source: str) -> Optional[float]:
        """Get historical success rate for a source from memory."""
        if not self.memory:
            return None
        
        experiences = self.memory.get_recent_experiences(hours=168)  # Last week
        source_exps = [e for e in experiences if e.source == source]
        
        if len(source_exps) < 3:
            return None
        
        successful = sum(1 for e in source_exps if e.success)
        return successful / len(source_exps)
    
    def get_tool(self, source: LiquiditySource) -> Tool:
        """Get a tool by its source."""
        return self._tools[source]
    
    def get_all_tools(self) -> List[Tool]:
        """Get all available tools."""
        return list(self._tools.values())
    
    def rank_tools_for_goal(self, goal: Goal) -> List[Tuple[Tool, float]]:
        """Rank tools based on suitability for a goal."""
        scores = []
        
        for tool in self._tools.values():
            score = self._calculate_tool_score(tool, goal)
            scores.append((tool, score))
        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores
    
    def _calculate_tool_score(self, tool: Tool, goal: Goal) -> float:
        """Calculate a suitability score for a tool given a goal."""
        score = 0.0
        corridor = goal.corridor
        
        # Base reliability
        score += tool.reliability_score * 20
        
        # Corridor-specific matching
        if "cUSD" in corridor and "cEUR" in corridor:
            if LiquiditySource.MENTO == tool.liquidity_source:
                score += 30  # Mento is best for cUSD/cEUR
        
        if "cUSD" in corridor and "USDC" in corridor:
            if LiquiditySource.CURVE == tool.liquidity_source:
                score += 30  # Curve has deep cUSD/USDC liquidity
        
        if "CELO" in corridor:
            if LiquiditySource.UNISWAP_V3 == tool.liquidity_source:
                score += 25  # Uniswap for CELO pairs
        
        # Objective-based scoring
        if goal.primary_objective == "maximize_savings":
            if tool.cost_model == "fixed_spread":
                score += 15
        elif goal.primary_objective == "minimize_time":
            score += tool.speed_rating * 3
        elif goal.primary_objective == "minimize_slippage":
            if "deep_liquidity" in tool.best_for:
                score += 15
        
        # Apply learned preferences from memory
        if self.memory:
            learned_pref = self.memory.strategy.source_preferences.get(
                tool.liquidity_source.value, 0.5
            )
            score += learned_pref * 10
        
        # Amount-based considerations
        if goal.amount_usd > 10000:
            if "large_amounts" in tool.best_for:
                score += 10
            if tool.cost_model == "fixed_spread":
                score += 10  # Fixed spread better for large amounts
        
        return score


class AgentPlanner:
    """
    Autonomous planner for RemitAgent.
    Interprets goals, selects tools, and generates execution plans.
    """
    
    def __init__(self, memory=None):
        self.memory = memory
        self.tool_registry = ToolRegistry(memory)
    
    def interpret_goal(
        self, 
        intent: str, 
        corridor: str, 
        amount: float,
        **kwargs
    ) -> Goal:
        """
        Interpret the agent's goal from natural intent.
        
        Args:
            intent: Natural language intent (e.g., "maximize savings on EUR corridor")
            corridor: Trading pair (e.g., "cUSD-cEUR")
            amount: Trade amount in USD
            **kwargs: Additional constraints
            
        Returns:
            Structured Goal object
        """
        # Parse objective from intent
        objective = "maximize_savings"  # Default
        
        if any(word in intent.lower() for word in ["fast", "quick", "speed", "time"]):
            objective = "minimize_time"
        elif any(word in intent.lower() for word in ["slippage", "exact", "precise"]):
            objective = "minimize_slippage"
        elif any(word in intent.lower() for word in ["cheap", "save", "saving", "cost"]):
            objective = "maximize_savings"
        
        # Extract constraints
        constraints = {
            "max_slippage": kwargs.get("max_slippage", 0.5),
            "deadline_hours": kwargs.get("deadline_hours", 24),
            "require_confirmation": kwargs.get("require_confirmation", False),
            "priority": kwargs.get("priority", "normal")
        }
        
        return Goal(
            original_intent=intent,
            corridor=corridor,
            amount_usd=amount,
            primary_objective=objective,
            constraints=constraints,
            deadline=kwargs.get("deadline")
        )
    
    def generate_plan(
        self, 
        goal: Goal,
        market_data: Dict[str, Any],
        risk_profile: Dict[str, Any]
    ) -> Plan:
        """
        Generate an execution plan for a given goal.
        
        Args:
            goal: The interpreted goal
            market_data: Current market conditions
            risk_profile: Current risk assessment
            
        Returns:
            A Plan with selected tools and expected outcomes
        """
        logger.info(f"[PLAN] Generating plan for goal: {goal.original_intent}")
        
        # Step 1: Rank available tools
        ranked_tools = self.tool_registry.rank_tools_for_goal(goal)
        
        if not ranked_tools:
            return self._create_wait_plan(goal, "No suitable tools available")
        
        # Step 2: Select best tool
        best_tool, best_score = ranked_tools[0]
        
        # Step 3: Check if opportunity exists
        opportunity = market_data.get("opportunity", {})
        spread_percent = opportunity.get("spread_percent", 0)
        threshold = market_data.get("adaptive_threshold", 0.5)
        
        # Step 4: Generate plan based on conditions
        if spread_percent < threshold * 0.5:
            return self._create_wait_plan(
                goal, 
                f"Spread ({spread_percent:.2f}%) too low vs threshold ({threshold:.2f}%)",
                alternatives=[{"tool": t.name, "score": s} for t, s in ranked_tools[:3]]
            )
        
        # Step 5: Build execution plan
        if best_score < 30:
            return self._create_investigate_plan(goal, market_data, ranked_tools)
        
        return self._create_execution_plan(
            goal, best_tool, market_data, risk_profile, ranked_tools
        )
    
    def _create_execution_plan(
        self,
        goal: Goal,
        tool: Tool,
        market_data: Dict[str, Any],
        risk_profile: Dict[str, Any],
        alternatives: List[Tuple[Tool, float]]
    ) -> Plan:
        """Create an execution plan for a swap."""
        
        opportunity = market_data.get("opportunity", {})
        spread = opportunity.get("spread_percent", 0)
        
        # Determine action type
        action_map = {
            LiquiditySource.MENTO: ActionType.EXECUTE_MENTO_SWAP,
            LiquiditySource.CURVE: ActionType.EXECUTE_CURVE_SWAP,
            LiquiditySource.UNISWAP_V3: ActionType.EXECUTE_UNISWAP_V3_SWAP,
            LiquiditySource.ZEROX: ActionType.EXECUTE_0X_SWAP
        }
        primary_action = action_map.get(tool.liquidity_source, ActionType.WAIT)
        
        # Build steps
        steps = [
            {
                "step": 1,
                "action": "validate_preconditions",
                "description": "Verify balances, allowances, and gas"
            },
            {
                "step": 2,
                "action": "get_quote",
                "description": f"Get exact quote from {tool.name}",
                "tool": tool.name
            },
            {
                "step": 3,
                "action": "risk_check",
                "description": "Run final risk assessment"
            },
            {
                "step": 4,
                "action": "execute_swap",
                "description": f"Execute swap via {tool.name}",
                "tool": tool.liquidity_source.value
            },
            {
                "step": 5,
                "action": "verify_result",
                "description": "Confirm transaction and record outcome"
            }
        ]
        
        # Calculate expected outcome
        mento_rate = market_data.get("mento_rate", 0)
        fiat_rate = market_data.get("fiat_rate", 0)
        traditional_cost = 0.05  # 5% typical remittance fee
        
        if mento_rate > 0 and fiat_rate > 0:
            mento_premium = (mento_rate - fiat_rate) / fiat_rate
            traditional_effective = fiat_rate * (1 - traditional_cost)
            savings_vs_traditional = (traditional_effective - mento_rate) / traditional_effective
        else:
            savings_vs_traditional = 0
        
        expected_outcome = {
            "expected_rate": mento_rate,
            "expected_savings_percent": savings_vs_traditional * 100,
            "gas_cost_estimate_usd": risk_profile.get("gas_cost_usd", 0.01),
            "execution_time_estimate_sec": 10 if tool.speed_rating >= 4 else 30,
            "confidence": "high" if spread > 1.0 else "medium"
        }
        
        # Build reasoning
        reasoning = (
            f"Selected {tool.name} as primary tool (score: {alternatives[0][1]:.1f}). "
            f"Detected spread of {spread:.2f}% vs traditional remittance cost of {traditional_cost*100:.1f}%. "
            f"Expected savings: {expected_outcome['expected_savings_percent']:.2f}%. "
            f"Tool reliability: {tool.reliability_score*100:.0f}%."
        )
        
        return Plan(
            goal=goal,
            steps=steps,
            primary_action=primary_action,
            selected_tool=tool,
            expected_outcome=expected_outcome,
            confidence_score=min(1.0, spread / 2.0),
            risk_assessment=risk_profile,
            alternatives=[
                {"tool": alt.name, "score": score, "action": action_map.get(alt.liquidity_source).value}
                for alt, score in alternatives[1:3]
            ],
            reasoning=reasoning
        )
    
    def _create_wait_plan(
        self, 
        goal: Goal, 
        reason: str,
        alternatives: Optional[List[Dict]] = None
    ) -> Plan:
        """Create a wait plan when conditions aren't favorable."""
        return Plan(
            goal=goal,
            steps=[{
                "step": 1,
                "action": "wait",
                "description": f"Waiting: {reason}"
            }],
            primary_action=ActionType.WAIT,
            selected_tool=self.tool_registry.get_tool(LiquiditySource.MENTO),
            expected_outcome={
                "action": "wait",
                "reason": reason,
                "retry_in_seconds": 300
            },
            confidence_score=0.0,
            risk_assessment={"level": "low", "reason": "no_action"},
            alternatives=alternatives or [],
            reasoning=f"No favorable opportunity detected. {reason}"
        )
    
    def _create_investigate_plan(
        self,
        goal: Goal,
        market_data: Dict[str, Any],
        ranked_tools: List[Tuple[Tool, float]]
    ) -> Plan:
        """Create an investigation plan when more data is needed."""
        return Plan(
            goal=goal,
            steps=[
                {
                    "step": 1,
                    "action": "investigate",
                    "description": "Gather additional market data"
                },
                {
                    "step": 2,
                    "action": "reassess",
                    "description": "Re-evaluate with fresh data"
                }
            ],
            primary_action=ActionType.INVESTIGATE,
            selected_tool=ranked_tools[0][0] if ranked_tools else None,
            expected_outcome={
                "action": "gather_data",
                "data_points": ["deeper_liquidity_check", "fiat_rate_refresh", "gas_price_check"]
            },
            confidence_score=0.3,
            risk_assessment={"level": "unknown", "reason": "insufficient_data"},
            alternatives=[],
            reasoning="Tool scores too low for confident execution. Investigating further."
        )
