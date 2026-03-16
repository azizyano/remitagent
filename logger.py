"""
Structured logging configuration for RemitAgent.
Outputs JSON logs for hackathon demo and human-readable logs for development.
"""
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional

import colorlog
from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields for hackathon demo."""
    
    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]) -> None:
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        
        # Add timestamp
        log_record['timestamp'] = datetime.utcnow().isoformat()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name
        
        # Add agent-specific fields for hackathon
        log_record['agent_version'] = '1.0.0'
        log_record['network'] = 'celo-mainnet'


def setup_logger(name: str = "remitagent", json_mode: bool = False) -> logging.Logger:
    """
    Set up a logger with structured formatting.
    
    Args:
        name: Logger name
        json_mode: If True, output JSON logs; otherwise, colored console logs
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    logger.handlers = []
    
    if json_mode:
        # JSON formatter for production/demo
        formatter = CustomJsonFormatter('%(timestamp)s %(level)s %(name)s %(message)s')
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
    else:
        # Colored formatter for development
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s | %(levelname)-8s | %(name)s | %(message)s%(reset)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return logger


# Create default logger
logger = setup_logger()


def log_opportunity(opportunity: Dict[str, Any]) -> None:
    """Log an arbitrage opportunity in a structured format."""
    logger.info(
        f"💰 Opportunity detected: {opportunity['pair']} | "
        f"Spread: {opportunity['spread_percent']:.2f}% | "
        f"Direction: {opportunity['direction']} | "
        f"Profit: ${opportunity.get('profit_usd', 0):.2f}"
    )


def log_trade_executed(tx_hash: str, pair: str, amount: float, savings: float) -> None:
    """Log a successful trade execution."""
    explorer_url = f"https://celoscan.io/tx/{tx_hash}"
    logger.info(
        f"✅ Trade executed: {pair} | "
        f"Amount: ${amount:.2f} | "
        f"Savings: ${savings:.2f} | "
        f"Tx: {explorer_url}"
    )


def log_trade_failed(error: str, pair: str, amount: float) -> None:
    """Log a failed trade execution."""
    logger.error(
        f"❌ Trade failed: {pair} | "
        f"Amount: ${amount:.2f} | "
        f"Error: {error}"
    )


def log_daily_summary(opportunities_seen: int, trades_executed: int, total_savings: float) -> None:
    """Log daily summary statistics."""
    logger.info(
        f"📊 Daily Summary | "
        f"Opportunities: {opportunities_seen} | "
        f"Trades: {trades_executed} | "
        f"Total Savings: ${total_savings:.2f}"
    )


def log_risk_check_failed(check_name: str, reason: str) -> None:
    """Log a failed risk check."""
    logger.warning(f"🛡️ Risk check failed: {check_name} | Reason: {reason}")


def log_emergency_stop() -> None:
    """Log emergency stop activation."""
    logger.critical("🚨 EMERGENCY STOP ACTIVATED - Agent halted")
