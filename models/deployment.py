from typing import Optional, List
from pydantic import BaseModel, Field


class V2ScriptDeployment(BaseModel):
    instance_name: str = Field(description="Unique name for the bot instance")
    credentials_profile: str = Field(description="Name of the credentials profile to use")
    image: str = Field(default="hummingbot/hummingbot:latest", description="Docker image for the Hummingbot instance")
    script: Optional[str] = Field(default=None, description="Name of the script to run (without .py extension)")
    script_config: Optional[str] = Field(default=None, description="Name of the script configuration file (without .yml extension)")


class V2ControllerDeployment(BaseModel):
    instance_name: str = Field(description="Unique name for the bot instance")
    credentials_profile: str = Field(description="Name of the credentials profile to use")
    controllers_config: List[str] = Field(description="List of controller configuration files to use (without .yml extension)")
    max_global_drawdown: Optional[float] = Field(default=None, description="Maximum allowed global drawdown percentage (0.0-1.0)")
    max_controller_drawdown: Optional[float] = Field(default=None, description="Maximum allowed per-controller drawdown percentage (0.0-1.0)")
    image: str = Field(default="hummingbot/hummingbot:latest", description="Docker image for the Hummingbot instance")