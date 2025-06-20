from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime


class CandleData(BaseModel):
    """Single candle data point"""
    timestamp: datetime = Field(description="Candle timestamp")
    open: float = Field(description="Opening price")
    high: float = Field(description="Highest price")
    low: float = Field(description="Lowest price")
    close: float = Field(description="Closing price")
    volume: float = Field(description="Trading volume")


class CandlesResponse(BaseModel):
    """Response for candles data"""
    candles: List[CandleData] = Field(description="List of candle data")


class ActiveFeedInfo(BaseModel):
    """Information about an active market data feed"""
    connector: str = Field(description="Connector name")
    trading_pair: str = Field(description="Trading pair")
    interval: str = Field(description="Candle interval")
    last_access: datetime = Field(description="Last access time")
    expires_at: datetime = Field(description="Expiration time")


class ActiveFeedsResponse(BaseModel):
    """Response for active market data feeds"""
    feeds: List[ActiveFeedInfo] = Field(description="List of active feeds")


class MarketDataSettings(BaseModel):
    """Market data configuration settings"""
    cleanup_interval: int = Field(description="Cleanup interval in seconds")
    feed_timeout: int = Field(description="Feed timeout in seconds")
    description: str = Field(description="Settings description")


class TradingRulesResponse(BaseModel):
    """Response for trading rules"""
    trading_pairs: Dict[str, Dict[str, Any]] = Field(description="Trading rules by pair")


class SupportedOrderTypesResponse(BaseModel):
    """Response for supported order types"""
    connector: str = Field(description="Connector name")
    supported_order_types: List[str] = Field(description="List of supported order types")