import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

import logfire
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware

from config import LOGFIRE_ENVIRONMENT, BROKER_HOST, BROKER_PASSWORD, BROKER_PORT, BROKER_USERNAME
from services.bots_orchestrator import BotsOrchestrator
from services.accounts_service import AccountsService
from services.docker_service import DockerService
from utils.bot_archiver import BotArchiver
from routers import (
    accounts,
    backtesting,
    bot_orchestration,
    databases,
    docker,
    files,
    market_data,
    performance,
)

# Configure logging
import logging

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Enable debug logging for MQTT manager
logging.getLogger('services.mqtt_manager').setLevel(logging.DEBUG)

# Load environment variables early
load_dotenv()

# Environment variables
username = os.getenv("USERNAME", "admin")
password = os.getenv("PASSWORD", "admin")
debug_mode = os.getenv("DEBUG_MODE", "False").lower() in ("true", "1", "t")

# Security setup
security = HTTPBasic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for the FastAPI application.
    Handles startup and shutdown events.
    """
    # Initialize services
    bots_orchestrator = BotsOrchestrator(
        broker_host=BROKER_HOST,
        broker_port=BROKER_PORT,
        broker_username=BROKER_USERNAME,
        broker_password=BROKER_PASSWORD
    )
    
    accounts_service = AccountsService()
    docker_service = DockerService()
    bot_archiver = BotArchiver(
        os.environ.get("AWS_API_KEY"),
        os.environ.get("AWS_SECRET_KEY"),
        os.environ.get("S3_DEFAULT_BUCKET_NAME")
    )
    
    # Initialize database
    await accounts_service.ensure_db_initialized()
    
    # Store services in app state
    app.state.bots_orchestrator = bots_orchestrator
    app.state.accounts_service = accounts_service
    app.state.docker_service = docker_service
    app.state.bot_archiver = bot_archiver
    
    # Start services
    bots_orchestrator.start_update_active_bots_loop()
    accounts_service.start_update_account_state_loop()
    
    yield
    
    # Shutdown services
    bots_orchestrator.stop_update_active_bots_loop()
    accounts_service.stop_update_account_state_loop()
    
    # Close database connections
    await accounts_service.db_manager.close()


# Initialize FastAPI with metadata and lifespan
app = FastAPI(
    title="Hummingbot Backend API",
    description="API for managing Hummingbot trading instances",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Modify in production to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logfire.configure(send_to_logfire="if-token-present", environment=LOGFIRE_ENVIRONMENT, service_name="backend-api")
logfire.instrument_fastapi(app)

def auth_user(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
):
    """Authenticate user using HTTP Basic Auth"""
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = f"{username}".encode("utf8")
    is_correct_username = secrets.compare_digest(
        current_username_bytes, correct_username_bytes
    )
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = f"{password}".encode("utf8")
    is_correct_password = secrets.compare_digest(
        current_password_bytes, correct_password_bytes
    )
    if not (is_correct_username and is_correct_password) and not debug_mode:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Include all routers with authentication
app.include_router(manage_docker.router, dependencies=[Depends(auth_user)])
app.include_router(manage_accounts.router, dependencies=[Depends(auth_user)])
app.include_router(manage_bot_orchestration.router, dependencies=[Depends(auth_user)])
app.include_router(manage_files.router, dependencies=[Depends(auth_user)])
app.include_router(manage_market_data.router, dependencies=[Depends(auth_user)])
app.include_router(manage_backtesting.router, dependencies=[Depends(auth_user)])
app.include_router(manage_databases.router, dependencies=[Depends(auth_user)])
app.include_router(manage_performance.router, dependencies=[Depends(auth_user)])

@app.get("/")
async def root():
    """API root endpoint returning basic information."""
    return {
        "name": "Backend API",
        "version": "0.2.0",
        "status": "running",
    }