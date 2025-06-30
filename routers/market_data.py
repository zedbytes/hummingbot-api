import asyncio
from typing import Dict, List, Optional

from fastapi import APIRouter, Request, HTTPException
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig, HistoricalCandlesConfig
from services.market_data_feed_manager import MarketDataFeedManager

router = APIRouter(tags=["Market"], prefix="/market-data")


@router.post("/candles")
async def get_candles(request: Request, candles_config: CandlesConfig):
    """
    Get real-time candles data for a specific trading pair.
    
    This endpoint uses the MarketDataProvider to get or create a candles feed that will
    automatically start and maintain real-time updates. Subsequent requests with the same
    configuration will reuse the existing feed for up-to-date data.
    
    Args:
        request: FastAPI request object
        candles_config: Configuration for the candles including connector, trading_pair, interval, and max_records
        
    Returns:
        Real-time candles data or error message
    """
    try:
        market_data_feed_manager: MarketDataFeedManager = request.app.state.market_data_feed_manager
        
        # Get or create the candles feed (this will start it automatically and track access time)
        candles_feed = market_data_feed_manager.get_candles_feed(candles_config)
        
        # Wait for the candles feed to be ready
        while not candles_feed.ready:
            await asyncio.sleep(0.1)
        
        # Get the candles dataframe
        df = candles_feed.candles_df
        
        if df is not None and not df.empty:
            # Limit to requested max_records and remove duplicates
            df = df.tail(candles_config.max_records)
            df = df.drop_duplicates(subset=["timestamp"], keep="last")
            # Convert to dict for JSON serialization
            return df.to_dict(orient="records")
        else:
            return {"error": "No candles data available"}
            
    except Exception as e:
        return {"error": str(e)}


@router.post("/historical-candles")
async def get_historical_candles(request: Request, config: HistoricalCandlesConfig):
    """
    Get historical candles data for a specific trading pair.
    
    Args:
        config: Configuration for historical candles including connector, trading pair, interval, start and end time
        
    Returns:
        Historical candles data or error message
    """
    try:
        market_data_feed_manager: MarketDataFeedManager = request.app.state.market_data_feed_manager
        
        # Create candles config from historical config
        candles_config = CandlesConfig(
            connector=config.connector_name,
            trading_pair=config.trading_pair,
            interval=config.interval
        )
        
        # Get or create the candles feed (this will track access time)
        candles = market_data_feed_manager.get_candles_feed(candles_config)
        
        # Fetch historical candles
        historical_data = await candles.get_historical_candles(config=config)
        
        if historical_data is not None and not historical_data.empty:
            # Convert to dict for JSON serialization
            return historical_data.to_dict(orient="records")
        else:
            return {"error": "No historical data available"}
            
    except Exception as e:
        return {"error": str(e)}


@router.get("/active-feeds")
async def get_active_feeds(request: Request):
    """
    Get information about currently active market data feeds.
    
    Args:
        request: FastAPI request object to access application state
        
    Returns:
        Dictionary with active feeds information including last access times and expiration
    """
    try:
        market_data_feed_manager: MarketDataFeedManager = request.app.state.market_data_feed_manager
        return market_data_feed_manager.get_active_feeds_info()
    except Exception as e:
        return {"error": str(e)}


@router.get("/settings")
async def get_market_data_settings():
    """
    Get current market data settings for debugging.
    
    Returns:
        Dictionary with current market data configuration including cleanup and timeout settings
    """
    from config import settings
    return {
        "cleanup_interval": settings.market_data.cleanup_interval,
        "feed_timeout": settings.market_data.feed_timeout,
        "description": "cleanup_interval: seconds between cleanup runs, feed_timeout: seconds before unused feeds expire"
    }


