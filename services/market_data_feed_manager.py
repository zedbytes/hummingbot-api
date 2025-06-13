import asyncio
import time
from typing import Dict, Optional, Any, Callable, List, Set
import logging
from enum import Enum
from decimal import Decimal

from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.data_feed.market_data_provider import MarketDataProvider


class FeedType(Enum):
    """Types of market data feeds that can be managed."""
    CANDLES = "candles"
    ORDER_BOOK = "order_book"
    TRADES = "trades"
    TICKER = "ticker"


class MarketDataFeedManager:
    """
    Generic manager for market data feeds lifecycle with automatic cleanup.
    
    This service wraps the MarketDataProvider and tracks when any type of market data feed
    is last accessed. Feeds that haven't been accessed within the specified timeout period 
    are automatically stopped and cleaned up.
    """
    
    def __init__(self, market_data_provider: MarketDataProvider, cleanup_interval: int = 300, feed_timeout: int = 600):
        """
        Initialize the MarketDataFeedManager.
        
        Args:
            market_data_provider: The underlying MarketDataProvider instance
            cleanup_interval: How often to run cleanup (seconds, default: 5 minutes)
            feed_timeout: How long to keep unused feeds alive (seconds, default: 10 minutes)
        """
        self.market_data_provider = market_data_provider
        self.cleanup_interval = cleanup_interval
        self.feed_timeout = feed_timeout
        self.last_access_times: Dict[str, float] = {}
        self.feed_configs: Dict[str, tuple] = {}  # Store feed configs for cleanup
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_running = False
        self.logger = logging.getLogger(__name__)
        
        # Registry of cleanup functions for different feed types
        self._cleanup_functions: Dict[FeedType, Callable] = {
            FeedType.CANDLES: self._cleanup_candle_feed,
            FeedType.ORDER_BOOK: self._cleanup_order_book_feed,
            # Add more feed types as needed
        }
        
    def start(self):
        """Start the cleanup background task."""
        if not self._is_running:
            self._is_running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.logger.info(f"MarketDataFeedManager started with cleanup_interval={self.cleanup_interval}s, feed_timeout={self.feed_timeout}s")
    
    def stop(self):
        """Stop the cleanup background task and all feeds."""
        self._is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None
        
        # Stop all feeds managed by the MarketDataProvider
        self.market_data_provider.stop()
        self.last_access_times.clear()
        self.feed_configs.clear()
        self.logger.info("MarketDataFeedManager stopped")
    
    def get_candles_feed(self, config: CandlesConfig):
        """
        Get a candles feed and update its last access time.
        
        Args:
            config: CandlesConfig for the desired feed
            
        Returns:
            Candle feed instance
        """
        feed_key = self._generate_feed_key(FeedType.CANDLES, config.connector, config.trading_pair, config.interval)
        
        # Update last access time and store config for cleanup
        self.last_access_times[feed_key] = time.time()
        self.feed_configs[feed_key] = (FeedType.CANDLES, config)
        
        # Get the feed from MarketDataProvider
        feed = self.market_data_provider.get_candles_feed(config)
        
        self.logger.debug(f"Accessed candle feed: {feed_key}")
        return feed
    
    def get_candles_df(self, connector_name: str, trading_pair: str, interval: str, max_records: int = 500):
        """
        Get candles dataframe and update access time.
        
        Args:
            connector_name: The connector name
            trading_pair: The trading pair
            interval: The candle interval
            max_records: Maximum number of records
            
        Returns:
            Candles dataframe
        """
        config = CandlesConfig(
            connector=connector_name,
            trading_pair=trading_pair,
            interval=interval,
            max_records=max_records
        )
        
        feed_key = self._generate_feed_key(FeedType.CANDLES, connector_name, trading_pair, interval)
        self.last_access_times[feed_key] = time.time()
        self.feed_configs[feed_key] = (FeedType.CANDLES, config)
        
        # Use MarketDataProvider's convenience method
        df = self.market_data_provider.get_candles_df(connector_name, trading_pair, interval, max_records)
        
        self.logger.debug(f"Accessed candle data: {feed_key}")
        return df
    
    def get_order_book(self, connector_name: str, trading_pair: str):
        """
        Get order book and update access time.
        
        Args:
            connector_name: The connector name
            trading_pair: The trading pair
            
        Returns:
            Order book instance
        """
        feed_key = self._generate_feed_key(FeedType.ORDER_BOOK, connector_name, trading_pair)
        
        # Update last access time
        self.last_access_times[feed_key] = time.time()
        self.feed_configs[feed_key] = (FeedType.ORDER_BOOK, (connector_name, trading_pair))
        
        # Get order book from MarketDataProvider
        order_book = self.market_data_provider.get_order_book(connector_name, trading_pair)
        
        self.logger.debug(f"Accessed order book: {feed_key}")
        return order_book
    
    def get_order_book_snapshot(self, connector_name: str, trading_pair: str):
        """
        Get order book snapshot and update access time.
        
        Args:
            connector_name: The connector name
            trading_pair: The trading pair
            
        Returns:
            Tuple of bid and ask DataFrames
        """
        feed_key = self._generate_feed_key(FeedType.ORDER_BOOK, connector_name, trading_pair)
        
        # Update last access time
        self.last_access_times[feed_key] = time.time()
        self.feed_configs[feed_key] = (FeedType.ORDER_BOOK, (connector_name, trading_pair))
        
        # Get order book snapshot from MarketDataProvider
        snapshot = self.market_data_provider.get_order_book_snapshot(connector_name, trading_pair)
        
        self.logger.debug(f"Accessed order book snapshot: {feed_key}")
        return snapshot
    
    async def get_trading_rules(self, connector_name: str, trading_pairs: Optional[List[str]] = None) -> Dict[str, Dict]:
        """
        Get trading rules for specified trading pairs from a connector.
        
        Args:
            connector_name: Name of the connector
            trading_pairs: List of trading pairs to get rules for. If None, get all available.
            
        Returns:
            Dictionary mapping trading pairs to their trading rules
        """
        try:
            # Access connector through MarketDataProvider's _rate_sources LazyDict
            connector = self.market_data_provider._rate_sources[connector_name]
            
            # Update trading rules to ensure we have the latest data
            await connector._update_trading_rules()
            
            # Get trading rules
            if trading_pairs:
                # Get rules for specific trading pairs
                result = {}
                for trading_pair in trading_pairs:
                    if trading_pair in connector.trading_rules:
                        rule = connector.trading_rules[trading_pair]
                        result[trading_pair] = {
                            "min_order_size": float(rule.min_order_size),
                            "max_order_size": float(rule.max_order_size) if rule.max_order_size else None,
                            "min_price_increment": float(rule.min_price_increment),
                            "min_base_amount_increment": float(rule.min_base_amount_increment),
                            "min_notional_size": float(rule.min_notional_size),
                            "max_price_significant_digits": rule.max_price_significant_digits,
                            "max_quantity_significant_digits": rule.max_quantity_significant_digits,
                            "supports_limit_orders": rule.supports_limit_orders,
                            "supports_market_orders": rule.supports_market_orders,
                        }
                    else:
                        result[trading_pair] = {"error": f"Trading pair {trading_pair} not found"}
            else:
                # Get all trading rules
                result = {}
                for trading_pair, rule in connector.trading_rules.items():
                    result[trading_pair] = {
                        "min_order_size": float(rule.min_order_size),
                        "max_order_size": float(rule.max_order_size) if rule.max_order_size else None,
                        "min_price_increment": float(rule.min_price_increment),
                        "min_base_amount_increment": float(rule.min_base_amount_increment),
                        "min_notional_size": float(rule.min_notional_size),
                        "max_price_significant_digits": rule.max_price_significant_digits,
                        "max_quantity_significant_digits": rule.max_quantity_significant_digits,
                        "supports_limit_orders": rule.supports_limit_orders,
                        "supports_market_orders": rule.supports_market_orders,
                    }
            
            self.logger.debug(f"Retrieved trading rules for {connector_name}: {len(result)} pairs")
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting trading rules for {connector_name}: {e}")
            return {"error": str(e)}
    
    async def get_prices(self, connector_name: str, trading_pairs: List[str]) -> Dict[str, float]:
        """
        Get current prices for specified trading pairs.
        
        Args:
            connector_name: Name of the connector
            trading_pairs: List of trading pairs to get prices for
            
        Returns:
            Dictionary mapping trading pairs to their current prices
        """
        try:
            # Access connector through MarketDataProvider's _rate_sources LazyDict
            connector = self.market_data_provider._rate_sources[connector_name]
            
            # Get last traded prices
            prices = await connector.get_last_traded_prices(trading_pairs)
            
            # Convert Decimal to float for JSON serialization
            result = {pair: float(price) for pair, price in prices.items()}
            
            self.logger.debug(f"Retrieved prices for {connector_name}: {len(result)} pairs")
            return result
            
        except Exception as e:
            self.logger.error(f"Error getting prices for {connector_name}: {e}")
            return {"error": str(e)}
    
    def get_order_book_data(self, connector_name: str, trading_pair: str, depth: int = 10) -> Dict:
        """
        Get order book data using the connector's order book data source.
        
        Args:
            connector_name: Name of the connector
            trading_pair: Trading pair to get order book for
            depth: Number of bid/ask levels to return
            
        Returns:
            Dictionary containing bid and ask data
        """
        try:
            # Access connector through MarketDataProvider's _rate_sources LazyDict
            connector = self.market_data_provider._rate_sources[connector_name]
            
            # Access the order book data source
            if hasattr(connector, '_orderbook_ds') and connector._orderbook_ds:
                orderbook_ds = connector._orderbook_ds
                
                # Check if the trading pair is available in the order book data source
                if trading_pair in orderbook_ds:
                    orderbook = orderbook_ds[trading_pair]
                    
                    # Get bid and ask data
                    bids = []
                    asks = []
                    
                    # Get top bids (highest prices first)
                    for i, (price, amount) in enumerate(orderbook.bid_entries()):
                        if i >= depth:
                            break
                        bids.append({"price": float(price), "amount": float(amount)})
                    
                    # Get top asks (lowest prices first) 
                    for i, (price, amount) in enumerate(orderbook.ask_entries()):
                        if i >= depth:
                            break
                        asks.append({"price": float(price), "amount": float(amount)})
                    
                    result = {
                        "trading_pair": trading_pair,
                        "bids": bids,
                        "asks": asks,
                        "timestamp": time.time()
                    }
                    
                    self.logger.debug(f"Retrieved order book for {connector_name}/{trading_pair}")
                    return result
                else:
                    return {"error": f"Trading pair {trading_pair} not found in order book data source"}
            else:
                return {"error": f"Order book data source not available for {connector_name}"}
                
        except Exception as e:
            self.logger.error(f"Error getting order book for {connector_name}/{trading_pair}: {e}")
            return {"error": str(e)}
    
    async def _cleanup_loop(self):
        """Background task that periodically cleans up unused feeds."""
        while self._is_running:
            try:
                await self._cleanup_unused_feeds()
                await asyncio.sleep(self.cleanup_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}", exc_info=True)
                await asyncio.sleep(self.cleanup_interval)
    
    async def _cleanup_unused_feeds(self):
        """Clean up feeds that haven't been accessed within the timeout period."""
        current_time = time.time()
        feeds_to_remove = []
        
        for feed_key, last_access_time in self.last_access_times.items():
            if current_time - last_access_time > self.feed_timeout:
                feeds_to_remove.append(feed_key)
        
        for feed_key in feeds_to_remove:
            try:
                # Get feed type and config
                feed_type, config = self.feed_configs[feed_key]
                
                # Use appropriate cleanup function
                cleanup_func = self._cleanup_functions.get(feed_type)
                if cleanup_func:
                    cleanup_func(config)
                
                # Remove from tracking
                del self.last_access_times[feed_key]
                del self.feed_configs[feed_key]
                
                self.logger.info(f"Cleaned up unused {feed_type.value} feed: {feed_key}")
                
            except Exception as e:
                self.logger.error(f"Error cleaning up feed {feed_key}: {e}", exc_info=True)
        
        if feeds_to_remove:
            self.logger.info(f"Cleaned up {len(feeds_to_remove)} unused market data feeds")
    
    def _cleanup_candle_feed(self, config: CandlesConfig):
        """Clean up a candle feed."""
        self.market_data_provider.stop_candle_feed(config)
    
    def _cleanup_order_book_feed(self, config: tuple):
        """Clean up an order book feed."""
        # Order books are typically managed by connectors, so we might not need explicit cleanup
        # This is a placeholder for future implementation if needed
        pass
    
    def _generate_feed_key(self, feed_type: FeedType, connector: str, trading_pair: str, interval: str = None) -> str:
        """Generate a unique key for a market data feed."""
        if interval:
            return f"{feed_type.value}_{connector}_{trading_pair}_{interval}"
        else:
            return f"{feed_type.value}_{connector}_{trading_pair}"
    
    def get_active_feeds_info(self) -> Dict[str, dict]:
        """
        Get information about currently active feeds.
        
        Returns:
            Dictionary with feed information including last access times and feed types
        """
        current_time = time.time()
        result = {}
        
        for feed_key, last_access in self.last_access_times.items():
            feed_type, config = self.feed_configs.get(feed_key, (None, None))
            result[feed_key] = {
                "feed_type": feed_type.value if feed_type else "unknown",
                "last_access_time": last_access,
                "seconds_since_access": current_time - last_access,
                "will_expire_in": max(0, self.feed_timeout - (current_time - last_access)),
                "config": str(config)  # String representation of config
            }
        
        return result
    
    def manually_cleanup_feed(self, feed_type: FeedType, connector: str, trading_pair: str, interval: str = None):
        """
        Manually cleanup a specific feed.
        
        Args:
            feed_type: Type of feed to cleanup
            connector: Connector name
            trading_pair: Trading pair
            interval: Interval (for candles only)
        """
        feed_key = self._generate_feed_key(feed_type, connector, trading_pair, interval)
        
        if feed_key in self.feed_configs:
            feed_type_obj, config = self.feed_configs[feed_key]
            cleanup_func = self._cleanup_functions.get(feed_type_obj)
            
            if cleanup_func:
                try:
                    cleanup_func(config)
                    del self.last_access_times[feed_key]
                    del self.feed_configs[feed_key]
                    self.logger.info(f"Manually cleaned up feed: {feed_key}")
                except Exception as e:
                    self.logger.error(f"Error manually cleaning up feed {feed_key}: {e}", exc_info=True)
            else:
                self.logger.warning(f"No cleanup function for feed type: {feed_type}")
        else:
            self.logger.warning(f"Feed not found for cleanup: {feed_key}")