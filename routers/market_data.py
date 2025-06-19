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


# Trading Rules Endpoints
@router.get("/trading-rules/{connector}")
async def get_all_trading_rules(request: Request, connector: str):
    """
    Get trading rules for all available trading pairs on a connector.
    
    This endpoint uses the MarketDataFeedManager to access non-trading connector instances,
    which means no authentication or account setup is required.
    
    Args:
        request: FastAPI request object
        connector: Name of the connector (e.g., 'binance', 'binance_perpetual')
        
    Returns:
        Dictionary mapping trading pairs to their trading rules
        
    Raises:
        HTTPException: 404 if connector not found, 500 for other errors
    """
    try:
        market_data_feed_manager: MarketDataFeedManager = request.app.state.market_data_feed_manager
        
        # Get trading rules for all pairs
        rules = await market_data_feed_manager.get_trading_rules(connector)
        
        if "error" in rules:
            raise HTTPException(status_code=404, detail=f"Connector '{connector}' not found or error: {rules['error']}")
        
        return rules
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving trading rules: {str(e)}")


@router.get("/trading-rules/{connector}/{trading_pair}")
async def get_trading_rules_for_pair(request: Request, connector: str, trading_pair: str):
    """
    Get trading rules for a specific trading pair on a connector.
    
    This endpoint uses the MarketDataFeedManager to access non-trading connector instances,
    which means no authentication or account setup is required.
    
    Args:
        request: FastAPI request object
        connector: Name of the connector (e.g., 'binance', 'binance_perpetual')
        trading_pair: Trading pair to get rules for (e.g., 'BTC-USDT')
        
    Returns:
        Trading rules including minimum order size, price increment, etc.
        
    Raises:
        HTTPException: 404 if connector or trading pair not found, 500 for other errors
    """
    try:
        market_data_feed_manager: MarketDataFeedManager = request.app.state.market_data_feed_manager
        
        # Get trading rules for specific pair
        rules = await market_data_feed_manager.get_trading_rules(connector, [trading_pair])
        
        if "error" in rules:
            raise HTTPException(status_code=404, detail=f"Connector '{connector}' not found or error: {rules['error']}")
        
        if trading_pair not in rules:
            raise HTTPException(status_code=404, detail=f"Trading pair '{trading_pair}' not found on {connector}")
        
        if "error" in rules[trading_pair]:
            raise HTTPException(status_code=404, detail=rules[trading_pair]["error"])
        
        return rules[trading_pair]
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving trading rules: {str(e)}")


@router.get("/supported-order-types/{connector}")
async def get_supported_order_types(request: Request, connector: str):
    """
    Get order types supported by a specific connector.
    
    This endpoint uses the MarketDataFeedManager to access non-trading connector instances,
    which means no authentication or account setup is required.
    
    Args:
        request: FastAPI request object
        connector: Name of the connector (e.g., 'binance', 'binance_perpetual')
        
    Returns:
        List of supported order types (LIMIT, MARKET, LIMIT_MAKER)
        
    Raises:
        HTTPException: 404 if connector not found, 500 for other errors
    """
    try:
        market_data_feed_manager: MarketDataFeedManager = request.app.state.market_data_feed_manager
        
        # Access connector through MarketDataProvider's _rate_sources
        connector_instance = market_data_feed_manager.market_data_provider._rate_sources.get(connector)
        
        if not connector_instance:
            raise HTTPException(status_code=404, detail=f"Connector '{connector}' not found")
        
        # Get supported order types
        if hasattr(connector_instance, 'supported_order_types'):
            order_types = [order_type.name for order_type in connector_instance.supported_order_types()]
            return {"connector": connector, "supported_order_types": order_types}
        else:
            raise HTTPException(status_code=404, detail=f"Connector '{connector}' does not support order types query")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving order types: {str(e)}")
