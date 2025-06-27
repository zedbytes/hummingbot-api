# Hummingbot API

A comprehensive RESTful API framework for managing trading operations across multiple exchanges. The Hummingbot API provides a centralized platform to aggregate all your trading functionalities, from basic account management to sophisticated automated trading strategies.

## What is Hummingbot API?

The Hummingbot API is designed to be your central hub for trading operations, offering:

- **Multi-Exchange Account Management**: Create and manage multiple trading accounts across different exchanges
- **Portfolio Monitoring**: Real-time balance tracking and portfolio distribution analysis
- **Trade Execution**: Execute trades, manage orders, and monitor positions across all your accounts
- **Automated Trading**: Deploy and control Hummingbot instances with automated strategies
- **Strategy Management**: Add, configure, and manage trading strategies in real-time
- **Complete Flexibility**: Build any trading product on top of this robust API framework

Whether you're building a trading dashboard, implementing algorithmic strategies, or creating a comprehensive trading platform, the Hummingbot API provides all the tools you need.

## System Dependencies

The Hummingbot API requires two essential services to function properly:

### 1. PostgreSQL Database
Stores all trading data including:
- Orders and trade history
- Account states and balances
- Positions and funding payments
- Performance metrics

### 2. EMQX Message Broker
Enables real-time communication with trading bots:
- Receives live updates from running bots
- Sends commands to control bot execution
- Handles real-time data streaming

## Installation & Setup

### Prerequisites
- Docker and Docker Compose installed
- Git for cloning the repository

### Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/hummingbot/backend-api.git
   cd backend-api
   ```

2. **Make setup script executable and run it**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. **Configure your environment**
   During setup, you'll configure several important variables:

   - **Config Password**: Used to encrypt and hash API keys and credentials for security
   - **Username & Password**: Basic authentication credentials for API access (used by dashboards and other systems)
   - **Additional configurations**: Available in the `.env` file including:
     - Broker configuration (EMQX settings)
     - Database URL
     - Market data cleanup settings
     - AWS S3 configuration (experimental)
     - Banned tokens list (for delisted tokens)

4. **Set up monitoring (Production recommended)**
   For production deployments, add observability through Logfire:
   ```bash
   export LOGFIRE_TOKEN=your_token_here
   ```
   Learn more: [Logfire Documentation](https://logfire.pydantic.dev/docs/)

After running `setup.sh`, the required Docker images (EMQX, PostgreSQL, and Hummingbot) will be running and ready.

## Running the API

You have two deployment options depending on your use case:

### For Users (Production/Simple Deployment)
```bash
./run.sh
```
This runs the API in a Docker container - simple and isolated.

### For Developers (Development Environment)
1. **Install Conda** (if not already installed)
2. **Set up the development environment**
   ```bash
   make install
   ```
   This creates a Conda environment with all dependencies.

3. **Run in development mode**
   ```bash
   ./run.sh --dev
   ```
   This starts the API from source with hot-reloading enabled.

## Getting Started

Once the API is running, you can access it at `http://localhost:8000`

### First Steps
1. **Visit the API Documentation**: Go to `http://localhost:8000/docs` to explore the interactive Swagger documentation
2. **Authenticate**: Use the username and password you configured during setup
3. **Test endpoints**: Use the Swagger interface to test API functionality

## API Overview

The Hummingbot API is organized into several functional routers:

### =3 Docker Management (`/docker`)
- Check running containers and images
- Pull new Docker images
- Start, stop, and remove containers
- Monitor container status and health

### =d Account Management (`/accounts`)
- Create and delete trading accounts
- Add/remove exchange credentials
- Monitor account states and balances
- View portfolio distribution
- Track positions and funding payments

### =� Trading Operations (`/trading`)
- Place and cancel orders across exchanges
- Monitor order status and execution
- Set leverage and position modes
- View trade history and performance
- Real-time portfolio monitoring

### > Bot Orchestration (`/bot-orchestration`)
- Discover and manage active bots
- Deploy new Hummingbot instances
- Start/stop automated strategies
- Monitor bot performance in real-time

### <� Strategy Management
- **Controllers** (`/controllers`): Manage advanced strategy controllers
- **Scripts** (`/scripts`): Handle traditional Hummingbot scripts
- Create, edit, and remove strategy files
- Configure strategy parameters

### =� Market Data (`/market-data`)
- Access real-time and historical candles
- Get trading rules and exchange information
- Monitor funding rates
- Stream live market data

### =, Backtesting (`/backtesting`)
- Test strategies against historical data
- Analyze strategy performance
- Optimize parameters

### =� Analytics (`/archived-bots`)
- Analyze performance of stopped bots
- Generate comprehensive reports
- Review historical trades and orders
- Extract insights from past strategies

## Authentication

All API endpoints require HTTP Basic Authentication. Include your configured credentials in all requests:

```bash
curl -u username:password http://localhost:8000/endpoint
```

## Support & Documentation

- **API Documentation**: Available at `http://localhost:8000/docs` when running
- **Detailed Examples**: Check the `CLAUDE.md` file for comprehensive API usage examples
- **Issues**: Report bugs and feature requests through the project's issue tracker
---

Ready to start trading? Deploy your first account and start exploring the powerful capabilities of the Hummingbot API!