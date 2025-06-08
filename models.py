from typing import Any, Dict, Optional, List

from pydantic import BaseModel


class HummingbotInstanceConfig(BaseModel):
    instance_name: str
    credentials_profile: str
    image: str = "hummingbot/hummingbot:latest"
    script: Optional[str] = None
    script_config: Optional[str] = None


class ImageName(BaseModel):
    image_name: str


class Script(BaseModel):
    name: str
    content: str


class ScriptConfig(BaseModel):
    name: str
    content: Dict[str, Any]  # YAML content represented as a dictionary


class BotAction(BaseModel):
    bot_name: str


class StartBotAction(BotAction):
    log_level: str = None
    script: str = None
    conf: str = None
    async_backend: bool = False


class StopBotAction(BotAction):
    skip_order_cancellation: bool = False
    async_backend: bool = False


class ImportStrategyAction(BotAction):
    strategy: str


class ConfigureBotAction(BotAction):
    params: dict


class ShortcutAction(BotAction):
    params: list


class V2ControllerDeployment(BaseModel):
    instance_name: str
    credentials_profile: str
    controllers_config: List[str]  # List of controller config files to use
    max_global_drawdown: Optional[float] = None
    max_controller_drawdown: Optional[float] = None
    image: str = "hummingbot/hummingbot:latest"
