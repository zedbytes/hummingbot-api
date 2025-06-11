#!/bin/bash

# Backend API Setup Script
# This script creates a comprehensive .env file with all configuration options
# following the Pydantic Settings structure established in config.py

set -e  # Exit on any error

echo "🚀 Backend API Environment Setup"
echo "================================="
echo ""

# Colors for better output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to prompt for input with default value
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local result
    
    echo -n -e "${CYAN}$prompt${NC} [${YELLOW}$default${NC}]: "
    read -r result
    echo "${result:-$default}"
}

# Function to prompt for password (hidden input)
prompt_password() {
    local prompt="$1"
    local default="$2"
    local result
    
    echo -n -e "${CYAN}$prompt${NC} [${YELLOW}$default${NC}]: "
    read -r -s result
    echo ""  # New line after hidden input
    echo "${result:-$default}"
}

echo -e "${BLUE}📁 Project Configuration${NC}"
echo "========================"

# Basic paths and project settings
BOTS_PATH=$(prompt_with_default "Bots directory path" "$(pwd)")
CONFIG_PASSWORD=$(prompt_password "Configuration encryption password" "a")

echo ""
echo -e "${PURPLE}🔐 Security Configuration${NC}"
echo "========================="

# Security settings
USERNAME=$(prompt_with_default "API username" "admin")
PASSWORD=$(prompt_password "API password" "admin")
DEBUG_MODE=$(prompt_with_default "Enable debug mode (true/false)" "false")

echo ""
echo -e "${GREEN}🔗 MQTT Broker Configuration${NC}"
echo "============================="

# Broker settings
BROKER_HOST=$(prompt_with_default "MQTT broker host" "localhost")
BROKER_PORT=$(prompt_with_default "MQTT broker port" "1883")
BROKER_USERNAME=$(prompt_with_default "MQTT broker username" "admin")
BROKER_PASSWORD=$(prompt_password "MQTT broker password" "password")

echo ""
echo -e "${YELLOW}💾 Database Configuration${NC}"
echo "========================="

# Database settings
DATABASE_URL=$(prompt_with_default "Database URL" "postgresql+asyncpg://hbot:backend-api@localhost:5432/backend_api")

echo ""
echo -e "${CYAN}📊 Market Data Configuration${NC}"
echo "============================"

# Market data settings
CLEANUP_INTERVAL=$(prompt_with_default "Feed cleanup interval (seconds)" "300")
FEED_TIMEOUT=$(prompt_with_default "Feed timeout (seconds)" "600")

echo ""
echo -e "${PURPLE}☁️ AWS Configuration (Optional)${NC}"
echo "==============================="

# AWS settings (optional)
AWS_API_KEY=$(prompt_with_default "AWS API Key (optional)" "")
AWS_SECRET_KEY=$(prompt_password "AWS Secret Key (optional)" "")
S3_BUCKET=$(prompt_with_default "S3 Default Bucket (optional)" "")

echo ""
echo -e "${BLUE}⚙️ Application Settings${NC}"
echo "======================"

# Application settings
LOGFIRE_ENV=$(prompt_with_default "Logfire environment" "dev")
BANNED_TOKENS=$(prompt_with_default "Banned tokens (comma-separated)" "NAV,ARS,ETHW,ETHF")

echo ""
echo -e "${GREEN}📝 Creating .env file...${NC}"

# Create .env file with proper structure and comments
cat > .env << EOF
# =================================================================
# Backend API Environment Configuration
# Generated on: $(date)
# =================================================================

# =================================================================
# 🔐 Security Configuration
# =================================================================
USERNAME=$USERNAME
PASSWORD=$PASSWORD
DEBUG_MODE=$DEBUG_MODE
CONFIG_PASSWORD=$CONFIG_PASSWORD

# =================================================================
# 🔗 MQTT Broker Configuration (BROKER_*)
# =================================================================
BROKER_HOST=$BROKER_HOST
BROKER_PORT=$BROKER_PORT
BROKER_USERNAME=$BROKER_USERNAME
BROKER_PASSWORD=$BROKER_PASSWORD

# =================================================================
# 💾 Database Configuration (DATABASE_*)
# =================================================================
DATABASE_URL=$DATABASE_URL

# =================================================================
# 📊 Market Data Feed Manager Configuration (MARKET_DATA_*)
# =================================================================
MARKET_DATA_CLEANUP_INTERVAL=$CLEANUP_INTERVAL
MARKET_DATA_FEED_TIMEOUT=$FEED_TIMEOUT

# =================================================================
# ☁️ AWS Configuration (AWS_*) - Optional
# =================================================================
AWS_API_KEY=$AWS_API_KEY
AWS_SECRET_KEY=$AWS_SECRET_KEY
AWS_S3_DEFAULT_BUCKET_NAME=$S3_BUCKET

# =================================================================
# ⚙️ Application Settings
# =================================================================
LOGFIRE_ENVIRONMENT=$LOGFIRE_ENV
BANNED_TOKENS=$BANNED_TOKENS

# =================================================================
# 📁 Legacy Settings (maintained for backward compatibility)
# =================================================================
BOTS_PATH=$BOTS_PATH

EOF

echo -e "${GREEN}✅ .env file created successfully!${NC}"
echo ""

# Display configuration summary
echo -e "${BLUE}📋 Configuration Summary${NC}"
echo "======================="
echo -e "${CYAN}Security:${NC} Username: $USERNAME, Debug: $DEBUG_MODE"
echo -e "${CYAN}Broker:${NC} $BROKER_HOST:$BROKER_PORT"
echo -e "${CYAN}Database:${NC} ${DATABASE_URL%%@*}@[hidden]"
echo -e "${CYAN}Market Data:${NC} Cleanup: ${CLEANUP_INTERVAL}s, Timeout: ${FEED_TIMEOUT}s"
echo -e "${CYAN}Environment:${NC} $LOGFIRE_ENV"

if [ -n "$AWS_API_KEY" ]; then
    echo -e "${CYAN}AWS:${NC} Configured with S3 bucket: $S3_BUCKET"
else
    echo -e "${CYAN}AWS:${NC} Not configured (optional)"
fi

echo ""
echo -e "${GREEN}🎉 Setup Complete!${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Review the .env file if needed: ${BLUE}cat .env${NC}"
echo "2. Install dependencies: ${BLUE}make install${NC}"
echo "3. Start the API: ${BLUE}make run${NC}"
echo ""
echo -e "${PURPLE}💡 Pro tip:${NC} You can modify environment variables in .env file anytime"
echo -e "${PURPLE}📚 Documentation:${NC} Check config.py for all available settings"
echo ""