from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from enum import Enum


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