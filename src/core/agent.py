"""
Main RemitAgent class - Autonomous remittance optimization agent.
Implements agentic behavior with goal interpretation, planning, and adaptation.
"""
import asyncio
import time
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, field

from config import config, TOKEN_ADDRESSES
from logger import logger, log_opportunity, log_daily_summary

from ..data.subgraph_client import SubgraphClient
from ..data.mento_client import MentoClient
from ..data.zeroex_client import ZeroXClient
from ..data.fx_oracle import FXOracle
from ..notifications.telegram_bot import TelegramNotifier
from .risk_manager import RiskManager
from .executor import TransactionExecutor
from .memory import AgentMemory, TradeExperience
from .planner import AgentPlanner, Goal, Plan, LiquiditySource
from .simulator import MentoSimulator, ProfitValidator


@dataclass
class Opportunity:
    """Represents an arbitrage opportunity."""
    pair: str
    direction: str
    spread_percent: float
    profit_usd: float
    confidence: str
    rates: Dict[str, float] = field(default_factory=dict)
    recommended_action: str = ""
    execute: bool = False
    selected_source: str = "mento"


class RemitAgent:
    """
    Autonomous agent for monitoring remittance corridors on Celo.
    
    Agentic Behavior:
    1. Goal Interpretation: Understands the objective (maximize savings, minimize time, etc.)
    2. Tool Selection: Chooses between Mento, Curve, Uniswap, 0x based on context
    3. Planning: Generates explicit execution plans via generate_plan()
    4. Self-Execution: Executes within safety bounds
    5. Adaptation: Learns from experience via adapt_strategy()
    
    Architecture: Mento-Centric
    - Primary liquidity: Mento Protocol for stable-stable swaps
    - Secondary: Curve for cUSD/USDC exits
    - Fallback: Uniswap V3 for CELO collateral moves
    """
    
    def __init__(self):
        # Configuration
        self.threshold = config.agent.min_spread_threshold
        self.interval = config.agent.check_interval_seconds
        self.pairs = self._parse_pairs(config.agent.target_pairs)
        
        # Data clients
        self.subgraph = SubgraphClient()
        self.mento = MentoClient()
        self.zerox = ZeroXClient()
        self.fx_oracle = FXOracle()
        
        # Core components
        self.risk_manager = RiskManager()
        self.executor = TransactionExecutor()
        
        # Simulation components
        self.simulator = MentoSimulator()
        self.profit_validator = ProfitValidator()
        
        # Agentic components
        self.memory = AgentMemory()
        self.planner = AgentPlanner(self.memory)
        
        # Notification component
        self.notifier = TelegramNotifier()
        
        # Register callbacks for remote control
        self.notifier.register_stop_callback(self._handle_trading_pause)
        self.notifier.register_resume_callback(self._handle_trading_resume)
        self.notifier.register_status_callback(self.get_status)
        
        # Current plan and state
        self.current_plan: Optional[Plan] = None
        self.last_adaptation: Optional[datetime] = None
        self._trading_paused = False
        
        # Statistics
        self.stats = {
            "opportunities_seen": 0,
            "trades_executed": 0,
            "total_savings": 0.0,
            "last_check": None,
            "plans_generated": 0,
            "strategies_adapted": 0
        }
        
        self._running = False
    
    def _parse_pairs(self, pairs_list: List[str]) -> List[Dict[str, str]]:
        """Parse target pairs from config."""
        parsed = []
        for pair_str in pairs_list:
            parts = pair_str.strip().split("-")
            if len(parts) == 2:
                parsed.append({
                    "token_in": parts[0].strip(),
                    "token_out": parts[1].strip(),
                    "pair_str": pair_str.strip()
                })
        return parsed
    
    async def monitoring_loop(self):
        """
        Main autonomous monitoring loop with agentic behavior.
        
        Each iteration:
        1. Analyze market conditions
        2. Generate plan via generate_plan()
        3. Execute or wait based on plan
        4. Adapt strategy periodically via adapt_strategy()
        """
        logger.info(f"Starting RemitAgent - Autonomous Mode")
        logger.info(f"📊 Base threshold: {self.threshold}% | Interval: {self.interval}s")
        logger.info(f"🎯 Pairs: {[p['pair_str'] for p in self.pairs]}")
        logger.info(f"Memory: {len(self.memory.experiences)} experiences loaded")
        
        # Send startup notification
        if self.notifier.enabled:
            await self.notifier.send_message(
                f"🚀 <b>RemitAgent Started</b>\n\n"
                f"Monitoring: {', '.join([p['pair_str'] for p in self.pairs])}\n"
                f"Threshold: {self.threshold}%\n"
                f"Interval: {self.interval}s\n\n"
                f"<b>Remote Control:</b> Send /stop or /emergency in Telegram to halt the agent immediately.\n\n"
                f"<i>Notifications are active. You'll receive alerts for opportunities and trades.</i>"
            )
            logger.info("Telegram notifications enabled")
            
            # Start command listener for remote control
            try:
                await self.notifier.start_command_listener()
            except Exception as e:
                logger.warning(f"Could not start Telegram command listener: {e}")
                logger.warning("Remote control via Telegram will not be available")
        else:
            logger.info("Telegram notifications not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)")
        
        self._running = True
        loop_count = 0
        
        while self._running:
            try:
                # Log trading status if paused
                if self._trading_paused:
                    logger.info("🛑 Trading is paused - monitoring only mode")
                
                loop_count += 1
                
                # Periodic strategy adaptation (every 10 loops)
                if loop_count % 10 == 0:
                    await self.adapt_strategy()
                
                # Daily summary (every 288 loops assuming 5-min interval = ~24 hours)
                if loop_count % 288 == 0:
                    await self.notifier.send_daily_summary(
                        opportunities_seen=self.stats["opportunities_seen"],
                        trades_executed=self.stats["trades_executed"],
                        total_savings=self.stats["total_savings"]
                    )
                
                # Check and send any pending digest notifications
                await self.notifier.check_and_send_digest()
                
                # Analyze each pair with agentic planning
                for pair in self.pairs:
                    try:
                        # Step 1: Interpret goal for this corridor
                        goal = self.planner.interpret_goal(
                            intent="maximize savings on remittance corridor",
                            corridor=pair["pair_str"],
                            amount=1000.0  # Default analysis amount
                        )
                        
                        # Step 2: Gather market data
                        market_data = await self._gather_market_data(pair)
                        
                        # Step 3: Generate plan
                        plan = self.generate_plan(goal, market_data)
                        self.current_plan = plan
                        self.stats["plans_generated"] += 1
                        
                        # Step 4: Execute or wait based on plan
                        if plan.primary_action.value == "execute_mento_swap":
                            await self._execute_plan(plan, pair)
                        elif plan.primary_action.value == "wait":
                            logger.debug(f"Waiting on {pair['pair_str']}: {plan.reasoning}")
                            
                            # Check for opportunity to notify
                            opportunity = market_data.get("opportunity", {})
                            if opportunity.get("exists", False):
                                self.stats["opportunities_seen"] += 1
                                await self.notifier.send_opportunity_alert({
                                    "pair": pair["pair_str"],
                                    "direction": opportunity.get("direction", "unknown"),
                                    "spread_percent": opportunity.get("spread_percent", 0),
                                    "confidence": "medium",
                                    "profit_usd": opportunity.get("spread_percent", 0) * 10  # Rough estimate
                                })
                        else:
                            logger.debug(f"{plan.primary_action.value} for {pair['pair_str']}")
                        
                    except Exception as e:
                        logger.error(f"Error analyzing pair {pair['pair_str']}: {e}")
                
                self.stats["last_check"] = datetime.utcnow()
                
                # Wait for next check
                await asyncio.sleep(self.interval)
                
            except asyncio.CancelledError:
                logger.info("Monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(10)
        
        logger.info("Monitoring loop stopped")
    
    async def _gather_market_data(self, pair: Dict[str, str]) -> Dict[str, Any]:
        """Gather comprehensive market data for planning."""
        token_in = pair["token_in"]
        token_out = pair["token_out"]
        pair_str = pair["pair_str"]
        
        market_data = {
            "pair": pair_str,
            "timestamp": datetime.utcnow().isoformat(),
            "adaptive_threshold": self.memory.strategy.adaptive_threshold
        }
        
        # Get Mento rate (primary)
        try:
            mento_data = await self.mento.get_mento_rate(token_in, token_out)
            market_data["mento_rate"] = mento_data["rate"]
            market_data["mento_spread"] = mento_data["spread_percent"]
        except Exception as e:
            logger.warning(f"Mento rate unavailable for {pair_str}: {e}")
            market_data["mento_rate"] = 0
        
        # Get fiat FX rate
        try:
            fiat_base = self.fx_oracle.map_stablecoin_to_fiat(token_in)
            fiat_quote = self.fx_oracle.map_stablecoin_to_fiat(token_out)
            fx_data = await self.fx_oracle.get_fiat_rate(fiat_base, fiat_quote)
            market_data["fiat_rate"] = fx_data["mid_rate"]
        except Exception as e:
            logger.warning(f"Fiat rate unavailable for {pair_str}: {e}")
            market_data["fiat_rate"] = 0
        
        # Check for opportunity
        opportunity = await self._analyze_opportunity(pair, market_data)
        market_data["opportunity"] = opportunity
        
        # Get corridor performance from memory
        corridor_perf = self.memory.get_corridor_performance(pair_str)
        if corridor_perf:
            market_data["corridor_performance"] = {
                "success_rate": corridor_perf.successful_trades / max(1, corridor_perf.total_attempts),
                "best_source": corridor_perf.best_source,
                "avg_slippage": corridor_perf.avg_slippage_percent
            }
        
        return market_data
    
    async def _analyze_opportunity(
        self, 
        pair: Dict[str, str], 
        market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze if there's a trading opportunity."""
        mento_rate = market_data.get("mento_rate", 0)
        fiat_rate = market_data.get("fiat_rate", 0)
        
        if mento_rate == 0 or fiat_rate == 0:
            return {"exists": False, "spread_percent": 0}
        
        # Calculate savings vs traditional remittance (5% cost)
        traditional_cost = 0.05
        traditional_effective = fiat_rate * (1 - traditional_cost)
        
        # Mento might be better or worse than fiat mid-market
        mento_premium = (mento_rate - fiat_rate) / fiat_rate
        
        # Savings calculation
        savings_vs_traditional = (traditional_effective - mento_rate) / traditional_effective
        
        # Opportunity exists if Mento offers significant savings vs traditional
        opportunity_exists = savings_vs_traditional > (self.memory.strategy.adaptive_threshold / 100)
        
        return {
            "exists": opportunity_exists,
            "spread_percent": max(0, savings_vs_traditional * 100),
            "mento_premium_percent": mento_premium * 100,
            "traditional_effective_rate": traditional_effective,
            "direction": "mento_swap" if opportunity_exists else "no_opportunity"
        }
    
    def generate_plan(
        self, 
        goal: Goal, 
        market_data: Dict[str, Any]
    ) -> Plan:
        """
        Generate an execution plan for the given goal.
        
        This is the core agentic method that:
        1. Evaluates available tools (Mento, Curve, Uniswap, 0x)
        2. Selects the optimal tool based on goal and market conditions
        3. Generates a step-by-step execution plan
        4. Provides confidence score and risk assessment
        
        Args:
            goal: The interpreted goal from interpret_goal()
            market_data: Current market conditions
            
        Returns:
            Plan object with selected tool and execution steps
        """
        # Get risk profile
        risk_profile = {
            "level": "medium",
            "gas_cost_usd": 0.01,  # Celo is cheap
            "max_slippage": self.memory.strategy.max_slippage_tolerance
        }
        
        # Generate plan using planner
        plan = self.planner.generate_plan(goal, market_data, risk_profile)
        
        logger.info(f"Plan generated for {goal.corridor}:")
        logger.info(f"   Action: {plan.primary_action.value}")
        logger.info(f"   Tool: {plan.selected_tool.name if plan.selected_tool else 'N/A'}")
        logger.info(f"   Confidence: {plan.confidence_score:.2f}")
        
        return plan
    
    async def adapt_strategy(self):
        """
        Adapt strategy based on accumulated experience.
        
        This is the learning component of the agent. It:
        1. Analyzes recent trade performance
        2. Adjusts thresholds based on success rates
        3. Updates source preferences based on outcomes
        4. Modifies timing parameters
        
        Called periodically during the monitoring loop.
        """
        logger.info("Adapting strategy based on experience...")
        
        try:
            strategy = self.memory.strategy
            changes_made = []
            
            # 1. Adapt threshold based on success rate
            success_rate = self.memory.get_success_rate(hours=168)  # Last week
            recent_exps = self.memory.get_recent_experiences(hours=24)
            recent_spreads = [e.expected_savings_percent for e in recent_exps if e.success]
            
            if strategy.adapt_threshold(success_rate, recent_spreads):
                changes_made.append(
                    f"threshold: {strategy.adaptive_threshold:.2f}%"
                )
            
            # 2. Adjust source preferences based on performance
            for source in ["mento", "curve", "uniswap_v3", "0x"]:
                source_exps = [e for e in recent_exps if e.source == source]
                if len(source_exps) >= 3:
                    success_count = sum(1 for e in source_exps if e.success)
                    rate = success_count / len(source_exps)
                    
                    if rate > 0.8:
                        strategy.adjust_source_preference(source, "success")
                        changes_made.append(f"{source}: preference increased")
                    elif rate < 0.5:
                        strategy.adjust_source_preference(source, "failure")
                        changes_made.append(f"{source}: preference decreased")
                    
                    # Check for high slippage
                    avg_slippage = sum(e.slippage_percent for e in source_exps) / len(source_exps)
                    if avg_slippage > 1.0:
                        strategy.adjust_source_preference(source, "high_slippage")
                        changes_made.append(f"{source}: reduced due to slippage")
            
            # 3. Adapt check interval based on opportunity frequency
            if len(recent_exps) > 20:
                # Many opportunities - check more frequently
                strategy.optimal_check_interval = max(60, strategy.optimal_check_interval - 30)
                changes_made.append(f"check_interval: {strategy.optimal_check_interval}s")
            elif len(recent_exps) < 5:
                # Few opportunities - check less frequently
                strategy.optimal_check_interval = min(600, strategy.optimal_check_interval + 30)
                changes_made.append(f"check_interval: {strategy.optimal_check_interval}s")
            
            # 4. Record adaptation
            strategy.last_adaptation = datetime.utcnow().isoformat()
            strategy.adaptation_history.append({
                "timestamp": strategy.last_adaptation,
                "success_rate": success_rate,
                "changes": changes_made.copy()
            })
            
            # Keep only last 20 adaptations
            strategy.adaptation_history = strategy.adaptation_history[-20:]
            
            # 5. Save memory
            self.memory.save()
            
            self.stats["strategies_adapted"] += 1
            self.last_adaptation = datetime.utcnow()
            
            if changes_made:
                logger.info(f"Strategy adapted: {', '.join(changes_made)}")
            else:
                logger.info("No strategy changes needed")
            
            # Log learning summary
            summary = self.memory.get_learning_summary()
            logger.info(f"Learning Summary: {summary['successful_trades']} successful, "
                       f"{summary['failed_trades']} failed, "
                       f"success rate: {summary['overall_success_rate']:.1%}")
            
        except Exception as e:
            logger.error(f"Strategy adaptation failed: {e}")
    
    async def _execute_plan(self, plan: Plan, pair: Dict[str, str]):
        """
        Execute a generated plan with simulation, validation, and execution.
        
        Flow:
        1. Pre-execution safety checks
        2. Simulate trade (eth_call, no gas)
        3. Validate profit
        4. Final safety checks
        5. Execute transaction
        6. Record outcome
        """
        pair_str = pair["pair_str"]
        amount = plan.goal.amount_usd
        
        logger.info(f"[EXECUTE] Analyzing opportunity: {pair_str} | ${amount:.2f}")
        
        # Step 1: Pre-execution safety checks
        if not await self._safety_checks(pair_str, amount):
            return
        
        # Step 2: Simulate trade (static call, no gas)
        source = plan.selected_tool.liquidity_source if plan.selected_tool else LiquiditySource.MENTO
        
        if source != LiquiditySource.MENTO:
            logger.info(f"Execution via {source.value} not yet implemented")
            return
        
        simulation = await self.simulator.simulate_swap(pair_str, amount)
        
        if not simulation.success:
            logger.warning(f"[SIMULATION] Failed for {pair_str}: {simulation.error_message}")
            await self._record_experience(pair_str, amount, source.value, False, simulation)
            return
        
        logger.info(
            f"[SIMULATION] Result: Out={simulation.amount_out:.2f} | "
            f"Profit=${simulation.net_profit_usd:.2f} | "
            f"Gas=${simulation.gas_cost_usd:.4f}"
        )
        
        # Step 3: Validate profit
        validation = self.profit_validator.validate_trade(simulation, pair_str, amount)
        
        logger.info(f"[VALIDATION] {validation['reason']}")
        
        if not validation['should_execute']:
            logger.info(f"[REJECTED] Trade rejected: {validation['reason']}")
            return
        
        # Step 4: Final safety checks before execution
        if not await self._final_safety_checks(pair_str, amount, simulation):
            return
        
        # Step 5: Execute transaction
        logger.info(f"[EXECUTE] Executing trade: {pair_str} | Confidence: {validation['confidence']:.2f}")
        
        start_time = time.time()
        
        try:
            # Execute Mento swap
            result = await self._execute_mento_swap_with_simulation(pair, simulation)
            
            execution_time = int((time.time() - start_time) * 1000)
            
            # Invalidate simulation cache
            self.simulator.invalidate_cache(pair_str)
            
            # Record success
            await self._record_experience(
                pair_str, amount, source.value, True, simulation, 
                execution_time=execution_time, tx_hash=result.get("tx_hash")
            )
            
            self.stats["trades_executed"] += 1
            self.stats["total_savings"] += simulation.net_profit_usd
            logger.info(f"[SUCCESS] Trade executed: {result.get('tx_hash')}")
            
            # Send Telegram notification
            await self.notifier.send_trade_executed(
                tx_hash=result.get("tx_hash"),
                pair=pair_str,
                amount=amount,
                savings=simulation.net_profit_usd
            )
            
        except Exception as e:
            logger.error(f"[FAILED] Trade failed: {pair_str} | Error: {e}")
            
            execution_time = int((time.time() - start_time) * 1000)
            
            await self._record_experience(
                pair_str, amount, source.value, False, simulation,
                execution_time=execution_time, error=str(e)
            )
            
            # Send Telegram notification for failed trade
            await self.notifier.send_trade_failed(
                error=str(e),
                pair=pair_str,
                amount=amount
            )
    
    async def _safety_checks(self, pair: str, amount: float) -> bool:
        """Pre-execution safety checks."""
        # Check if trading is paused (via Telegram command)
        if self._trading_paused:
            logger.warning("[SAFETY] Trading is paused - skipping execution")
            return False
        
        # Check emergency stop file
        if config.is_emergency_stop():
            logger.warning("[SAFETY] Emergency stop file exists - skipping execution")
            return False
        
        # Check if wallet is configured
        if not config.celo.wallet_address or not config.celo.private_key:
            logger.error("[SAFETY] Wallet not configured for execution")
            return False
        
        # Check trade size limits
        if amount > config.safety.max_trade_size_usd:
            logger.warning(f"[SAFETY] Trade size ${amount} exceeds max ${config.safety.max_trade_size_usd}")
            return False
        
        return True
    
    async def _final_safety_checks(self, pair: str, amount: float, simulation) -> bool:
        """Final safety checks before real execution."""
        # Check wallet balance
        token_in = pair.split("-")[0]
        token_addr = TOKEN_ADDRESSES[token_in]["address"]
        balance = await self.executor.check_balance(token_addr)
        decimals = TOKEN_ADDRESSES[token_in]["decimals"]
        balance_human = balance / (10 ** decimals)
        
        if balance_human < amount:
            logger.error(f"[SAFETY] Insufficient balance: {balance_human:.2f} < {amount:.2f}")
            return False
        
        # Check gas price
        gas_price = self.executor.w3.eth.gas_price
        gas_price_gwei = self.executor.w3.from_wei(gas_price, 'gwei')
        
        if gas_price_gwei > 1.0:  # 1 gwei is high for Celo
            logger.warning(f"[SAFETY] Gas price high: {gas_price_gwei:.2f} gwei, delaying")
            return False
        
        # Check for pending transactions
        try:
            nonce = self.executor.w3.eth.get_transaction_count(config.celo.wallet_address)
            pending_nonce = self.executor.w3.eth.get_transaction_count(config.celo.wallet_address, 'pending')
            
            if pending_nonce > nonce:
                logger.warning(f"[SAFETY] Has {pending_nonce - nonce} pending transaction(s)")
                return False
        except Exception as e:
            logger.warning(f"[SAFETY] Could not check pending transactions: {e}")
        
        logger.info("[SAFETY] All safety checks passed")
        return True
    
    async def _record_experience(
        self, 
        pair: str, 
        amount: float, 
        source: str, 
        success: bool,
        simulation,
        execution_time: int = 0,
        tx_hash: str = None,
        error: str = None
    ):
        """Record trade experience to memory."""
        experience = TradeExperience(
            timestamp=datetime.utcnow().isoformat(),
            pair=pair,
            direction="buy",
            source=source,
            amount_usd=amount,
            expected_rate=simulation.amount_out / amount if amount > 0 else 0,
            actual_rate=simulation.amount_out / amount if amount > 0 else 0,
            expected_savings_percent=simulation.profit_percent,
            gas_cost_usd=simulation.gas_cost_usd,
            slippage_percent=0,
            success=success,
            execution_time_ms=execution_time,
            market_conditions={
                "expected_amount_out": simulation.amount_out,
                "tx_hash": tx_hash
            },
            error_reason=error
        )
        
        self.memory.record_experience(experience)
    
    async def _execute_mento_swap_with_simulation(
        self, 
        pair: Dict[str, str], 
        simulation
    ) -> Dict[str, Any]:
        """Execute Mento swap using simulation data."""
        pair_str = pair["pair_str"]
        
        # Calculate min amount out with slippage
        slippage_tolerance = 0.005  # 0.5%
        min_amount_out = simulation.amount_out * (1 - slippage_tolerance)
        
        # Get amount from plan or use default
        amount_in = 100  # Default 100 units, would come from plan
        
        # Prepare hops data for composite swaps
        hops = None
        if getattr(simulation, 'is_composite', False) and simulation.hops:
            # Convert hop results to executor format
            hops = []
            for hop in simulation.hops:
                hops.append({
                    "pair": f"{hop.token_in}-{hop.token_out}" if hasattr(hop, 'token_in') else None,
                    "amount_in": hop.amount_in if hasattr(hop, 'amount_in') else amount_in,
                    "min_amount_out": hop.amount_out * 0.995 if hasattr(hop, 'amount_out') else 0,
                    "exchange_provider": hop.exchange_provider if hasattr(hop, 'exchange_provider') else simulation.exchange_provider,
                    "expected_amount_out": hop.amount_out if hasattr(hop, 'amount_out') else 0
                })
        
        # Execute swap (direct or composite)
        return await self.executor.execute_mento_swap(
            pair=pair_str,
            amount_in=amount_in,
            min_amount_out=min_amount_out,
            exchange_provider=simulation.exchange_provider,
            exchange_id=b'\x00' * 32,  # Placeholder - should get actual exchange ID
            slippage_percent=slippage_tolerance * 100,
            is_composite=getattr(simulation, 'is_composite', False),
            hops=hops
        )
    
    async def _execute_mento_swap(self, pair: Dict[str, str], plan: Plan) -> str:
        """Execute a swap through Mento."""
        token_in = pair["token_in"]
        token_out = pair["token_out"]
        
        # Get quote
        decimals = TOKEN_ADDRESSES[token_in]["decimals"]
        amount_in = int(100 * (10 ** decimals))  # Start with 100 units
        
        mento_data = await self.mento.get_mento_rate(token_in, token_out, amount_in)
        expected_out = mento_data["amount_out"]
        
        # Calculate min out with slippage
        min_amount_out = self.risk_manager.calculate_min_amount_out(
            amount_in / (10 ** decimals),
            expected_out / (10 ** TOKEN_ADDRESSES[token_out]["decimals"]),
            TOKEN_ADDRESSES[token_out]["decimals"]
        )
        
        # Execute
        tx_hash = await self.executor.execute_mento_swap(
            amount_in, token_in, token_out, min_amount_out, self.mento
        )
        
        self.risk_manager.record_trade(pair["pair_str"])
        
        return tx_hash
    
    async def single_check(self, pair_str: str, amount: float) -> Dict[str, Any]:
        """
        Run a single check on a specific pair with full agentic analysis.
        
        Args:
            pair_str: Pair string like "cUSD-cEUR"
            amount: Trade amount
            
        Returns:
            Analysis result including plan
        """
        parts = pair_str.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid pair format: {pair_str}")
        
        pair = {
            "token_in": parts[0],
            "token_out": parts[1],
            "pair_str": pair_str
        }
        
        # Interpret goal
        goal = self.planner.interpret_goal(
            intent="analyze opportunity",
            corridor=pair_str,
            amount=amount
        )
        
        # Gather data
        market_data = await self._gather_market_data(pair)
        
        # Generate plan
        plan = self.generate_plan(goal, market_data)
        
        return {
            "pair": pair_str,
            "goal": {
                "intent": goal.original_intent,
                "objective": goal.primary_objective
            },
            "plan": {
                "action": plan.primary_action.value,
                "tool": plan.selected_tool.name if plan.selected_tool else None,
                "confidence": plan.confidence_score,
                "reasoning": plan.reasoning,
                "expected_outcome": plan.expected_outcome,
                "steps": plan.steps
            },
            "market_data": market_data,
            "alternative_tools": plan.alternatives
        }
    
    async def backtest(self, days: int = 7) -> Dict[str, Any]:
        """Run historical analysis with agentic evaluation."""
        logger.info(f"Running agentic backtest for {days} days...")
        
        # This would query historical data
        # For now, return learning summary
        learning_summary = self.memory.get_learning_summary()
        
        return {
            "period_days": days,
            "pairs_analyzed": [p["pair_str"] for p in self.pairs],
            "learning_summary": learning_summary,
            "current_strategy": {
                "adaptive_threshold": self.memory.strategy.adaptive_threshold,
                "source_preferences": self.memory.strategy.source_preferences,
                "check_interval": self.memory.strategy.optimal_check_interval
            },
            "opportunities_found": learning_summary["successful_trades"],
            "potential_savings": 0.0  # Would calculate from history
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current agent status including agentic state."""
        return {
            "running": self._running,
            "trading_paused": self._trading_paused,
            "threshold": self.threshold,
            "adaptive_threshold": self.memory.strategy.adaptive_threshold,
            "interval": self.interval,
            "pairs": [p["pair_str"] for p in self.pairs],
            "stats": self.stats,
            "current_plan": {
                "action": self.current_plan.primary_action.value if self.current_plan else None,
                "tool": self.current_plan.selected_tool.name if self.current_plan and self.current_plan.selected_tool else None
            },
            "learning": self.memory.get_learning_summary(),
            "last_adaptation": self.last_adaptation.isoformat() if self.last_adaptation else None
        }
    
    def _handle_trading_pause(self):
        """Handle trading pause command from Telegram (stops trading but keeps monitoring)."""
        logger.critical("Trading pause command received from Telegram")
        self._trading_paused = True
    
    def _handle_trading_resume(self):
        """Handle trading resume command from Telegram (resumes trading)."""
        logger.critical("Trading resume command received from Telegram")
        self._trading_paused = False
    
    async def stop(self):
        """Stop the monitoring loop and save state."""
        self._running = False
        
        # Stop command listener
        await self.notifier.stop_command_listener()
        
        # Save memory
        self.memory.save()
        
        # Close all clients
        await self.subgraph.close()
        await self.zerox.close()
        await self.fx_oracle.close()
        
        logger.info("Agent stopped and memory saved")
    
    def print_daily_summary(self):
        """Print daily summary statistics."""
        log_daily_summary(
            self.stats["opportunities_seen"],
            self.stats["trades_executed"],
            self.stats["total_savings"]
        )
