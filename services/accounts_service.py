import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import HTTPException
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
from hummingbot.core.data_type.common import OrderType, TradeType, PositionAction, PositionMode
from hummingbot.strategy_v2.executors.data_types import ConnectorPair

from config import settings
from database import AsyncDatabaseManager, AccountRepository, OrderRepository, TradeRepository, FundingRepository
from services.market_data_feed_manager import MarketDataFeedManager
from utils.connector_manager import ConnectorManager
from utils.file_system import fs_util

# Create module-specific logger
logger = logging.getLogger(__name__)


class AccountsService:
    """
    This class is responsible for managing all the accounts that are connected to the trading system. It is responsible
    to initialize all the connectors that are connected to each account, keep track of the balances of each account and
    update the balances of each account.
    """
    default_quotes = {
        "hyperliquid": "USDC",
        "hyperliquid_perpetual": "USD",
        "xrpl": "RLUSD",
        "kraken": "USD",
    }
    
    # Cache for storing last successful prices by trading pair with timestamps
    _last_known_prices = {}
    _price_update_interval = 60  # Update prices every 60 seconds

    def __init__(self,
                 account_update_interval: int = 5,
                 default_quote: str = "USDT",
                 market_data_feed_manager: Optional[MarketDataFeedManager] = None):
        """
        Initialize the AccountsService.
        
        Args:
            account_update_interval: How often to update account states in minutes (default: 5)
            default_quote: Default quote currency for trading pairs (default: "USDT")
            market_data_feed_manager: Market data feed manager for price caching (optional)
        """
        self.secrets_manager = ETHKeyFileSecretManger(settings.security.config_password)
        self.accounts_state = {}
        self.update_account_state_interval = account_update_interval * 60
        self.default_quote = default_quote
        self.market_data_feed_manager = market_data_feed_manager
        self._update_account_state_task: Optional[asyncio.Task] = None
        
        # Database setup for account states and orders
        self.db_manager = AsyncDatabaseManager(settings.database.url)
        self._db_initialized = False
        
        # Initialize connector manager with db_manager
        self.connector_manager = ConnectorManager(self.secrets_manager, self.db_manager)

    async def ensure_db_initialized(self):
        """Ensure database is initialized before using it."""
        if not self._db_initialized:
            await self.db_manager.create_tables()
            self._db_initialized = True
    
    def get_accounts_state(self):
        return self.accounts_state

    def get_default_market(self, token: str, connector_name: str) -> str:
        if token.startswith("LD") and token != "LDO":
            # These tokens are staked in binance earn
            token = token[2:]
        quote = self.default_quotes.get(connector_name, self.default_quote)
        return f"{token}-{quote}"

    def start(self):
        """
        Start the loop that updates the account state at a fixed interval.
        Note: Balance updates are now handled by manual connector state updates.
        :return:
        """
        # Start the update loop which will call check_all_connectors
        self._update_account_state_task = asyncio.create_task(self.update_account_state_loop())

    async def stop(self):
        """
        Stop all accounts service tasks and cleanup resources.
        This is the main cleanup method that should be called during application shutdown.
        """
        logger.info("Stopping AccountsService...")
        
        # Stop the account state update loop
        if self._update_account_state_task:
            self._update_account_state_task.cancel()
            self._update_account_state_task = None
            logger.info("Stopped account state update loop")
        
        # Stop all connectors through the ConnectorManager
        await self.connector_manager.stop_all_connectors()
        
        logger.info("AccountsService stopped successfully")

    async def update_account_state_loop(self):
        """
        The loop that updates the account state at a fixed interval.
        This now includes manual connector state updates.
        :return:
        """
        while True:
            try:
                await self.check_all_connectors()
                # Update all connector states (balances, orders, positions, trading rules)
                await self.connector_manager.update_all_connector_states()
                await self.update_account_state()
                await self.dump_account_state()
            except Exception as e:
                logger.error(f"Error updating account state: {e}")
            finally:
                await asyncio.sleep(self.update_account_state_interval)

    async def dump_account_state(self):
        """
        Save the current account state to the database.
        All account/connector combinations from the same snapshot will use the same timestamp.
        :return:
        """
        await self.ensure_db_initialized()
        
        try:
            # Generate a single timestamp for this entire snapshot
            snapshot_timestamp = datetime.now(timezone.utc)
            
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                
                # Save each account-connector combination with the same timestamp
                for account_name, connectors in self.accounts_state.items():
                    for connector_name, tokens_info in connectors.items():
                        if tokens_info:  # Only save if there's token data
                            await repository.save_account_state(account_name, connector_name, tokens_info, snapshot_timestamp)
                            
        except Exception as e:
            logger.error(f"Error saving account state to database: {e}")
            # Re-raise the exception since we no longer have a fallback
            raise

    async def load_account_state_history(self, 
                                        limit: Optional[int] = None,
                                        cursor: Optional[str] = None,
                                        start_time: Optional[datetime] = None,
                                        end_time: Optional[datetime] = None):
        """
        Load the account state history from the database with pagination.
        :return: Tuple of (data, next_cursor, has_more).
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_account_state_history(
                    limit=limit,
                    cursor=cursor,
                    start_time=start_time,
                    end_time=end_time
                )
        except Exception as e:
            logger.error(f"Error loading account state history from database: {e}")
            # Return empty result since we no longer have a fallback
            return [], None, False

    async def check_all_connectors(self):
        """
        Check all available credentials for all accounts and ensure connectors are initialized.
        This method is idempotent - it only initializes missing connectors.
        """
        for account_name in self.list_accounts():
            await self._ensure_account_connectors_initialized(account_name)

    async def _ensure_account_connectors_initialized(self, account_name: str):
        """
        Ensure all connectors for a specific account are initialized.
        This delegates to ConnectorManager for actual initialization.
        
        :param account_name: The name of the account to initialize connectors for.
        """
        # Initialize missing connectors
        for connector_name in self.connector_manager.list_available_credentials(account_name):
            try:
                # Only initialize if connector doesn't exist
                if not self.connector_manager.is_connector_initialized(account_name, connector_name):
                    # Get connector will now handle all initialization
                    await self.connector_manager.get_connector(account_name, connector_name)
            except Exception as e:
                logger.error(f"Error initializing connector {connector_name} for account {account_name}: {e}")

    def _initialize_rate_sources_for_pairs(self, connector_name: str, trading_pairs: List[str]):
        """
        Helper method to initialize rate sources for trading pairs.
        
        :param connector_name: The name of the connector.
        :param trading_pairs: List of trading pairs to initialize.
        """
        if not trading_pairs or not self.market_data_feed_manager:
            return
            
        try:
            connector_pairs = [ConnectorPair(connector_name=connector_name, trading_pair=trading_pair) 
                             for trading_pair in trading_pairs]
            self.market_data_feed_manager.market_data_provider.initialize_rate_sources(connector_pairs)
            logger.info(f"Initialized rate sources for {len(trading_pairs)} trading pairs in {connector_name}")
        except Exception as e:
            logger.error(f"Error initializing rate sources for {connector_name}: {e}")

    async def _initialize_price_tracking(self, account_name: str, connector_name: str, connector):
        """
        Initialize price tracking for a connector's tokens using MarketDataProvider.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :param connector: The connector instance.
        """
        try:
            # Get current balances to determine which tokens need price tracking
            balances = connector.get_all_balances()
            unique_tokens = [token for token, value in balances.items() if 
                           value != Decimal("0") and token not in settings.banned_tokens and "USD" not in token]
            
            if unique_tokens:
                # Create trading pairs for price tracking
                trading_pairs = [self.get_default_market(token, connector_name) for token in unique_tokens]
                
                # Initialize rate sources using helper method
                self._initialize_rate_sources_for_pairs(connector_name, trading_pairs)
                
                logger.info(f"Initialized price tracking for {len(trading_pairs)} trading pairs in {connector_name} (Account: {account_name})")
                
        except Exception as e:
            logger.error(f"Error initializing price tracking for {connector_name} in account {account_name}: {e}")

    async def update_account_state(self):
        """Update account state for all connectors."""
        all_connectors = self.connector_manager.get_all_connectors()
        
        for account_name, connectors in all_connectors.items():
            if account_name not in self.accounts_state:
                self.accounts_state[account_name] = {}
            for connector_name, connector in connectors.items():
                try:
                    tokens_info = await self._get_connector_tokens_info(connector, connector_name, self.market_data_feed_manager)
                    self.accounts_state[account_name][connector_name] = tokens_info
                except Exception as e:
                    logger.error(f"Error updating balances for connector {connector_name} in account {account_name}: {e}")
                    self.accounts_state[account_name][connector_name] = []

    async def _get_connector_tokens_info(self, connector, connector_name: str, market_data_manager: Optional[MarketDataFeedManager] = None) -> List[Dict]:
        """Get token info from a connector instance using cached prices when available."""
        balances = [{"token": key, "units": value} for key, value in connector.get_all_balances().items() if
                    value != Decimal("0") and key not in settings.banned_tokens]
        unique_tokens = [balance["token"] for balance in balances]
        trading_pairs = [self.get_default_market(token, connector_name) for token in unique_tokens if "USD" not in token]
        
        # Try to get cached prices first, fallback to live prices if needed
        prices_from_cache = {}
        trading_pairs_need_update = []
        
        if market_data_manager:
            for trading_pair in trading_pairs:
                try:
                    cached_price = market_data_manager.market_data_provider.get_rate(trading_pair)
                    if cached_price > 0:
                        prices_from_cache[trading_pair] = cached_price
                    else:
                        trading_pairs_need_update.append(trading_pair)
                except Exception:
                    trading_pairs_need_update.append(trading_pair)
        else:
            trading_pairs_need_update = trading_pairs
        
        # Add new trading pairs to market data provider if they need updates
        if trading_pairs_need_update:
            self._initialize_rate_sources_for_pairs(connector_name, trading_pairs_need_update)
            logger.info(f"Added {len(trading_pairs_need_update)} new trading pairs to market data provider: {trading_pairs_need_update}")
        
        # Get fresh prices for pairs not in cache or with stale/zero prices
        fresh_prices = {}
        if trading_pairs_need_update:
            fresh_prices = await self._safe_get_last_traded_prices(connector, trading_pairs_need_update)
        
        # Combine cached and fresh prices
        all_prices = {**prices_from_cache, **fresh_prices}
        
        tokens_info = []
        for balance in balances:
            token = balance["token"]
            if "USD" in token:
                price = Decimal("1")
            else:
                market = self.get_default_market(balance["token"], connector_name)
                price = Decimal(str(all_prices.get(market, 0)))
                
            tokens_info.append({
                "token": balance["token"],
                "units": float(balance["units"]),
                "price": float(price),
                "value": float(price * balance["units"]),
                "available_units": float(connector.get_available_balance(balance["token"]))
            })
        return tokens_info
    
    async def _safe_get_last_traded_prices(self, connector, trading_pairs, timeout=10):
        """Safely get last traded prices with timeout and error handling. Preserves previous prices on failure."""
        try:
            last_traded = await asyncio.wait_for(connector.get_last_traded_prices(trading_pairs=trading_pairs), timeout=timeout)
            
            # Update cache with successful prices
            for pair, price in last_traded.items():
                if price and price > 0:
                    self._last_known_prices[pair] = price
            
            return last_traded
        except asyncio.TimeoutError:
            logger.error(f"Timeout getting last traded prices for trading pairs {trading_pairs}")
            return self._get_fallback_prices(trading_pairs)
        except Exception as e:
            logger.error(f"Error getting last traded prices in connector {connector} for trading pairs {trading_pairs}: {e}")
            return self._get_fallback_prices(trading_pairs)
    
    def _get_fallback_prices(self, trading_pairs):
        """Get fallback prices using cached values, only setting to 0 if no previous price exists."""
        fallback_prices = {}
        for pair in trading_pairs:
            if pair in self._last_known_prices:
                fallback_prices[pair] = self._last_known_prices[pair]
                logger.info(f"Using cached price {self._last_known_prices[pair]} for {pair}")
            else:
                fallback_prices[pair] = Decimal("0")
                logger.warning(f"No cached price available for {pair}, using 0")
        return fallback_prices

    def get_connector_config_map(self, connector_name: str):
        """
        Get the connector config map for the specified connector.
        :param connector_name: The name of the connector.
        :return: The connector config map.
        """
        return self.connector_manager.get_connector_config_map(connector_name)

    async def add_credentials(self, account_name: str, connector_name: str, credentials: dict):
        """
        Add or update connector credentials and initialize the connector with validation.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :param credentials: Dictionary containing the connector credentials.
        :raises Exception: If credentials are invalid or connector cannot be initialized.
        """
        try:
            # Update the connector keys (this saves the credentials to file and validates them)
            connector = await self.connector_manager.update_connector_keys(account_name, connector_name, credentials)
            
            # Initialize price tracking for this connector's tokens if market data manager is available
            if self.market_data_feed_manager:
                await self._initialize_price_tracking(account_name, connector_name, connector)
            
            await self.update_account_state()
        except Exception as e:
            logger.error(f"Error adding connector credentials for account {account_name}: {e}")
            await self.delete_credentials(account_name, connector_name)
            raise e

    @staticmethod
    def list_accounts():
        """
        List all the accounts that are connected to the trading system.
        :return: List of accounts.
        """
        return fs_util.list_folders('credentials')

    @staticmethod
    def list_credentials(account_name: str):
        """
        List all the credentials that are connected to the specified account.
        :param account_name: The name of the account.
        :return: List of credentials.
        """
        try:
            return [file for file in fs_util.list_files(f'credentials/{account_name}/connectors') if
                    file.endswith('.yml')]
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    async def delete_credentials(self, account_name: str, connector_name: str):
        """
        Delete the credentials of the specified connector for the specified account.
        :param account_name:
        :param connector_name:
        :return:
        """
        if fs_util.path_exists(f"credentials/{account_name}/connectors/{connector_name}.yml"):
            fs_util.delete_file(directory=f"credentials/{account_name}/connectors", file_name=f"{connector_name}.yml")
            
            # Stop the connector if it's running
            await self.connector_manager.stop_connector(account_name, connector_name)
            
            # Remove from account state
            if account_name in self.accounts_state and connector_name in self.accounts_state[account_name]:
                self.accounts_state[account_name].pop(connector_name)
            
            # Clear the connector from cache
            self.connector_manager.clear_cache(account_name, connector_name)

    def add_account(self, account_name: str):
        """
        Add a new account.
        :param account_name:
        :return:
        """
        # Check if account already exists by looking at folders
        if account_name in self.list_accounts():
            raise HTTPException(status_code=400, detail="Account already exists.")
        
        files_to_copy = ["conf_client.yml", "conf_fee_overrides.yml", "hummingbot_logs.yml", ".password_verification"]
        fs_util.create_folder('credentials', account_name)
        fs_util.create_folder(f'credentials/{account_name}', "connectors")
        for file in files_to_copy:
            fs_util.copy_file(f"credentials/master_account/{file}", f"credentials/{account_name}/{file}")
        
        # Initialize account state
        self.accounts_state[account_name] = {}

    async def delete_account(self, account_name: str):
        """
        Delete the specified account.
        :param account_name:
        :return:
        """
        # Stop all connectors for this account
        for connector_name in self.connector_manager.list_account_connectors(account_name):
            await self.connector_manager.stop_connector(account_name, connector_name)
        
        # Delete account folder
        fs_util.delete_folder('credentials', account_name)
        
        # Remove from account state
        if account_name in self.accounts_state:
            self.accounts_state.pop(account_name)
        
        # Clear all connectors for this account from cache
        self.connector_manager.clear_cache(account_name)
    
    async def get_account_current_state(self, account_name: str) -> Dict[str, List[Dict]]:
        """
        Get current state for a specific account from database.
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_account_current_state(account_name)
        except Exception as e:
            logger.error(f"Error getting account current state: {e}")
            # Fallback to in-memory state
            return self.accounts_state.get(account_name, {})
    
    async def get_account_state_history(self, 
                                        account_name: str, 
                                        limit: Optional[int] = None,
                                        cursor: Optional[str] = None,
                                        start_time: Optional[datetime] = None,
                                        end_time: Optional[datetime] = None):
        """
        Get historical state for a specific account with pagination.
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_account_state_history(
                    account_name=account_name, 
                    limit=limit,
                    cursor=cursor,
                    start_time=start_time,
                    end_time=end_time
                )
        except Exception as e:
            logger.error(f"Error getting account state history: {e}")
            return [], None, False
    
    async def get_connector_current_state(self, account_name: str, connector_name: str) -> List[Dict]:
        """
        Get current state for a specific connector.
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_connector_current_state(account_name, connector_name)
        except Exception as e:
            logger.error(f"Error getting connector current state: {e}")
            # Fallback to in-memory state
            return self.accounts_state.get(account_name, {}).get(connector_name, [])
    
    async def get_connector_state_history(self, 
                                          account_name: str, 
                                          connector_name: str, 
                                          limit: Optional[int] = None,
                                          cursor: Optional[str] = None,
                                          start_time: Optional[datetime] = None,
                                          end_time: Optional[datetime] = None):
        """
        Get historical state for a specific connector with pagination.
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_account_state_history(
                    account_name=account_name, 
                    connector_name=connector_name,
                    limit=limit,
                    cursor=cursor,
                    start_time=start_time,
                    end_time=end_time
                )
        except Exception as e:
            logger.error(f"Error getting connector state history: {e}")
            return [], None, False
    
    async def get_all_unique_tokens(self) -> List[str]:
        """
        Get all unique tokens across all accounts and connectors.
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_all_unique_tokens()
        except Exception as e:
            logger.error(f"Error getting unique tokens: {e}")
            # Fallback to in-memory state
            tokens = set()
            for account_data in self.accounts_state.values():
                for connector_data in account_data.values():
                    for token_info in connector_data:
                        tokens.add(token_info.get("token"))
            return sorted(list(tokens))
    
    async def get_token_current_state(self, token: str) -> List[Dict]:
        """
        Get current state of a specific token across all accounts.
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_token_current_state(token)
        except Exception as e:
            logger.error(f"Error getting token current state: {e}")
            return []
    
    async def get_portfolio_value(self, account_name: Optional[str] = None) -> Dict[str, any]:
        """
        Get total portfolio value, optionally filtered by account.
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                return await repository.get_portfolio_value(account_name)
        except Exception as e:
            logger.error(f"Error getting portfolio value: {e}")
            # Fallback to in-memory calculation
            portfolio = {"accounts": {}, "total_value": 0}
            
            accounts_to_process = [account_name] if account_name else self.accounts_state.keys()
            
            for acc_name in accounts_to_process:
                account_value = 0
                if acc_name in self.accounts_state:
                    for connector_data in self.accounts_state[acc_name].values():
                        for token_info in connector_data:
                            account_value += token_info.get("value", 0)
                    portfolio["accounts"][acc_name] = account_value
                    portfolio["total_value"] += account_value
            
            return portfolio
    
    def get_portfolio_distribution(self, account_name: Optional[str] = None) -> Dict[str, any]:
        """
        Get portfolio distribution by tokens with percentages.
        """
        try:
            # Get accounts to process
            accounts_to_process = [account_name] if account_name else list(self.accounts_state.keys())
            
            # Aggregate all tokens across accounts and connectors
            token_values = {}
            total_value = 0
            
            for acc_name in accounts_to_process:
                if acc_name in self.accounts_state:
                    for connector_name, connector_data in self.accounts_state[acc_name].items():
                        for token_info in connector_data:
                            token = token_info.get("token", "")
                            value = token_info.get("value", 0)
                            
                            if token not in token_values:
                                token_values[token] = {
                                    "token": token,
                                    "total_value": 0,
                                    "total_units": 0,
                                    "accounts": {}
                                }
                            
                            token_values[token]["total_value"] += value
                            token_values[token]["total_units"] += token_info.get("units", 0)
                            total_value += value
                            
                            # Track by account
                            if acc_name not in token_values[token]["accounts"]:
                                token_values[token]["accounts"][acc_name] = {
                                    "value": 0,
                                    "units": 0,
                                    "connectors": {}
                                }
                            
                            token_values[token]["accounts"][acc_name]["value"] += value
                            token_values[token]["accounts"][acc_name]["units"] += token_info.get("units", 0)
                            
                            # Track by connector within account
                            if connector_name not in token_values[token]["accounts"][acc_name]["connectors"]:
                                token_values[token]["accounts"][acc_name]["connectors"][connector_name] = {
                                    "value": 0,
                                    "units": 0
                                }
                            
                            token_values[token]["accounts"][acc_name]["connectors"][connector_name]["value"] += value
                            token_values[token]["accounts"][acc_name]["connectors"][connector_name]["units"] += token_info.get("units", 0)
            
            # Calculate percentages
            distribution = []
            for token_data in token_values.values():
                percentage = (token_data["total_value"] / total_value * 100) if total_value > 0 else 0
                
                token_dist = {
                    "token": token_data["token"],
                    "total_value": round(token_data["total_value"], 6),
                    "total_units": token_data["total_units"],
                    "percentage": round(percentage, 4),
                    "accounts": {}
                }
                
                # Add account-level percentages
                for acc_name, acc_data in token_data["accounts"].items():
                    acc_percentage = (acc_data["value"] / total_value * 100) if total_value > 0 else 0
                    token_dist["accounts"][acc_name] = {
                        "value": round(acc_data["value"], 6),
                        "units": acc_data["units"],
                        "percentage": round(acc_percentage, 4),
                        "connectors": {}
                    }
                    
                    # Add connector-level data
                    for conn_name, conn_data in acc_data["connectors"].items():
                        token_dist["accounts"][acc_name]["connectors"][conn_name] = {
                            "value": round(conn_data["value"], 6),
                            "units": conn_data["units"]
                        }
                
                distribution.append(token_dist)
            
            # Sort by value (descending)
            distribution.sort(key=lambda x: x["total_value"], reverse=True)
            
            return {
                "total_portfolio_value": round(total_value, 6),
                "token_count": len(distribution),
                "distribution": distribution,
                "account_filter": account_name if account_name else "all_accounts"
            }
            
        except Exception as e:
            logger.error(f"Error calculating portfolio distribution: {e}")
            return {
                "total_portfolio_value": 0,
                "token_count": 0,
                "distribution": [],
                "account_filter": account_name if account_name else "all_accounts",
                "error": str(e)
            }
    
    def get_account_distribution(self) -> Dict[str, any]:
        """
        Get portfolio distribution by accounts with percentages.
        """
        try:
            account_values = {}
            total_value = 0
            
            for acc_name, account_data in self.accounts_state.items():
                account_value = 0
                connector_values = {}
                
                for connector_name, connector_data in account_data.items():
                    connector_value = 0
                    for token_info in connector_data:
                        value = token_info.get("value", 0)
                        connector_value += value
                        account_value += value
                    
                    connector_values[connector_name] = round(connector_value, 6)
                
                account_values[acc_name] = {
                    "total_value": round(account_value, 6),
                    "connectors": connector_values
                }
                total_value += account_value
            
            # Calculate percentages
            distribution = []
            for acc_name, acc_data in account_values.items():
                percentage = (acc_data["total_value"] / total_value * 100) if total_value > 0 else 0
                
                connector_dist = {}
                for conn_name, conn_value in acc_data["connectors"].items():
                    conn_percentage = (conn_value / total_value * 100) if total_value > 0 else 0
                    connector_dist[conn_name] = {
                        "value": conn_value,
                        "percentage": round(conn_percentage, 4)
                    }
                
                distribution.append({
                    "account": acc_name,
                    "total_value": acc_data["total_value"],
                    "percentage": round(percentage, 4),
                    "connectors": connector_dist
                })
            
            # Sort by value (descending)
            distribution.sort(key=lambda x: x["total_value"], reverse=True)
            
            return {
                "total_portfolio_value": round(total_value, 6),
                "account_count": len(distribution),
                "distribution": distribution
            }
            
        except Exception as e:
            logger.error(f"Error calculating account distribution: {e}")
            return {
                "total_portfolio_value": 0,
                "account_count": 0,
                "distribution": [],
                "error": str(e)
            }
    
    async def place_trade(self, account_name: str, connector_name: str, trading_pair: str, 
                         trade_type: TradeType, amount: Decimal, order_type: OrderType = OrderType.LIMIT, 
                         price: Optional[Decimal] = None, position_action: PositionAction = PositionAction.OPEN, 
                         market_data_manager: Optional[MarketDataFeedManager] = None) -> str:
        """
        Place a trade using the specified account and connector.
        
        Args:
            account_name: Name of the account to trade with
            connector_name: Name of the connector/exchange
            trading_pair: Trading pair (e.g., BTC-USDT)
            trade_type: "BUY" or "SELL"
            amount: Amount to trade
            order_type: "LIMIT", "MARKET", or "LIMIT_MAKER"
            price: Price for limit orders (required for LIMIT and LIMIT_MAKER)
            position_action: Position action for perpetual contracts (OPEN/CLOSE)
            market_data_manager: Market data manager for price fetching
            
        Returns:
            Client order ID assigned by the connector
            
        Raises:
            HTTPException: If account, connector not found, or trade fails
        """
        # Validate account exists
        if account_name not in self.list_accounts():
            raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
        
        # Validate connector exists for account
        if not self.connector_manager.is_connector_initialized(account_name, connector_name):
            raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found for account '{account_name}'")
        
        # Get the connector instance
        connector = await self.connector_manager.get_connector(account_name, connector_name)
        
        # Validate price for limit orders
        if order_type in [OrderType.LIMIT, OrderType.LIMIT_MAKER] and price is None:
            raise HTTPException(status_code=400, detail="Price is required for LIMIT and LIMIT_MAKER orders")
        
        # Check if trading rules are loaded
        if not connector.trading_rules:
            raise HTTPException(
                status_code=503, 
                detail=f"Trading rules not yet loaded for {connector_name}. Please try again in a moment."
            )
        
        # Validate trading pair and get trading rule
        if trading_pair not in connector.trading_rules:
            available_pairs = list(connector.trading_rules.keys())[:10]  # Show first 10
            more_text = f" (and {len(connector.trading_rules) - 10} more)" if len(connector.trading_rules) > 10 else ""
            raise HTTPException(
                status_code=400, 
                detail=f"Trading pair '{trading_pair}' not supported on {connector_name}. "
                       f"Available pairs: {available_pairs}{more_text}"
            )
        
        trading_rule = connector.trading_rules[trading_pair]
        
        # Validate order type is supported
        if order_type not in connector.supported_order_types():
            supported_types = [ot.name for ot in connector.supported_order_types()]
            raise HTTPException(status_code=400, detail=f"Order type '{order_type.name}' not supported. Supported types: {supported_types}")
        
        # Quantize amount according to trading rules
        quantized_amount = connector.quantize_order_amount(trading_pair, amount)
        
        # Validate minimum order size
        if quantized_amount < trading_rule.min_order_size:
            raise HTTPException(
                status_code=400, 
                detail=f"Order amount {quantized_amount} is below minimum order size {trading_rule.min_order_size} for {trading_pair}"
            )
        
        # Calculate and validate notional size
        if order_type in [OrderType.LIMIT, OrderType.LIMIT_MAKER]:
            quantized_price = connector.quantize_order_price(trading_pair, price)
            notional_size = quantized_price * quantized_amount
        else:
            # For market orders without price, get current market price for validation
            if market_data_manager:
                try:
                    prices = await market_data_manager.get_prices(connector_name, [trading_pair])
                    if trading_pair in prices and "error" not in prices:
                        price = Decimal(str(prices[trading_pair]))
                except Exception as e:
                    logger.error(f"Error getting market price for {trading_pair}: {e}")
            notional_size = price * quantized_amount
            
        if notional_size < trading_rule.min_notional_size:
            raise HTTPException(
                status_code=400,
                detail=f"Order notional value {notional_size} is below minimum notional size {trading_rule.min_notional_size} for {trading_pair}. "
                       f"Increase the amount or price to meet the minimum requirement."
            )
        


        try:
            # Place the order using the connector with quantized values
            # (position_action will be ignored by non-perpetual connectors)
            if trade_type == TradeType.BUY:
                order_id = connector.buy(
                    trading_pair=trading_pair,
                    amount=quantized_amount,
                    order_type=order_type,
                    price=price or Decimal("1"),
                    position_action=position_action
                )
            else:
                order_id = connector.sell(
                    trading_pair=trading_pair,
                    amount=quantized_amount,
                    order_type=order_type,
                    price=price or Decimal("1"),
                    position_action=position_action
                )

            logger.info(f"Placed {trade_type} order for {amount} {trading_pair} on {connector_name} (Account: {account_name}). Order ID: {order_id}")
            return order_id
            
        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            logger.error(f"Failed to place {trade_type} order: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to place trade: {str(e)}")
    
    async def get_connector_instance(self, account_name: str, connector_name: str):
        """
        Get a connector instance for direct access.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector
            
        Returns:
            Connector instance
            
        Raises:
            HTTPException: If account or connector not found
        """
        if account_name not in self.list_accounts():
            raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
        
        # Check if connector credentials exist
        available_credentials = self.connector_manager.list_available_credentials(account_name)
        if connector_name not in available_credentials:
            raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found for account '{account_name}'")
        
        return await self.connector_manager.get_connector(account_name, connector_name)
    
    async def get_active_orders(self, account_name: str, connector_name: str) -> Dict[str, any]:
        """
        Get active orders for a specific connector.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector
            
        Returns:
            Dictionary of active orders
        """
        connector = await self.get_connector_instance(account_name, connector_name)
        return {order_id: order.to_json() for order_id, order in connector.in_flight_orders.items()}
    
    async def cancel_order(self, account_name: str, connector_name: str, client_order_id: str) -> str:
        """
        Cancel an active order.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector
            client_order_id: Client order ID to cancel
            
        Returns:
            Client order ID that was cancelled
            
        Raises:
            HTTPException: 404 if order not found, 500 if cancellation fails
        """
        connector = await self.get_connector_instance(account_name, connector_name)
        
        # Check if order exists in in-flight orders
        if client_order_id not in connector.in_flight_orders:
            raise HTTPException(status_code=404, detail=f"Order '{client_order_id}' not found in active orders")
        
        try:
            result = connector.cancel(trading_pair="NA", client_order_id=client_order_id)
            logger.info(f"Initiated cancellation for order {client_order_id} on {connector_name} (Account: {account_name})")
            return result
        except Exception as e:
            logger.error(f"Failed to initiate cancellation for order {client_order_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to initiate order cancellation: {str(e)}")
    
    async def set_leverage(self, account_name: str, connector_name: str, 
                          trading_pair: str, leverage: int) -> Dict[str, str]:
        """
        Set leverage for a specific trading pair on a perpetual connector.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector (must be perpetual)
            trading_pair: Trading pair to set leverage for
            leverage: Leverage value (typically 1-125)
            
        Returns:
            Dictionary with success status and message
            
        Raises:
            HTTPException: If account/connector not found, not perpetual, or operation fails
        """
        # Validate this is a perpetual connector
        if "_perpetual" not in connector_name:
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' is not a perpetual connector")
        
        connector = await self.get_connector_instance(account_name, connector_name)
        
        # Check if connector has leverage functionality
        if not hasattr(connector, '_execute_set_leverage'):
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' does not support leverage setting")
        
        try:
            await connector._execute_set_leverage(trading_pair, leverage)
            message = f"Leverage for {trading_pair} set to {leverage} on {connector_name}"
            logger.info(f"Set leverage for {trading_pair} to {leverage} on {connector_name} (Account: {account_name})")
            return {"status": "success", "message": message}
            
        except Exception as e:
            logger.error(f"Failed to set leverage for {trading_pair} to {leverage}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to set leverage: {str(e)}")

    async def set_position_mode(self, account_name: str, connector_name: str, 
                               position_mode: PositionMode) -> Dict[str, str]:
        """
        Set position mode for a perpetual connector.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector (must be perpetual)
            position_mode: PositionMode.HEDGE or PositionMode.ONEWAY
            
        Returns:
            Dictionary with success status and message
            
        Raises:
            HTTPException: If account/connector not found, not perpetual, or operation fails
        """
        # Validate this is a perpetual connector
        if "_perpetual" not in connector_name:
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' is not a perpetual connector")
        
        connector = await self.get_connector_instance(account_name, connector_name)
        
        # Check if the requested position mode is supported
        supported_modes = connector.supported_position_modes()
        if position_mode not in supported_modes:
            supported_values = [mode.value for mode in supported_modes]
            raise HTTPException(
                status_code=400, 
                detail=f"Position mode '{position_mode.value}' not supported. Supported modes: {supported_values}"
            )
        
        try:
            # Try to call the method - it might be sync or async
            result = connector.set_position_mode(position_mode)
            # If it's a coroutine, await it
            if asyncio.iscoroutine(result):
                await result
            
            message = f"Position mode set to {position_mode.value} on {connector_name}"
            logger.info(f"Set position mode to {position_mode.value} on {connector_name} (Account: {account_name})")
            return {"status": "success", "message": message}
            
        except Exception as e:
            logger.error(f"Failed to set position mode to {position_mode.value}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to set position mode: {str(e)}")

    async def get_position_mode(self, account_name: str, connector_name: str) -> Dict[str, str]:
        """
        Get current position mode for a perpetual connector.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector (must be perpetual)
            
        Returns:
            Dictionary with current position mode
            
        Raises:
            HTTPException: If account/connector not found, not perpetual, or operation fails
        """
        # Validate this is a perpetual connector
        if "_perpetual" not in connector_name:
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' is not a perpetual connector")
        
        connector = await self.get_connector_instance(account_name, connector_name)
        
        # Check if connector has position mode functionality
        if not hasattr(connector, 'position_mode'):
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' does not support position mode")
        
        try:
            current_mode = connector.position_mode
            return {
                "position_mode": current_mode.value if current_mode else "UNKNOWN",
                "connector": connector_name,
                "account": account_name
            }
            
        except Exception as e:
            logger.error(f"Failed to get position mode: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get position mode: {str(e)}")

    async def get_orders(self, account_name: Optional[str] = None, connector_name: Optional[str] = None,
                        trading_pair: Optional[str] = None, status: Optional[str] = None,
                        start_time: Optional[int] = None, end_time: Optional[int] = None,
                        limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get order history using OrderRepository."""
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                order_repo = OrderRepository(session)
                orders = await order_repo.get_orders(
                    account_name=account_name,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    status=status,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                    offset=offset
                )
                return [order_repo.to_dict(order) for order in orders]
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []

    async def get_active_orders_history(self, account_name: Optional[str] = None, connector_name: Optional[str] = None,
                                       trading_pair: Optional[str] = None) -> List[Dict]:
        """Get active orders from database using OrderRepository."""
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                order_repo = OrderRepository(session)
                orders = await order_repo.get_active_orders(
                    account_name=account_name,
                    connector_name=connector_name,
                    trading_pair=trading_pair
                )
                return [order_repo.to_dict(order) for order in orders]
        except Exception as e:
            logger.error(f"Error getting active orders: {e}")
            return []

    async def get_orders_summary(self, account_name: Optional[str] = None, start_time: Optional[int] = None,
                                end_time: Optional[int] = None) -> Dict:
        """Get order summary statistics using OrderRepository."""
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                order_repo = OrderRepository(session)
                return await order_repo.get_orders_summary(
                    account_name=account_name,
                    start_time=start_time,
                    end_time=end_time
                )
        except Exception as e:
            logger.error(f"Error getting orders summary: {e}")
            return {
                "total_orders": 0,
                "filled_orders": 0,
                "cancelled_orders": 0,
                "failed_orders": 0,
                "active_orders": 0,
                "fill_rate": 0,
            }

    async def get_trades(self, account_name: Optional[str] = None, connector_name: Optional[str] = None,
                        trading_pair: Optional[str] = None, trade_type: Optional[str] = None,
                        start_time: Optional[int] = None, end_time: Optional[int] = None,
                        limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get trade history using TradeRepository."""
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                trade_repo = TradeRepository(session)
                trade_order_pairs = await trade_repo.get_trades_with_orders(
                    account_name=account_name,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    trade_type=trade_type,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                    offset=offset
                )
                return [trade_repo.to_dict(trade, order) for trade, order in trade_order_pairs]
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []

    async def get_account_positions(self, account_name: str, connector_name: str) -> List[Dict]:
        """
        Get current positions for a specific perpetual connector.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector (must be perpetual)
            
        Returns:
            List of position dictionaries
            
        Raises:
            HTTPException: If account/connector not found or not perpetual
        """
        # Validate this is a perpetual connector
        if "_perpetual" not in connector_name:
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' is not a perpetual connector")
        
        connector = await self.get_connector_instance(account_name, connector_name)
        
        # Check if connector has account_positions property
        if not hasattr(connector, 'account_positions'):
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' does not support position tracking")
        
        try:
            # Force position update to ensure current market prices are used
            await connector._update_positions()
            
            positions = []
            raw_positions = connector.account_positions
            
            for trading_pair, position_info in raw_positions.items():
                # Convert position data to dict format
                position_dict = {
                    "account_name": account_name,
                    "connector_name": connector_name,
                    "trading_pair": position_info.trading_pair,
                    "side": position_info.position_side.name if hasattr(position_info, 'position_side') else "UNKNOWN",
                    "amount": float(position_info.amount) if hasattr(position_info, 'amount') else 0.0,
                    "entry_price": float(position_info.entry_price) if hasattr(position_info, 'entry_price') else None,
                    "unrealized_pnl": float(position_info.unrealized_pnl) if hasattr(position_info, 'unrealized_pnl') else None,
                    "leverage": float(position_info.leverage) if hasattr(position_info, 'leverage') else None,
                }
                
                # Only include positions with non-zero amounts
                if position_dict["amount"] != 0:
                    positions.append(position_dict)
            
            return positions
            
        except Exception as e:
            logger.error(f"Failed to get positions for {connector_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get positions: {str(e)}")

    async def get_funding_payments(self, account_name: str, connector_name: str = None, 
                                  trading_pair: str = None, limit: int = 100) -> List[Dict]:
        """
        Get funding payment history for an account.
        
        Args:
            account_name: Name of the account
            connector_name: Optional connector name filter
            trading_pair: Optional trading pair filter
            limit: Maximum number of records to return
            
        Returns:
            List of funding payment dictionaries
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                funding_repo = FundingRepository(session)
                funding_payments = await funding_repo.get_funding_payments(
                    account_name=account_name,
                    connector_name=connector_name,
                    trading_pair=trading_pair,
                    limit=limit
                )
                return [funding_repo.to_dict(payment) for payment in funding_payments]
                
        except Exception as e:
            logger.error(f"Error getting funding payments: {e}")
            return []

    async def get_total_funding_fees(self, account_name: str, connector_name: str, 
                                   trading_pair: str) -> Dict:
        """
        Get total funding fees for a specific trading pair.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector
            trading_pair: Trading pair to get fees for
            
        Returns:
            Dictionary with total funding fees information
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                funding_repo = FundingRepository(session)
                return await funding_repo.get_total_funding_fees(
                    account_name=account_name,
                    connector_name=connector_name,
                    trading_pair=trading_pair
                )
                
        except Exception as e:
            logger.error(f"Error getting total funding fees: {e}")
            return {
                "total_funding_fees": 0,
                "payment_count": 0,
                "fee_currency": None,
                "error": str(e)
            }
