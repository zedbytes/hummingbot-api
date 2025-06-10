import os

from dotenv import load_dotenv

load_dotenv()

CONTROLLERS_PATH = "bots/conf/controllers"
CONTROLLERS_MODULE = "bots.controllers"
CONFIG_PASSWORD = os.getenv("CONFIG_PASSWORD", "a")
BROKER_HOST = os.getenv("BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("BROKER_PORT", 1883))
BROKER_USERNAME = os.getenv("BROKER_USERNAME", "admin")
BROKER_PASSWORD = os.getenv("BROKER_PASSWORD", "password")
PASSWORD_VERIFICATION_PATH = "bots/credentials/master_account/.password_verification"
BANNED_TOKENS = os.getenv("BANNED_TOKENS", "NAV,ARS,ETHW,ETHF").split(",")
LOGFIRE_ENVIRONMENT = os.getenv("LOGFIRE_ENVIRONMENT", "dev")

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://hbot:backend-api@localhost:5432/backend_api")
