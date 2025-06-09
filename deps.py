from fastapi import Request
from services.bots_orchestrator import BotsOrchestrator
from services.accounts_service import AccountsService
from services.docker_service import DockerService
from utils.bot_archiver import BotArchiver


def get_bots_orchestrator(request: Request) -> BotsOrchestrator:
    """Get BotsOrchestrator service from app state."""
    return request.app.state.bots_orchestrator


def get_accounts_service(request: Request) -> AccountsService:
    """Get AccountsService from app state."""
    return request.app.state.accounts_service


def get_docker_service(request: Request) -> DockerService:
    """Get DockerService from app state."""
    return request.app.state.docker_service


def get_bot_archiver(request: Request) -> BotArchiver:
    """Get BotArchiver from app state."""
    return request.app.state.bot_archiver