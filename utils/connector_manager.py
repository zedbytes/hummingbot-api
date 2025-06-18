import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
from hummingbot.client.config.config_helpers import ClientConfigAdapter, ReadOnlyClientConfigAdapter, get_connector_class
from hummingbot.client.settings import AllConnectorSettings
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.core.data_type.common import PositionMode
from hummingbot.core.utils.async_utils import safe_ensure_future

from utils.backend_api_config_adapter import BackendAPIConfigAdapter
from utils.security import BackendAPISecurity
from utils.file_system import FileSystemUtil


class ConnectorManager:
    """
    Manages the creation and caching of exchange connectors.
    Handles connector configuration and initialization.
    This is the single source of truth for all connector instances.
    """
    
    def __init__(self, secrets_manager: ETHKeyFileSecretManger, db_manager=None):
        self.secrets_manager = secrets_manager
        self.db_manager = db_manager
        self._connector_cache: Dict[str, ConnectorBase] = {}
        self._orders_recorders: Dict[str, any] = {}
        self._file_system = FileSystemUtil()
    
    async def get_connector(self, account_name: str, connector_name: str):
        """
        Get the connector object for the specified account and connector.
        Uses caching to avoid recreating connectors unnecessarily.
        Ensures proper initialization including position mode setup.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return: The connector object.
        """
        cache_key = f"{account_name}:{connector_name}"
        
        if cache_key in self._connector_cache:
            return self._connector_cache[cache_key]
        
        try:
            # Create connector with full initialization
            connector = await self._create_and_initialize_connector(account_name, connector_name)
            self._connector_cache[cache_key] = connector
            return connector
        except Exception as e:
            logging.error(f"Error creating connector {connector_name} for account {account_name}: {e}")
            raise
    
    def _create_connector(self, account_name: str, connector_name: str):
        """
        Create a new connector instance.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return: The connector object.
        """
        BackendAPISecurity.login_account(account_name=account_name, secrets_manager=self.secrets_manager)
        client_config_map = ClientConfigAdapter(ClientConfigMap())
        conn_setting = AllConnectorSettings.get_connector_settings()[connector_name]
        keys = BackendAPISecurity.api_keys(connector_name)
        read_only_config = ReadOnlyClientConfigAdapter.lock_config(client_config_map)
        
        init_params = conn_setting.conn_init_parameters(
            trading_pairs=[],
            trading_required=True,
            api_keys=keys,
            client_config_map=read_only_config,
        )
        
        connector_class = get_connector_class(connector_name)
        connector = connector_class(**init_params)
        return connector
    
    def clear_cache(self, account_name: Optional[str] = None, connector_name: Optional[str] = None):
        """
        Clear the connector cache.
        
        :param account_name: If provided, only clear cache for this account.
        :param connector_name: If provided with account_name, only clear this specific connector.
        """
        if account_name and connector_name:
            cache_key = f"{account_name}:{connector_name}"
            self._connector_cache.pop(cache_key, None)
        elif account_name:
            # Clear all connectors for this account
            keys_to_remove = [k for k in self._connector_cache.keys() if k.startswith(f"{account_name}:")]
            for key in keys_to_remove:
                self._connector_cache.pop(key)
        else:
            # Clear entire cache
            self._connector_cache.clear()
    
    @staticmethod
    def get_connector_config_map(connector_name: str):
        """
        Get the connector config map for the specified connector.
        
        :param connector_name: The name of the connector.
        :return: The connector config map.
        """
        connector_config = BackendAPIConfigAdapter(AllConnectorSettings.get_connector_config_keys(connector_name))
        return [key for key in connector_config.hb_config.__fields__.keys() if key != "connector"]
    
    async def update_connector_keys(self, account_name: str, connector_name: str, keys: dict):
        """
        Update the API keys for a connector and refresh the connector instance.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :param keys: Dictionary of API keys to update.
        :return: The updated connector instance.
        """
        BackendAPISecurity.login_account(account_name=account_name, secrets_manager=self.secrets_manager)
        connector_config = BackendAPIConfigAdapter(AllConnectorSettings.get_connector_config_keys(connector_name))
        
        for key, value in keys.items():
            setattr(connector_config, key, value)
        
        BackendAPISecurity.update_connector_keys(account_name, connector_config)
        
        # Clear the cache for this connector to force recreation with new keys
        self.clear_cache(account_name, connector_name)
        
        # Create and return new connector instance
        new_connector = self.get_connector(account_name, connector_name)
        await new_connector._update_balances()
        
        return new_connector
    
    def list_account_connectors(self, account_name: str) -> List[str]:
        """
        List all initialized connectors for a specific account.
        
        :param account_name: The name of the account.
        :return: List of connector names.
        """
        connectors = []
        for cache_key in self._connector_cache.keys():
            acc_name, conn_name = cache_key.split(":", 1)
            if acc_name == account_name:
                connectors.append(conn_name)
        return connectors
    
    def get_all_connectors(self) -> Dict[str, Dict[str, ConnectorBase]]:
        """
        Get all connectors organized by account.
        
        :return: Dictionary mapping account names to their connectors.
        """
        result = {}
        for cache_key, connector in self._connector_cache.items():
            account_name, connector_name = cache_key.split(":", 1)
            if account_name not in result:
                result[account_name] = {}
            result[account_name][connector_name] = connector
        return result
    
    def is_connector_initialized(self, account_name: str, connector_name: str) -> bool:
        """
        Check if a connector is already initialized and cached.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return: True if the connector is initialized, False otherwise.
        """
        cache_key = f"{account_name}:{connector_name}"
        return cache_key in self._connector_cache
    
    def get_connector_state(self, account_name: str, connector_name: str) -> Dict[str, any]:
        """
        Get the current state of a connector (balances, trading rules, etc).
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return: Dictionary containing connector state information.
        """
        connector = self.get_connector(account_name, connector_name)
        
        return {
            "balances": {k: float(v) for k, v in connector.get_all_balances().items()},
            "available_balances": {k: float(connector.get_available_balance(k)) 
                                 for k in connector.get_all_balances().keys()},
            "is_ready": connector.ready,
            "name": connector.name,
            "trading_required": connector.is_trading_required
        }
    
    async def _create_and_initialize_connector(self, account_name: str, connector_name: str) -> ConnectorBase:
        """
        Create and fully initialize a connector with all necessary setup.
        This includes creating the connector, starting its network, setting up order recording,
        and configuring position mode for perpetual connectors.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return: The initialized connector instance.
        """
        # Create the base connector
        connector = self._create_connector(account_name, connector_name)
        
        # Start order tracking if db_manager is available
        if self.db_manager:
            cache_key = f"{account_name}:{connector_name}"
            if cache_key not in self._orders_recorders:
                # Import OrdersRecorder dynamically to avoid circular imports
                from services.orders_recorder import OrdersRecorder
                
                # Create and start orders recorder
                orders_recorder = OrdersRecorder(self.db_manager, account_name, connector_name)
                orders_recorder.start(connector)
                self._orders_recorders[cache_key] = orders_recorder
        
        # Start the connector's network without order book tracker
        self._start_network_without_order_book(connector)
        
        # Update initial balances
        await connector._update_balances()
        
        # Set default position mode to HEDGE for perpetual connectors
        await self._set_default_position_mode(connector)
        
        logging.info(f"Initialized connector {connector_name} for account {account_name}")
        return connector
    
    async def initialize_connector_with_tracking(self, account_name: str, connector_name: str, db_manager=None) -> ConnectorBase:
        """
        DEPRECATED: Use get_connector() instead.
        This method is kept for backward compatibility but just calls get_connector().
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :param db_manager: Database manager (ignored, use constructor instead).
        :return: The initialized connector instance.
        """
        logging.warning(f"initialize_connector_with_tracking is deprecated, use get_connector() instead")
        return await self.get_connector(account_name, connector_name)
    
    def _start_network_without_order_book(self, connector: ExchangePyBase):
        """
        Start connector network tasks except the order book tracker.
        This avoids issues when there are no trading pairs configured.
        """
        try:
            # Start only the essential polling tasks if trading is required
            connector._trading_rules_polling_task = safe_ensure_future(connector._trading_rules_polling_loop())
            connector._trading_fees_polling_task = safe_ensure_future(connector._trading_fees_polling_loop())
            connector._status_polling_task = safe_ensure_future(connector._status_polling_loop())
            connector._user_stream_tracker_task = connector._create_user_stream_tracker_task()
            connector._user_stream_event_listener_task = safe_ensure_future(connector._user_stream_event_listener())
            connector._lost_orders_update_task = safe_ensure_future(connector._lost_orders_update_polling_loop())
                
            logging.info(f"Started connector network without order book tracker")
            
        except Exception as e:
            logging.error(f"Error starting connector network without order book: {e}")
    
    async def _set_default_position_mode(self, connector):
        """
        Set default position mode to HEDGE for perpetual connectors that support position modes.
        
        :param connector: The connector instance
        """
        try:
            # Check if this is a perpetual connector
            if "_perpetual" in connector.name and hasattr(connector, 'set_position_mode'):
                # Check if HEDGE mode is supported
                if hasattr(connector, 'supported_position_modes'):
                    supported_modes = connector.supported_position_modes()
                    if PositionMode.HEDGE in supported_modes:
                        # Try to call the method - it might be sync or async
                        result = connector.set_position_mode(PositionMode.HEDGE)
                        # If it's a coroutine, await it
                        if asyncio.iscoroutine(result):
                            await result
                        logging.info(f"Set default position mode to HEDGE for {connector.name}")
                    else:
                        logging.info(f"HEDGE mode not supported for {connector.name}, skipping position mode setup")
                else:
                    logging.info(f"Position modes not supported for {connector.name}, skipping position mode setup")
        except Exception as e:
            logging.warning(f"Failed to set default position mode for {connector.name}: {e}")
    
    async def stop_connector(self, account_name: str, connector_name: str):
        """
        Stop a connector and its associated services.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        """
        cache_key = f"{account_name}:{connector_name}"
        
        # Stop order recorder if exists
        if cache_key in self._orders_recorders:
            try:
                await self._orders_recorders[cache_key].stop()
                del self._orders_recorders[cache_key]
                logging.info(f"Stopped order recorder for {account_name}/{connector_name}")
            except Exception as e:
                logging.error(f"Error stopping order recorder for {account_name}/{connector_name}: {e}")
        
        # Stop connector network if exists
        if cache_key in self._connector_cache:
            try:
                connector = self._connector_cache[cache_key]
                await connector.stop_network()
                logging.info(f"Stopped connector network for {account_name}/{connector_name}")
            except Exception as e:
                logging.error(f"Error stopping connector network for {account_name}/{connector_name}: {e}")
    
    async def stop_all_connectors(self):
        """
        Stop all connectors and their associated services.
        """
        # Get all account/connector pairs
        pairs = [(k.split(":", 1)[0], k.split(":", 1)[1]) for k in self._connector_cache.keys()]
        
        # Stop each connector
        for account_name, connector_name in pairs:
            await self.stop_connector(account_name, connector_name)
    
    def list_available_credentials(self, account_name: str) -> List[str]:
        """
        List all available connector credentials for an account.
        
        :param account_name: The name of the account.
        :return: List of connector names that have credentials.
        """
        try:
            files = self._file_system.list_files(f'credentials/{account_name}/connectors')
            return [file.replace('.yml', '') for file in files if file.endswith('.yml')]
        except FileNotFoundError:
            return []