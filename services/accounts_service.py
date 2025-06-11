import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import HTTPException
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger

from config import settings
from database import AsyncDatabaseManager, AccountRepository
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
    }

    def __init__(self,
                 update_account_state_interval_minutes: int = 5,
                 default_quote: str = "USDT",
                 account_history_file: str = "account_state_history.json"):
        self.secrets_manager = ETHKeyFileSecretManger(settings.security.config_password)
        self.connector_manager = ConnectorManager(self.secrets_manager)
        self.accounts = {}
        self.accounts_state = {}
        self.account_state_update_event = asyncio.Event()
        self.initialize_accounts()
        self.update_account_state_interval = update_account_state_interval_minutes * 60
        self.default_quote = default_quote
        self.history_file = account_history_file
        self._update_account_state_task: Optional[asyncio.Task] = None
        
        # Database setup
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

    def start_update_account_state_loop(self):
        """
        Start the loop that updates the balances of all the accounts at a fixed interval.
        :return:
        """
        self._update_account_state_task = asyncio.create_task(self.update_account_state_loop())

    def stop_update_account_state_loop(self):
        """
        Stop the loop that updates the balances of all the accounts at a fixed interval.
        :return:
        """
        if self._update_account_state_task:
            self._update_account_state_task.cancel()
        self._update_account_state_task = None

    async def update_account_state_loop(self):
        """
        The loop that updates the balances of all the accounts at a fixed interval.
        :return:
        """
        while True:
            try:
                await self.check_all_connectors()
                await self.update_balances()
                await self.update_trading_rules()
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
            # Fallback to JSON file
            timestamp = datetime.now().isoformat()
            state_to_dump = {"timestamp": timestamp, "state": self.accounts_state}
            if not file_system.path_exists(path=f"data/{self.history_file}"):
                file_system.add_file(directory="data", file_name=self.history_file, content=json.dumps(state_to_dump) + "\n")
            else:
                file_system.append_to_file(directory="data", file_name=self.history_file, content=json.dumps(state_to_dump) + "\n")

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
            # Fallback to JSON file (simplified, no pagination)
            history = []
            try:
                with open("bots/data/" + self.history_file, "r") as file:
                    for line in file:
                        if line.strip():  # Check if the line is not empty
                            history.append(json.loads(line))
                            if limit and len(history) >= limit:
                                break
            except FileNotFoundError:
                logging.warning("No account state history file found.")
            return history, None, False

    async def check_all_connectors(self):
        """
        Check all avaialble credentials for all accounts and see if the connectors are created.
        :return:
        """
        for account_name in self.list_accounts():
            for connector_name in self.list_credentials(account_name):
                try:
                    connector_name = connector_name.split(".")[0]
                    if account_name not in self.accounts or connector_name not in self.accounts[account_name]:
                        self.initialize_connector(account_name, connector_name)
                except Exception as e:
                    logging.error(f"Error initializing connector {connector_name}: {e}")

    def initialize_accounts(self):
        """
        Initialize all the connectors that are connected to each account.
        :return:
        """
        for account_name in self.list_accounts():
            self.accounts[account_name] = {}
            for connector_name in self.list_credentials(account_name):
                try:
                    connector_name = connector_name.split(".")[0]
                    connector = self.connector_manager.get_connector(account_name, connector_name)
                    self.accounts[account_name][connector_name] = connector
                except Exception as e:
                    logging.error(f"Error initializing connector {connector_name}: {e}")

    def initialize_account(self, account_name: str):
        """
        Initialize all the connectors that are connected to the specified account.
        :param account_name: The name of the account.
        :return:
        """
        for connector_name in self.list_credentials(account_name):
            try:
                connector_name = connector_name.split(".")[0]
                self.initialize_connector(account_name, connector_name)
            except Exception as e:
                logging.error(f"Error initializing connector {connector_name}: {e}")

    def initialize_connector(self, account_name: str, connector_name: str):
        """
        Initialize the specified connector for the specified account.
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return:
        """
        if account_name not in self.accounts:
            self.accounts[account_name] = {}
        try:
            connector = self.connector_manager.get_connector(account_name, connector_name)
            self.accounts[account_name][connector_name] = connector
        except Exception as e:
            logging.error(f"Error initializing connector {connector_name}: {e}")

    async def update_balances(self):
        tasks = []
        for account_name, connectors in self.accounts.items():
            for connector_instance in connectors.values():
                tasks.append(self._safe_update_balances(connector_instance))
        await asyncio.gather(*tasks)

    async def _safe_update_balances(self, connector_instance):
        try:
            await connector_instance._update_balances()
        except Exception as e:
            logging.error(f"Error updating balances for connector {connector_instance}: {e}")

    async def update_trading_rules(self):
        tasks = []
        for account_name, connectors in self.accounts.items():
            for connector_instance in connectors.values():
                tasks.append(self._safe_update_trading_rules(connector_instance))
        await asyncio.gather(*tasks)

    async def _safe_update_trading_rules(self, connector_instance):
        try:
            await connector_instance._update_trading_rules()
        except Exception as e:
            logging.error(f"Error updating trading rules for connector {connector_instance}: {e}")

    async def update_account_state(self):
        for account_name, connectors in self.accounts.items():
            if account_name not in self.accounts_state:
                self.accounts_state[account_name] = {}
            for connector_name, connector in connectors.items():
                tokens_info = []
                try:
                    balances = [{"token": key, "units": value} for key, value in connector.get_all_balances().items() if
                                value != Decimal("0") and key not in settings.app.banned_tokens]
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
                    self.account_state_update_event.set()
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

    async def add_connector_keys(self, account_name: str, connector_name: str, keys: dict):
        new_connector = await self.connector_manager.update_connector_keys(account_name, connector_name, keys)
        self.accounts[account_name][connector_name] = new_connector
        await self.update_account_state()
        await self.dump_account_state()


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

    def delete_credentials(self, account_name: str, connector_name: str):
        """
        Delete the credentials of the specified connector for the specified account.
        :param account_name:
        :param connector_name:
        :return:
        """
        if file_system.path_exists(f"credentials/{account_name}/connectors/{connector_name}.yml"):
            file_system.delete_file(directory=f"credentials/{account_name}/connectors", file_name=f"{connector_name}.yml")
            if connector_name in self.accounts[account_name]:
                self.accounts[account_name].pop(connector_name)
            if connector_name in self.accounts_state[account_name]:
                self.accounts_state[account_name].pop(connector_name)
            # Clear the connector from cache
            self.connector_manager.clear_cache(account_name, connector_name)

    def add_account(self, account_name: str):
        """
        Add a new account.
        :param account_name:
        :return:
        """
        if account_name in self.accounts:
            raise HTTPException(status_code=400, detail="Account already exists.")
        files_to_copy = ["conf_client.yml", "conf_fee_overrides.yml", "hummingbot_logs.yml", ".password_verification"]
        file_system.create_folder('credentials', account_name)
        file_system.create_folder(f'credentials/{account_name}', "connectors")
        for file in files_to_copy:
            file_system.copy_file(f"credentials/master_account/{file}", f"credentials/{account_name}/{file}")
        self.accounts[account_name] = {}
        self.accounts_state[account_name] = {}

    def delete_account(self, account_name: str):
        """
        Delete the specified account.
        :param account_name:
        :return:
        """
        file_system.delete_folder('credentials', account_name)
        self.accounts.pop(account_name)
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
