import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import HTTPException
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
from hummingbot.core.data_type.common import OrderType, TradeType

from config import settings
from database import AsyncDatabaseManager, AccountRepository, Order, Trade
from utils.connector_manager import ConnectorManager
from utils.file_system import FileSystemUtil

file_system = FileSystemUtil()


class AccountsService:
    """
    This class is responsible for managing all the accounts that are connected to the trading system. It is responsible
    to initialize all the connectors that are connected to each account, keep track of the balances of each account and
    update the balances of each account.
    """
    default_quotes = {
        "hyperliquid": "USD",
        "hyperliquid_perpetual": "USDC",
        "xrpl": "RLUSD",
        "kraken": "USD",
    }

    def __init__(self,
                 account_update_interval: int = 5,
                 default_quote: str = "USDT"):
        """
        Initialize the AccountsService.
        
        Args:
            account_update_interval: How often to update account states in minutes (default: 5)
            default_quote: Default quote currency for trading pairs (default: "USDT")
        """
        self.secrets_manager = ETHKeyFileSecretManger(settings.security.config_password)
        self.connector_manager = ConnectorManager(self.secrets_manager)
        self.accounts_state = {}
        self.update_account_state_interval = account_update_interval * 60
        self.default_quote = default_quote
        self._update_account_state_task: Optional[asyncio.Task] = None
        
        # Database setup for account states and orders
        self.db_manager = AsyncDatabaseManager(settings.database.url)
        self._db_initialized = False

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
        Note: Balance updates are now handled automatically by connector.start_network()
        :return:
        """
        # Start the update loop which will call check_all_connectors
        self._update_account_state_task = asyncio.create_task(self.update_account_state_loop())
    
    async def stop(self):
        """
        Stop all accounts service tasks and cleanup resources.
        This is the main cleanup method that should be called during application shutdown.
        """
        logging.info("Stopping AccountsService...")
        
        # Stop the account state update loop
        if self._update_account_state_task:
            self._update_account_state_task.cancel()
            self._update_account_state_task = None
            logging.info("Stopped account state update loop")
        
        # Stop all connectors through the ConnectorManager
        await self.connector_manager.stop_all_connectors()
        
        logging.info("AccountsService stopped successfully")

    async def update_account_state_loop(self):
        """
        The loop that updates the account state at a fixed interval.
        Note: Balance updates are now handled automatically by connector.start_network()
        :return:
        """
        while True:
            try:
                await self.check_all_connectors()
                await self.update_account_state()
                await self.dump_account_state()
            except Exception as e:
                logging.error(f"Error updating account state: {e}")
            finally:
                await asyncio.sleep(self.update_account_state_interval)

    async def dump_account_state(self):
        """
        Save the current account state to the database.
        :return:
        """
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                repository = AccountRepository(session)
                
                # Save each account-connector combination
                for account_name, connectors in self.accounts_state.items():
                    for connector_name, tokens_info in connectors.items():
                        if tokens_info:  # Only save if there's token data
                            await repository.save_account_state(account_name, connector_name, tokens_info)
                            
        except Exception as e:
            logging.error(f"Error saving account state to database: {e}")
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
            logging.error(f"Error loading account state history from database: {e}")
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
                    await self.connector_manager.initialize_connector_with_tracking(
                        account_name, connector_name, self.db_manager
                    )
                    await self._update_connector_balance(account_name, connector_name)
                    
            except Exception as e:
                logging.error(f"Error initializing connector {connector_name} for account {account_name}: {e}")


    async def _update_connector_balance(self, account_name: str, connector_name: str):
        """
        Update balance for a specific connector and store in accounts_state.
        This is called after connector initialization to get initial balance data.
        """
        try:
            tokens_info = []
            connector = self.connector_manager.get_connector(account_name, connector_name)
            await connector._update_balances()
            balances = [{"token": key, "units": value} for key, value in connector.get_all_balances().items() if
                        value != Decimal("0") and key not in settings.banned_tokens]
            unique_tokens = [balance["token"] for balance in balances]
            trading_pairs = [self.get_default_market(token, connector_name) for token in unique_tokens if "USD" not in token]
            last_traded_prices = await self._safe_get_last_traded_prices(connector, trading_pairs)
            
            for balance in balances:
                token = balance["token"]
                if "USD" in token:
                    price = Decimal("1")
                else:
                    market = self.get_default_market(balance["token"], connector_name)
                    price = Decimal(last_traded_prices.get(market, 0))
                tokens_info.append({
                    "token": balance["token"],
                    "units": float(balance["units"]),
                    "price": float(price),
                    "value": float(price * balance["units"]),
                    "available_units": float(connector.get_available_balance(balance["token"]))
                })
            
            # Ensure account exists in accounts_state before assignment
            if account_name not in self.accounts_state:
                self.accounts_state[account_name] = {}
                
            self.accounts_state[account_name][connector_name] = tokens_info

            logging.info(f"Updated balance for {account_name}/{connector_name}: {len(tokens_info)} tokens")
            
        except Exception as e:
            logging.error(f"Error updating balance for connector {connector_name} in account {account_name}: {e}")
            # Set empty state if update fails
            if account_name not in self.accounts_state:
                self.accounts_state[account_name] = {}
            self.accounts_state[account_name][connector_name] = []

    async def update_account_state(self):
        # Get all connectors from ConnectorManager
        all_connectors = self.connector_manager.get_all_connectors()
        
        for account_name, connectors in all_connectors.items():
            if account_name not in self.accounts_state:
                self.accounts_state[account_name] = {}
            for connector_name, connector in connectors.items():
                tokens_info = []
                try:
                    balances = [{"token": key, "units": value} for key, value in connector.get_all_balances().items() if
                                value != Decimal("0") and key not in settings.banned_tokens]
                    unique_tokens = [balance["token"] for balance in balances]
                    trading_pairs = [self.get_default_market(token, connector_name) for token in unique_tokens if "USD" not in token]
                    last_traded_prices = await self._safe_get_last_traded_prices(connector, trading_pairs)
                    for balance in balances:
                        token = balance["token"]
                        if "USD" in token:
                            price = Decimal("1")
                        else:
                            market = self.get_default_market(balance["token"], connector_name)
                            price = Decimal(last_traded_prices.get(market, 0))
                        tokens_info.append({
                            "token": balance["token"],
                            "units": float(balance["units"]),
                            "price": float(price),
                            "value": float(price * balance["units"]),
                            "available_units": float(connector.get_available_balance(balance["token"]))
                        })
                except Exception as e:
                    logging.error(
                        f"Error updating balances for connector {connector_name} in account {account_name}: {e}")
                self.accounts_state[account_name][connector_name] = tokens_info

    async def _safe_get_last_traded_prices(self, connector, trading_pairs, timeout=10):
        try:
            last_traded = await asyncio.wait_for(connector.get_last_traded_prices(trading_pairs=trading_pairs), timeout=timeout)
            return last_traded
        except asyncio.TimeoutError:
            logging.error(f"Timeout getting last traded prices for trading pairs {trading_pairs}")
            return {pair: Decimal("0") for pair in trading_pairs}
        except Exception as e:
            logging.error(f"Error getting last traded prices in connector {connector} for trading pairs {trading_pairs}: {e}")
            return {pair: Decimal("0") for pair in trading_pairs}

    def get_connector_config_map(self, connector_name: str):
        """
        Get the connector config map for the specified connector.
        :param connector_name: The name of the connector.
        :return: The connector config map.
        """
        return self.connector_manager.get_connector_config_map(connector_name)

    async def add_credentials(self, account_name: str, connector_name: str, credentials: dict):
        """
        Add or update connector credentials and initialize the connector.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :param credentials: Dictionary containing the connector credentials.
        """
        # Update the connector keys (this saves the credentials to file)
        await self.connector_manager.update_connector_keys(account_name, connector_name, credentials)
        
        # Initialize the connector with tracking
        await self.connector_manager.initialize_connector_with_tracking(
            account_name, connector_name, self.db_manager
        )
        await self._update_connector_balance(account_name, connector_name)



    @staticmethod
    def list_accounts():
        """
        List all the accounts that are connected to the trading system.
        :return: List of accounts.
        """
        return file_system.list_folders('credentials')

    def list_credentials(self, account_name: str):
        """
        List all the credentials that are connected to the specified account.
        :param account_name: The name of the account.
        :return: List of credentials.
        """
        try:
            return [file for file in file_system.list_files(f'credentials/{account_name}/connectors') if
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
        if file_system.path_exists(f"credentials/{account_name}/connectors/{connector_name}.yml"):
            file_system.delete_file(directory=f"credentials/{account_name}/connectors", file_name=f"{connector_name}.yml")
            
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
        file_system.create_folder('credentials', account_name)
        file_system.create_folder(f'credentials/{account_name}', "connectors")
        for file in files_to_copy:
            file_system.copy_file(f"credentials/master_account/{file}", f"credentials/{account_name}/{file}")
        
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
        file_system.delete_folder('credentials', account_name)
        
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
            logging.error(f"Error getting account current state: {e}")
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
            logging.error(f"Error getting account state history: {e}")
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
            logging.error(f"Error getting connector current state: {e}")
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
            logging.error(f"Error getting connector state history: {e}")
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
            logging.error(f"Error getting unique tokens: {e}")
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
            logging.error(f"Error getting token current state: {e}")
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
            logging.error(f"Error getting portfolio value: {e}")
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
    
    async def place_trade(self, account_name: str, connector_name: str, trading_pair: str, 
                         trade_type: TradeType, amount: Decimal, order_type: OrderType = OrderType.LIMIT, 
                         price: Optional[Decimal] = None, market_data_manager = None) -> str:
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
        connector = self.connector_manager.get_connector(account_name, connector_name)
        
        # Validate price for limit orders
        if order_type in [OrderType.LIMIT, OrderType.LIMIT_MAKER] and price is None:
            raise HTTPException(status_code=400, detail="Price is required for LIMIT and LIMIT_MAKER orders")
        
        # For market orders without price, get current market price
        if order_type == OrderType.MARKET and price is None and market_data_manager:
            try:
                prices = await market_data_manager.get_prices(connector_name, [trading_pair])
                if trading_pair in prices and "error" not in prices:
                    price = Decimal(str(prices[trading_pair]))
                    logging.info(f"Retrieved market price for {trading_pair}: {price}")
                else:
                    logging.warning(f"Could not get market price for {trading_pair}, using 0")
                    price = Decimal("0")
            except Exception as e:
                logging.error(f"Error getting market price for {trading_pair}: {e}")
                price = Decimal("0")
        
        try:
            # Place the order using the connector
            if trade_type == TradeType.BUY:
                order_id = connector.buy(
                    trading_pair=trading_pair,
                    amount=amount,
                    order_type=order_type,
                    price=price or Decimal("0")
                )
            else:
                order_id = connector.sell(
                    trading_pair=trading_pair,
                    amount=amount,
                    order_type=order_type,
                    price=price or Decimal("0")
                )
            
            # Wait briefly to check for immediate failures
            await asyncio.sleep(0.5)
            
            # Check if order was immediately rejected or failed
            if order_id in connector.in_flight_orders:
                order = connector.in_flight_orders[order_id]
                if hasattr(order, 'last_state') and order.last_state in ["FAILED", "CANCELLED"]:
                    error_msg = f"Order failed immediately: {getattr(order, 'last_failure_reason', 'Unknown error')}"
                    logging.error(error_msg)
                    raise HTTPException(status_code=400, detail=error_msg)
            
            logging.info(f"Placed {trade_type} order for {amount} {trading_pair} on {connector_name} (Account: {account_name}). Order ID: {order_id}")
            return order_id
            
        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            logging.error(f"Failed to place {trade_type} order: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to place trade: {str(e)}")
    
    def get_connector_instance(self, account_name: str, connector_name: str):
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
        
        if not self.connector_manager.is_connector_initialized(account_name, connector_name):
            raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found for account '{account_name}'")
        
        return self.connector_manager.get_connector(account_name, connector_name)
    
    def get_active_orders(self, account_name: str, connector_name: str) -> Dict[str, any]:
        """
        Get active orders for a specific connector.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector
            
        Returns:
            Dictionary of active orders
        """
        connector = self.get_connector_instance(account_name, connector_name)
        return {order_id: order.to_json() for order_id, order in connector.in_flight_orders.items()}
    
    async def cancel_order(self, account_name: str, connector_name: str, 
                          trading_pair: str, client_order_id: str) -> str:
        """
        Cancel an active order.
        
        Args:
            account_name: Name of the account
            connector_name: Name of the connector
            trading_pair: Trading pair
            client_order_id: Client order ID to cancel
            
        Returns:
            Client order ID that was cancelled
        """
        connector = self.get_connector_instance(account_name, connector_name)
        
        try:
            result = connector.cancel(trading_pair=trading_pair, client_order_id=client_order_id)
            logging.info(f"Cancelled order {client_order_id} on {connector_name} (Account: {account_name})")
            return result
        except Exception as e:
            logging.error(f"Failed to cancel order {client_order_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to cancel order: {str(e)}")


    async def get_orders(self, account_name: Optional[str] = None, market: Optional[str] = None, 
                        symbol: Optional[str] = None, status: Optional[str] = None,
                        start_time: Optional[int] = None, end_time: Optional[int] = None,
                        limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get order history using our AsyncDatabaseManager."""
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                query = session.query(Order)
                
                # Filter by account name if specified
                if account_name:
                    query = query.filter(Order.account_name == account_name)
                
                # Filter by connector name if specified
                if market:
                    query = query.filter(Order.connector_name == market)
                
                # Filter by trading pair if specified  
                if symbol:
                    query = query.filter(Order.trading_pair == symbol)
                
                # Filter by status if specified
                if status:
                    query = query.filter(Order.status == status)
                
                # Filter by time range if specified
                if start_time:
                    start_dt = datetime.fromtimestamp(start_time / 1000)  # Convert from milliseconds
                    query = query.filter(Order.created_at >= start_dt)
                if end_time:
                    end_dt = datetime.fromtimestamp(end_time / 1000)  # Convert from milliseconds
                    query = query.filter(Order.created_at <= end_dt)
                
                query = query.order_by(Order.created_at.desc())
                query = query.limit(limit).offset(offset)
                
                result = await session.execute(query)
                orders = result.scalars().all()
                
                # Convert to dict format
                return [
                    {
                        "order_id": order.client_order_id,
                        "account_name": order.account_name,
                        "connector_name": order.connector_name,
                        "trading_pair": order.trading_pair,
                        "trade_type": order.trade_type,
                        "order_type": order.order_type,
                        "amount": float(order.amount),
                        "price": float(order.price) if order.price else None,
                        "status": order.status,
                        "filled_amount": float(order.filled_amount),
                        "average_fill_price": float(order.average_fill_price) if order.average_fill_price else None,
                        "fee_paid": float(order.fee_paid) if order.fee_paid else None,
                        "fee_currency": order.fee_currency,
                        "created_at": order.created_at.isoformat(),
                        "updated_at": order.updated_at.isoformat(),
                        "exchange_order_id": order.exchange_order_id,
                        "error_message": order.error_message,
                    }
                    for order in orders
                ]
        except Exception as e:
            logging.error(f"Error getting orders: {e}")
            return []

    async def get_active_orders_history(self, account_name: Optional[str] = None, market: Optional[str] = None, 
                                       symbol: Optional[str] = None) -> List[Dict]:
        """Get active orders from database"""
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                query = session.query(Order).filter(
                    Order.status.in_(["SUBMITTED", "OPEN", "PARTIALLY_FILLED"])
                )
                
                # Filter by account name if specified
                if account_name:
                    query = query.filter(Order.account_name == account_name)
                
                # Filter by connector name if specified
                if market:
                    query = query.filter(Order.connector_name == market)
                
                # Filter by trading pair if specified  
                if symbol:
                    query = query.filter(Order.trading_pair == symbol)
                
                query = query.order_by(Order.created_at.desc())
                query = query.limit(1000)
                
                result = await session.execute(query)
                orders = result.scalars().all()
                
                # Convert to dict format using same structure as get_orders
                return [
                    {
                        "order_id": order.client_order_id,
                        "account_name": order.account_name,
                        "connector_name": order.connector_name,
                        "trading_pair": order.trading_pair,
                        "trade_type": order.trade_type,
                        "order_type": order.order_type,
                        "amount": float(order.amount),
                        "price": float(order.price) if order.price else None,
                        "status": order.status,
                        "filled_amount": float(order.filled_amount),
                        "average_fill_price": float(order.average_fill_price) if order.average_fill_price else None,
                        "fee_paid": float(order.fee_paid) if order.fee_paid else None,
                        "fee_currency": order.fee_currency,
                        "created_at": order.created_at.isoformat(),
                        "updated_at": order.updated_at.isoformat(),
                        "exchange_order_id": order.exchange_order_id,
                        "error_message": order.error_message,
                    }
                    for order in orders
                ]
        except Exception as e:
            logging.error(f"Error getting active orders: {e}")
            return []

    async def get_orders_summary(self, account_name: Optional[str] = None, start_time: Optional[int] = None,
                                end_time: Optional[int] = None) -> Dict:
        """Get order summary statistics"""
        orders = await self.get_orders(
            account_name=account_name,
            start_time=start_time,
            end_time=end_time,
            limit=10000  # Get all for summary
        )
        
        total_orders = len(orders)
        filled_orders = sum(1 for o in orders if o.get("status") == "FILLED")
        cancelled_orders = sum(1 for o in orders if o.get("status") == "CANCELLED")
        failed_orders = sum(1 for o in orders if o.get("status") == "FAILED")
        active_orders = sum(1 for o in orders if o.get("status") in ["SUBMITTED", "OPEN", "PARTIALLY_FILLED"])
        
        return {
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "cancelled_orders": cancelled_orders,
            "failed_orders": failed_orders,
            "active_orders": active_orders,
            "fill_rate": filled_orders / total_orders if total_orders > 0 else 0,
        }

    async def get_trades(self, account_name: Optional[str] = None, market: Optional[str] = None,
                        symbol: Optional[str] = None, trade_type: Optional[str] = None,
                        start_time: Optional[int] = None, end_time: Optional[int] = None,
                        limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get trade history using our AsyncDatabaseManager"""
        await self.ensure_db_initialized()
        
        try:
            async with self.db_manager.get_session_context() as session:
                # Join trades with orders to get account information
                query = session.query(Trade).join(Order, Trade.order_id == Order.id)
                
                # Filter by account name if specified
                if account_name:
                    query = query.filter(Order.account_name == account_name)
                
                # Filter by connector name if specified
                if market:
                    query = query.filter(Order.connector_name == market)
                
                # Filter by trading pair if specified  
                if symbol:
                    query = query.filter(Trade.trading_pair == symbol)
                
                # Filter by trade type if specified
                if trade_type:
                    query = query.filter(Trade.trade_type == trade_type)
                
                # Filter by time range if specified
                if start_time:
                    start_dt = datetime.fromtimestamp(start_time / 1000)  # Convert from milliseconds
                    query = query.filter(Trade.timestamp >= start_dt)
                if end_time:
                    end_dt = datetime.fromtimestamp(end_time / 1000)  # Convert from milliseconds
                    query = query.filter(Trade.timestamp <= end_dt)
                
                query = query.order_by(Trade.timestamp.desc())
                query = query.limit(limit).offset(offset)
                
                result = await session.execute(query)
                trades = result.scalars().all()
                
                # Convert to dict format
                return [
                    {
                        "trade_id": trade.trade_id,
                        "order_id": trade.order.client_order_id if trade.order else None,
                        "account_name": trade.order.account_name if trade.order else None,
                        "connector_name": trade.order.connector_name if trade.order else None,
                        "trading_pair": trade.trading_pair,
                        "trade_type": trade.trade_type,
                        "amount": float(trade.amount),
                        "price": float(trade.price),
                        "fee_paid": float(trade.fee_paid),
                        "fee_currency": trade.fee_currency,
                        "timestamp": trade.timestamp.isoformat(),
                    }
                    for trade in trades
                ]
        except Exception as e:
            logging.error(f"Error getting trades: {e}")
            return []
