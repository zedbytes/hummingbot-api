from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from enum import Enum


class ControllerType(str, Enum):
    DIRECTIONAL_TRADING = "directional_trading"
    MARKET_MAKING = "market_making"
    GENERIC = "generic"


class Script(BaseModel):
    name: str = Field(description="Script name (without .py extension)")
    content: str = Field(description="Python script content")


class ScriptConfig(BaseModel):
    name: str = Field(description="Config name (without .yml extension)")
    content: Dict[str, Any] = Field(description="YAML content as dictionary")


class Controller(BaseModel):
    name: str = Field(description="Controller name (without .py extension)")
    type: ControllerType = Field(description="Controller category")
    content: str = Field(description="Python controller content")


class ControllerConfig(BaseModel):
    name: str = Field(description="Config name (without .yml extension)")
    content: Dict[str, Any] = Field(description="YAML content as dictionary")


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