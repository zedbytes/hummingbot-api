from typing import Optional, List
from pydantic import BaseModel


class V2ScriptDeployment(BaseModel):
    instance_name: str
    credentials_profile: str
    image: str = "hummingbot/hummingbot:latest"
    script: Optional[str] = None
    script_config: Optional[str] = None


class V2ControllerDeployment(BaseModel):
    instance_name: str
    credentials_profile: str
    controllers_config: List[str]  # List of controller config files to use
    max_global_drawdown: Optional[float] = None
    max_controller_drawdown: Optional[float] = None
    image: str = "hummingbot/hummingbot:latest"