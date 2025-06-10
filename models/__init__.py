# Bot models
from .bot import (
    ControllerType,
    Script,
    ScriptConfig,
    Controller,
    ControllerConfig,
    BotAction,
    StartBotAction,
    StopBotAction,
    ImportStrategyAction,
    ConfigureBotAction,
    ShortcutAction,
)

# Deployment models
from .deployment import V2ScriptDeployment, V2ControllerDeployment

# Docker models  
from .docker import DockerImage

# Pagination models
from .pagination import PaginatedResponse, PaginationParams, TimeRangePaginationParams

# Backward compatibility aliases
HummingbotInstanceConfig = V2ScriptDeployment  # For backward compatibility
ImageName = DockerImage  # For backward compatibility

__all__ = [
    # Bot models
    "ControllerType",
    "Script",
    "ScriptConfig",
    "Controller", 
    "ControllerConfig",
    "BotAction",
    "StartBotAction",
    "StopBotAction",
    "ImportStrategyAction",
    "ConfigureBotAction",
    "ShortcutAction",
    # Deployment models
    "V2ScriptDeployment",
    "V2ControllerDeployment",
    # Docker models
    "DockerImage",
    # Pagination models
    "PaginatedResponse",
    "PaginationParams", 
    "TimeRangePaginationParams",
    # Backward compatibility
    "HummingbotInstanceConfig",  # Alias for V2ScriptDeployment
    "ImageName",  # Alias for DockerImage
]