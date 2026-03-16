"""
Main entry point for RemitAgent.
CLI interface for running the autonomous agent.
"""
import argparse
import asyncio
import sys
from typing import Optional

import uvicorn

from config import config
from logger import logger
from src.core.agent import RemitAgent
from src.api.dashboard import create_app


def create_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="RemitAgent - Autonomous remittance optimization for Celo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start autonomous monitoring
  python main.py --mode monitor
  
  # Single check on a pair
  python main.py --mode single --pair cUSD-cEUR --amount 100
  
  # Run backtest
  python main.py --mode backtest --days 7
  
  # Start dashboard only
  python main.py --mode dashboard --port 8000
        """
    )
    
    parser.add_argument(
        "--mode",
        type=str,
        choices=["monitor", "single", "backtest", "dashboard"],
        default="monitor",
        help="Operation mode (default: monitor)"
    )
    
    parser.add_argument(
        "--pair",
        type=str,
        help="Trading pair for single mode (e.g., cUSD-cEUR)"
    )
    
    parser.add_argument(
        "--amount",
        type=float,
        default=100.0,
        help="Trade amount for single mode (default: 100)"
    )
    
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days for backtest (default: 7)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for dashboard (default: 8000)"
    )
    
    parser.add_argument(
        "--threshold",
        type=float,
        help="Override spread threshold percentage"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate without executing trades"
    )
    
    return parser


async def run_monitor_mode(agent: RemitAgent):
    """Run the agent in continuous monitoring mode."""
    try:
        await agent.monitoring_loop()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping...")
        await agent.stop()


async def run_single_mode(agent: RemitAgent, pair: str, amount: float):
    """Run a single check on a pair."""
    logger.info(f"Running single check: {pair} with amount ${amount}")
    
    try:
        result = await agent.single_check(pair, amount)
        
        print("\n" + "="*60)
        print(f"ANALYSIS RESULT FOR {pair}")
        print("="*60)
        print(f"Goal:            {result['goal']['objective']}")
        print(f"Action:          {result['plan']['action']}")
        print(f"Tool:            {result['plan']['tool']}")
        print(f"Confidence:      {result['plan']['confidence']:.2f}")
        
        # Get market data
        market = result.get('market_data', {})
        opp = market.get('opportunity', {})
        if opp:
            print(f"Spread:          {opp.get('spread_percent', 0):.2f}%")
        
        print("\nRates:")
        rates = market.get('rates', {})
        for source, rate in rates.items():
            if rate:
                print(f"  {source:15} {rate:.6f}")
        
        print(f"\nReasoning:       {result['plan']['reasoning'][:80]}...")
        print("="*60)
        
        return result
        
    except Exception as e:
        logger.error(f"Single check failed: {e}")
        raise


async def run_backtest_mode(agent: RemitAgent, days: int):
    """Run historical backtest."""
    logger.info(f"Running backtest for {days} days...")
    
    try:
        results = await agent.backtest(days)
        
        print("\n" + "="*60)
        print(f"📊 BACKTEST RESULTS ({days} days)")
        print("="*60)
        print(f"Pairs Analyzed:  {len(results['pairs_analyzed'])}")
        print(f"Opportunities:   {results['opportunities_found']}")
        print(f"Potential Savings: ${results['potential_savings']:.2f}")
        print("="*60)
        
        return results
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        raise


def run_dashboard_mode(port: int, agent: Optional[RemitAgent] = None):
    """Run the dashboard API server."""
    app = create_app(agent)
    
    logger.info(f"Starting dashboard on http://localhost:{port}")
    logger.info(f"API documentation: http://localhost:{port}/docs")
    
    uvicorn.run(app, host="0.0.0.0", port=port)


async def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Override threshold if provided
    if args.threshold:
        config.agent.min_spread_threshold = args.threshold
        logger.info(f"Override threshold: {args.threshold}%")
    
    # Validate config
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Create agent instance
    agent = RemitAgent()
    
    if args.dry_run:
        logger.info("[DRY RUN] No trades will be executed")
    
    try:
        if args.mode == "monitor":
            await run_monitor_mode(agent)
            
        elif args.mode == "single":
            if not args.pair:
                logger.error("--pair is required for single mode")
                sys.exit(1)
            await run_single_mode(agent, args.pair, args.amount)
            
        elif args.mode == "backtest":
            await run_backtest_mode(agent, args.days)
            
        elif args.mode == "dashboard":
            # Dashboard is synchronous (blocking)
            run_dashboard_mode(args.port, agent)
            
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    finally:
        await agent.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye! 👋")
