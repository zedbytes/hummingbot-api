from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from enum import Enum
from decimal import Decimal
from hummingbot.core.data_type.common import OrderType, TradeType, PositionAction


class ControllerType(str, Enum):
    DIRECTIONAL_TRADING = "directional_trading"
    MARKET_MAKING = "market_making"
    GENERIC = "generic"


class FileContent(BaseModel):
    """Base model for file content"""
    content: str = Field(description="File content")


class ConfigContent(BaseModel):
    """Base model for configuration content"""
    content: Dict[str, Any] = Field(description="Configuration content as dictionary")


class TypedFileContent(FileContent):
    """File content with a type classification"""
    type: Optional[ControllerType] = Field(default=None, description="Content category")


# Specific models using base classes
class Script(FileContent):
    """Python script content"""
    pass


class ScriptConfig(ConfigContent):
    """Script configuration content"""
    pass


class Controller(TypedFileContent):
    """Controller content with optional type (type can come from URL path)"""
    pass


class ControllerConfig(ConfigContent):
    """Controller configuration content"""
    pass


class TradeRequest(BaseModel):
    """Request model for placing trades"""
    account_name: str = Field(description="Name of the account to trade with")
    connector_name: str = Field(description="Name of the connector/exchange")
    trading_pair: str = Field(description="Trading pair (e.g., BTC-USDT)")
    trade_type: TradeType = Field(description="Whether to buy or sell")
    amount: Decimal = Field(description="Amount to trade", gt=0)
    order_type: OrderType = Field(default=OrderType.LIMIT, description="Type of order")
    price: Optional[Decimal] = Field(default=None, description="Price for limit orders")
    position_action: Optional[PositionAction] = Field(default=PositionAction.OPEN, description="Position action for perpetual contracts (OPEN/CLOSE)")


class TradeResponse(BaseModel):
    """Response model for trade execution"""
    order_id: str = Field(description="Client order ID assigned by the connector")
    account_name: str = Field(description="Account used for the trade")
    connector_name: str = Field(description="Connector used for the trade")
    trading_pair: str = Field(description="Trading pair")
    trade_type: TradeType = Field(description="Trade type")
    amount: Decimal = Field(description="Trade amount")
    order_type: OrderType = Field(description="Order type")
    price: Optional[Decimal] = Field(description="Order price")
    status: str = Field(default="submitted", description="Order status")


class BotAction(BaseModel):
    bot_name: str = Field(description="Name of the bot instance to act upon")


class StartBotAction(BotAction):
    log_level: Optional[str] = Field(default=None, description="Logging level (DEBUG, INFO, WARNING, ERROR)")
    script: Optional[str] = Field(default=None, description="Script name to run (without .py extension)")
    conf: Optional[str] = Field(default=None, description="Configuration file name (without .yml extension)")
    async_backend: bool = Field(default=False, description="Whether to run in async backend mode")


class StopBotAction(BotAction):
    skip_order_cancellation: bool = Field(default=False, description="Whether to skip cancelling open orders when stopping")
    async_backend: bool = Field(default=False, description="Whether to run in async backend mode")


class ImportStrategyAction(BotAction):
    strategy: str = Field(description="Name of the strategy to import")


class ConfigureBotAction(BotAction):
    params: dict = Field(description="Configuration parameters to update")


class ShortcutAction(BotAction):
    params: list = Field(description="List of shortcut parameters")