import asyncio
import logging
import time
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.core.clock import Clock, ClockMode

# Create module-specific logger
logger = logging.getLogger(__name__)

from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger
from hummingbot.client.config.config_helpers import ClientConfigAdapter, ReadOnlyClientConfigAdapter, get_connector_class
from hummingbot.client.settings import AllConnectorSettings
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionMode, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState

from utils.file_system import FileSystemUtil, fs_util
from utils.hummingbot_api_config_adapter import HummingbotAPIConfigAdapter
from utils.security import BackendAPISecurity


class ConnectorManager:
    """
    Manages the creation and caching of exchange connectors.
    Handles connector configuration and initialization.
    This is the single source of truth for all connector instances.
    """

    def __init__(self, secrets_manager: ETHKeyFileSecretManger, clock: Clock, db_manager=None):
        self.secrets_manager = secrets_manager
        self.db_manager = db_manager
        self._connector_cache: Dict[str, ConnectorBase] = {}
        self._orders_recorders: Dict[str, any] = {}
        self._funding_recorders: Dict[str, any] = {}
        self._status_polling_tasks: Dict[str, asyncio.Task] = {}
        self.clock = clock

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

        # Create connector with full initialization
        connector = await self._create_and_initialize_connector(account_name, connector_name)
        return connector

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

        # Debug logging
        logger.info(f"Creating connector {connector_name} for account {account_name}")
        logger.debug(f"API keys retrieved: {list(keys.keys()) if keys else 'None'}")

        read_only_config = ReadOnlyClientConfigAdapter.lock_config(client_config_map)

        init_params = conn_setting.conn_init_parameters(
            trading_pairs=[],
            trading_required=True,
            api_keys=keys,
            client_config_map=read_only_config,
        )

        # Debug logging
        logger.debug(f"Init params keys: {list(init_params.keys())}")

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
        connector_config = HummingbotAPIConfigAdapter(AllConnectorSettings.get_connector_config_keys(connector_name))
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
        connector_config = HummingbotAPIConfigAdapter(AllConnectorSettings.get_connector_config_keys(connector_name))

        for key, value in keys.items():
            setattr(connector_config, key, value)

        BackendAPISecurity.update_connector_keys(account_name, connector_config)

        # Re-decrypt all credentials to ensure the new keys are available
        BackendAPISecurity.decrypt_all(account_name=account_name)

        # Clear the cache for this connector to force recreation with new keys
        self.clear_cache(account_name, connector_name)

        # Create and return new connector instance
        new_connector = await self.get_connector(account_name, connector_name)

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

    async def _create_and_initialize_connector(self, account_name: str, connector_name: str) -> ConnectorBase:
        """
        Create and fully initialize a connector with all necessary setup.
        This includes creating the connector, starting its network, setting up order recording,
        and configuring position mode for perpetual connectors.

        :param account_name: The name of the account.
        :param connector_name: The name of the connector.
        :return: The initialized connector instance.
        """
        cache_key = f"{account_name}:{connector_name}"
        # Create the base connector
        connector = self._create_connector(account_name, connector_name)
        self.clock.add_iterator(connector)

        # Initialize symbol map
        await connector._initialize_trading_pair_symbol_map()

        # Update initial balances
        await connector._update_balances()

        # Set default position mode to HEDGE for perpetual connectors
        if "_perpetual" in connector_name:
            if PositionMode.HEDGE in connector.supported_position_modes():
                connector.set_position_mode(PositionMode.HEDGE)
            await connector._update_positions()

        self._connector_cache[cache_key] = connector

        # Load existing orders from database before starting network
        if self.db_manager:
            await self._load_existing_orders_from_database(connector, account_name, connector_name)

        # Start order tracking if db_manager is available
        if self.db_manager:
            if cache_key not in self._orders_recorders:
                # Import OrdersRecorder dynamically to avoid circular imports
                from services.orders_recorder import OrdersRecorder

                # Create and start orders recorder
                orders_recorder = OrdersRecorder(self.db_manager, account_name, connector_name)
                orders_recorder.start(connector)
                self._orders_recorders[cache_key] = orders_recorder

            # Start funding tracking for perpetual connectors
            if "_perpetual" in connector_name and cache_key not in self._funding_recorders:
                # Import FundingRecorder dynamically to avoid circular imports
                from services.funding_recorder import FundingRecorder

                # Create and start funding recorder
                funding_recorder = FundingRecorder(self.db_manager, account_name, connector_name)
                funding_recorder.start(connector)
                self._funding_recorders[cache_key] = funding_recorder

        # Network will be started automatically by the clock system (using patched start_network)

        logger.info(f"Initialized connector {connector_name} for account {account_name}")
        return connector


    async def _load_existing_orders_from_database(self, connector: ConnectorBase, account_name: str, connector_name: str):
        """
        Load existing active orders from database and add them to connector's in_flight_orders.
        This ensures that orders placed before an API restart can still be managed.

        :param connector: The connector instance to load orders into
        :param account_name: The name of the account
        :param connector_name: The name of the connector
        """
        try:
            # Import OrderRepository dynamically to avoid circular imports
            from database import OrderRepository

            async with self.db_manager.get_session_context() as session:
                order_repo = OrderRepository(session)

                # Get active orders from database for this account/connector
                active_orders = await order_repo.get_active_orders(account_name=account_name, connector_name=connector_name)

                logger.info(f"Loading {len(active_orders)} existing active orders for {account_name}/{connector_name}")

                for order_record in active_orders:
                    try:
                        # Convert database order to InFlightOrder
                        in_flight_order = self._convert_db_order_to_in_flight_order(order_record)

                        # Add to connector's in_flight_orders
                        connector.in_flight_orders[in_flight_order.client_order_id] = in_flight_order

                        logger.debug(f"Loaded order {in_flight_order.client_order_id} from database into connector")

                    except Exception as e:
                        logger.error(f"Error converting database order {order_record.client_order_id} to InFlightOrder: {e}")
                        continue

                logger.info(
                    f"Successfully loaded {len(connector.in_flight_orders)} in-flight orders for {account_name}/{connector_name}"
                )

        except Exception as e:
            logger.error(f"Error loading existing orders from database for {account_name}/{connector_name}: {e}")

    def _convert_db_order_to_in_flight_order(self, order_record) -> InFlightOrder:
        """
        Convert a database Order record to a Hummingbot InFlightOrder object.

        :param order_record: Database Order model instance
        :return: InFlightOrder instance
        """
        # Map database status to OrderState
        status_mapping = {
            "SUBMITTED": OrderState.PENDING_CREATE,
            "OPEN": OrderState.OPEN,
            "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
            "FILLED": OrderState.FILLED,
            "CANCELLED": OrderState.CANCELED,
            "FAILED": OrderState.FAILED,
        }

        # Get the appropriate OrderState
        order_state = status_mapping.get(order_record.status, OrderState.PENDING_CREATE)

        # Convert string enums to proper enum instances
        try:
            order_type = OrderType[order_record.order_type]
        except (KeyError, ValueError):
            logger.warning(f"Unknown order type '{order_record.order_type}', defaulting to LIMIT")
            order_type = OrderType.LIMIT

        try:
            trade_type = TradeType[order_record.trade_type]
        except (KeyError, ValueError):
            logger.warning(f"Unknown trade type '{order_record.trade_type}', defaulting to BUY")
            trade_type = TradeType.BUY

        # Convert creation timestamp - use order creation time or current time as fallback
        creation_timestamp = order_record.created_at.timestamp() if order_record.created_at else time.time()

        # Create InFlightOrder instance
        in_flight_order = InFlightOrder(
            client_order_id=order_record.client_order_id,
            trading_pair=order_record.trading_pair,
            order_type=order_type,
            trade_type=trade_type,
            amount=Decimal(str(order_record.amount)),
            creation_timestamp=creation_timestamp,
            price=Decimal(str(order_record.price)) if order_record.price else None,
            exchange_order_id=order_record.exchange_order_id,
            initial_state=order_state,
            leverage=1,  # Default leverage
            position=PositionAction.NIL,  # Default position action
        )

        # Update current state and filled amount if order has progressed
        in_flight_order.current_state = order_state
        if order_record.filled_amount:
            in_flight_order.executed_amount_base = Decimal(str(order_record.filled_amount))
        if order_record.average_fill_price:
            in_flight_order.last_executed_quantity = Decimal(str(order_record.filled_amount or 0))
            in_flight_order.last_executed_price = Decimal(str(order_record.average_fill_price))

        return in_flight_order

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
                logger.info(f"Stopped order recorder for {account_name}/{connector_name}")
            except Exception as e:
                logger.error(f"Error stopping order recorder for {account_name}/{connector_name}: {e}")

        # Stop funding recorder if exists
        if cache_key in self._funding_recorders:
            try:
                await self._funding_recorders[cache_key].stop()
                del self._funding_recorders[cache_key]
                logger.info(f"Stopped funding recorder for {account_name}/{connector_name}")
            except Exception as e:
                logger.error(f"Error stopping funding recorder for {account_name}/{connector_name}: {e}")

        # Stop manual status polling task if exists
        if cache_key in self._status_polling_tasks:
            try:
                self._status_polling_tasks[cache_key].cancel()
                del self._status_polling_tasks[cache_key]
                logger.info(f"Stopped manual status polling for {account_name}/{connector_name}")
            except Exception as e:
                logger.error(f"Error stopping manual status polling for {account_name}/{connector_name}: {e}")

        # Stop connector netwowrk if exists
        if cache_key in self._connector_cache:
            try:
                connector = self._connector_cache[cache_key]
                await connector.stop_network()
                logger.info(f"Stopped connector network for {account_name}/{connector_name}")
            except Exception as e:
                logger.error(f"Error stopping connector network for {account_name}/{connector_name}: {e}")

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
            files = fs_util.list_files(f"credentials/{account_name}/connectors")
            return [file.replace(".yml", "") for file in files if file.endswith(".yml")]
        except FileNotFoundError:
            return []
