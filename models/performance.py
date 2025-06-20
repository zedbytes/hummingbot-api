from typing import Dict, List, Any
from pydantic import BaseModel, Field


class ExecutorInfo(BaseModel):
    """Information about an executor"""
    id: str = Field(description="Executor ID")
    trades: List[Dict[str, Any]] = Field(description="List of executor trades")
    orders: List[Dict[str, Any]] = Field(description="List of executor orders")


class PerformanceRequest(BaseModel):
    """Request for performance analysis"""
    executors: List[ExecutorInfo] = Field(description="List of executor data for analysis")


class PerformanceResults(BaseModel):
    """Performance analysis results"""
    total_pnl: float = Field(description="Total PnL")
    total_pnl_pct: float = Field(description="Total PnL percentage")
    total_volume: float = Field(description="Total trading volume")
    total_trades: int = Field(description="Total number of trades")
    win_rate: float = Field(description="Win rate percentage")
    profit_factor: float = Field(description="Profit factor")
    sharpe_ratio: float = Field(description="Sharpe ratio")
    max_drawdown: float = Field(description="Maximum drawdown")
    avg_trade_pnl: float = Field(description="Average trade PnL")


class PerformanceResponse(BaseModel):
    """Response for performance analysis"""
    executors: List[ExecutorInfo] = Field(description="Original executor data")
    results: PerformanceResults = Field(description="Performance analysis results")