import logging
from typing import Dict, Optional

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
from hummingbot.client.config.config_helpers import ClientConfigAdapter, ReadOnlyClientConfigAdapter, get_connector_class
from hummingbot.client.settings import AllConnectorSettings

from utils.backend_api_config_adapter import BackendAPIConfigAdapter
from utils.security import BackendAPISecurity


class ConnectorManager:
    """
    Manages the creation and caching of exchange connectors.
    Handles connector configuration and initialization.
    """
    
    def __init__(self, secrets_manager: ETHKeyFileSecretManger):
        self.secrets_manager = secrets_manager
        self._connector_cache: Dict[str, Dict[str, any]] = {}
    
    def get_connector(self, account_name: str, connector_name: str):
        """
        Get the connector object for the specified account and connector.
        Uses caching to avoid recreating connectors unnecessarily.
        
        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return: The connector object.
        """
        cache_key = f"{account_name}:{connector_name}"
        
        if cache_key in self._connector_cache:
            return self._connector_cache[cache_key]
        
        try:
            connector = self._create_connector(account_name, connector_name)
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