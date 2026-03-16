"""
FastAPI dashboard for RemitAgent.
Provides endpoints for monitoring status, opportunities, and trades.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import config
from logger import logger


# Pydantic models for API
class StatusResponse(BaseModel):
    status: str
    agent_running: bool
    threshold: float
    check_interval: int
    pairs: List[str]
    last_check: Optional[str]
    opportunities_seen: int
    trades_executed: int


class OpportunityItem(BaseModel):
    pair: str
    direction: str
    spread_percent: float
    profit_usd: float
    confidence: str
    timestamp: str
    rates: Dict[str, float]


class TradeItem(BaseModel):
    tx_hash: str
    pair: str
    amount_usd: float
    savings_usd: float
    timestamp: str
    explorer_url: str


class SimulateRequest(BaseModel):
    pair: str
    amount: float
    token_in: Optional[str] = None
    token_out: Optional[str] = None


class SimulateResponse(BaseModel):
    pair: str
    amount: float
    direction: str
    spread_percent: float
    estimated_savings: float
    confidence: str
    recommended_action: str
    rates: Dict[str, float]


class PairInfo(BaseModel):
    pair: str
    token_in: str
    token_out: str
    mento_rate: float
    uniswap_rate: Optional[float]
    fiat_rate: float
    last_updated: str


# In-memory cache for demo
_opportunities_cache: List[Dict[str, Any]] = []
_trades_cache: List[Dict[str, Any]] = []
_agent_instance = None


def create_app(agent_instance=None) -> FastAPI:
    """
    Create FastAPI application.
    
    Args:
        agent_instance: Optional RemitAgent instance for live data
        
    Returns:
        FastAPI app
    """
    global _agent_instance
    _agent_instance = agent_instance
    
    app = FastAPI(
        title="RemitAgent API",
        description="Autonomous remittance optimization agent for Celo",
        version="1.0.0"
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/", tags=["Health"])
    async def root():
        """Root endpoint - API info."""
        return {
            "name": "RemitAgent API",
            "version": "1.0.0",
            "network": "Celo Mainnet",
            "docs": "/docs"
        }
    
    @app.get("/status", response_model=StatusResponse, tags=["Status"])
    async def get_status():
        """Get current agent status."""
        if _agent_instance:
            agent_status = _agent_instance.get_status()
            return StatusResponse(
                status="active" if agent_status["running"] else "idle",
                agent_running=agent_status["running"],
                threshold=agent_status["threshold"],
                check_interval=agent_status["interval"],
                pairs=agent_status["pairs"],
                last_check=agent_status["stats"]["last_check"].isoformat() if agent_status["stats"]["last_check"] else None,
                opportunities_seen=agent_status["stats"]["opportunities_seen"],
                trades_executed=agent_status["stats"]["trades_executed"]
            )
        else:
            # Return config-based status
            return StatusResponse(
                status="standby",
                agent_running=False,
                threshold=config.agent.min_spread_threshold,
                check_interval=config.agent.check_interval_seconds,
                pairs=config.agent.target_pairs,
                last_check=None,
                opportunities_seen=0,
                trades_executed=0
            )
    
    @app.get("/opportunities", response_model=List[OpportunityItem], tags=["Opportunities"])
    async def get_opportunities(limit: int = Query(10, ge=1, le=100)):
        """
        Get list of recent opportunities.
        
        Args:
            limit: Maximum number of opportunities to return
        """
        # Return cached opportunities
        opportunities = _opportunities_cache[-limit:] if _opportunities_cache else []
        
        result = []
        for opp in opportunities:
            result.append(OpportunityItem(
                pair=opp.get("pair", ""),
                direction=opp.get("direction", ""),
                spread_percent=opp.get("spread_percent", 0),
                profit_usd=opp.get("profit_usd", 0),
                confidence=opp.get("confidence", ""),
                timestamp=opp.get("timestamp", datetime.utcnow().isoformat()),
                rates=opp.get("rates", {})
            ))
        
        return result
    
    @app.get("/trades", response_model=List[TradeItem], tags=["Trades"])
    async def get_trades(limit: int = Query(10, ge=1, le=100)):
        """
        Get history of executed trades.
        
        Args:
            limit: Maximum number of trades to return
        """
        trades = _trades_cache[-limit:] if _trades_cache else []
        
        result = []
        for trade in trades:
            result.append(TradeItem(
                tx_hash=trade.get("tx_hash", ""),
                pair=trade.get("pair", ""),
                amount_usd=trade.get("amount_usd", 0),
                savings_usd=trade.get("savings_usd", 0),
                timestamp=trade.get("timestamp", datetime.utcnow().isoformat()),
                explorer_url=f"https://celoscan.io/tx/{trade.get('tx_hash', '')}"
            ))
        
        return result
    
    @app.post("/simulate", response_model=SimulateResponse, tags=["Simulation"])
    async def simulate_trade(request: SimulateRequest):
        """
        Simulate a trade without execution (dry-run).
        
        Args:
            request: Simulation request with pair and amount
        """
        if _agent_instance:
            try:
                result = await _agent_instance.single_check(request.pair, request.amount)
                return SimulateResponse(
                    pair=result["pair"],
                    amount=result["amount"],
                    direction=result["direction"],
                    spread_percent=result["spread_percent"],
                    estimated_savings=result.get("amount", 0) * result["spread_percent"] / 100,
                    confidence=result["confidence"],
                    recommended_action=result["recommended_action"],
                    rates=result["rates"]
                )
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))
        else:
            # Mock response when no agent
            return SimulateResponse(
                pair=request.pair,
                amount=request.amount,
                direction="no_opportunity",
                spread_percent=0.0,
                estimated_savings=0.0,
                confidence="low",
                recommended_action="agent_not_running",
                rates={}
            )
    
    @app.get("/pairs", response_model=List[PairInfo], tags=["Pairs"])
    async def get_pairs():
        """Get supported pairs with current rates."""
        pairs = []
        
        for pair_str in config.agent.target_pairs:
            parts = pair_str.split("-")
            if len(parts) == 2:
                pairs.append(PairInfo(
                    pair=pair_str,
                    token_in=parts[0],
                    token_out=parts[1],
                    mento_rate=0.0,  # Would fetch live
                    uniswap_rate=None,
                    fiat_rate=0.0,
                    last_updated=datetime.utcnow().isoformat()
                ))
        
        return pairs
    
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    return app


def cache_opportunity(opportunity: Dict[str, Any]):
    """Cache an opportunity for API retrieval."""
    opportunity["timestamp"] = datetime.utcnow().isoformat()
    _opportunities_cache.append(opportunity)
    
    # Keep only last 100
    if len(_opportunities_cache) > 100:
        _opportunities_cache.pop(0)


def cache_trade(trade: Dict[str, Any]):
    """Cache a trade for API retrieval."""
    trade["timestamp"] = datetime.utcnow().isoformat()
    _trades_cache.append(trade)
    
    # Keep only last 100
    if len(_trades_cache) > 100:
        _trades_cache.pop(0)
