from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime
from hummingbot.core.data_type.common import OrderType, TradeType, PositionAction


class TradeRequest(BaseModel):
    """Request model for placing trades"""
    account_name: str = Field(description="Name of the account to trade with")
    connector_name: str = Field(description="Name of the connector/exchange")
    trading_pair: str = Field(description="Trading pair (e.g., BTC-USDT)")
    trade_type: TradeType = Field(description="Whether to buy or sell")
    amount: Decimal = Field(description="Amount to trade", gt=0)
    order_type: OrderType = Field(default=OrderType.LIMIT, description="Type of order")
    price: Optional[Decimal] = Field(default=None, description="Price for limit orders")
    position_action: PositionAction = Field(default=PositionAction.OPEN, description="Position action for perpetual contracts (OPEN/CLOSE)")


class TradeResponse(BaseModel):
    """Response model for trade execution"""
    order_id: str = Field(description="Client order ID assigned by the connector")
    account_name: str = Field(description="Account used for the trade")
    connector_name: str = Field(description="Connector used for the trade")
    trading_pair: str = Field(description="Trading pair")
    trade_type: TradeType = Field(description="Trade type")
    amount: Decimal = Field(description="Trade amount")
    order_type: OrderType = Field(description="Order type")
    price: Optional[Decimal] = Field(description="Order price")
    status: str = Field(default="submitted", description="Order status")


class TokenInfo(BaseModel):
    """Information about a token balance"""
    token: str = Field(description="Token symbol")
    balance: Decimal = Field(description="Token balance")
    value_usd: Optional[Decimal] = Field(None, description="USD value of the balance")


class ConnectorBalance(BaseModel):
    """Balance information for a connector"""
    connector_name: str = Field(description="Name of the connector")
    tokens: List[TokenInfo] = Field(description="List of token balances")


class AccountBalance(BaseModel):
    """Balance information for an account"""
    account_name: str = Field(description="Name of the account")
    connectors: List[ConnectorBalance] = Field(description="List of connector balances")


class PortfolioState(BaseModel):
    """Complete portfolio state across all accounts"""
    accounts: List[AccountBalance] = Field(description="List of account balances")
    timestamp: datetime = Field(description="Timestamp of the portfolio state")


class OrderInfo(BaseModel):
    """Information about an order"""
    order_id: str = Field(description="Order ID")
    client_order_id: str = Field(description="Client order ID")
    account_name: str = Field(description="Account name")
    connector_name: str = Field(description="Connector name")
    trading_pair: str = Field(description="Trading pair")
    order_type: str = Field(description="Order type")
    trade_type: str = Field(description="Trade type (BUY/SELL)")
    amount: Decimal = Field(description="Order amount")
    price: Optional[Decimal] = Field(description="Order price")
    filled_amount: Decimal = Field(description="Filled amount")
    status: str = Field(description="Order status")
    creation_timestamp: datetime = Field(description="Order creation time")
    last_update_timestamp: datetime = Field(description="Last update time")


class ActiveOrdersResponse(BaseModel):
    """Response for active orders"""
    orders: Dict[str, OrderInfo] = Field(description="Dictionary of active orders")


class OrderSummary(BaseModel):
    """Summary statistics for orders"""
    total_orders: int = Field(description="Total number of orders")
    filled_orders: int = Field(description="Number of filled orders")
    cancelled_orders: int = Field(description="Number of cancelled orders")
    fill_rate: float = Field(description="Order fill rate percentage")
    total_volume_base: Decimal = Field(description="Total volume in base currency")
    total_volume_quote: Decimal = Field(description="Total volume in quote currency")
    avg_fill_time: Optional[float] = Field(description="Average fill time in seconds")


class TradeInfo(BaseModel):
    """Information about a trade fill"""
    trade_id: str = Field(description="Trade ID")
    order_id: str = Field(description="Associated order ID")
    account_name: str = Field(description="Account name")
    connector_name: str = Field(description="Connector name")
    trading_pair: str = Field(description="Trading pair")
    trade_type: str = Field(description="Trade type (BUY/SELL)")
    amount: Decimal = Field(description="Trade amount")
    price: Decimal = Field(description="Trade price")
    fee: Decimal = Field(description="Trade fee")
    timestamp: datetime = Field(description="Trade timestamp")


class TradingRulesInfo(BaseModel):
    """Trading rules for a trading pair"""
    trading_pair: str = Field(description="Trading pair")
    min_order_size: Decimal = Field(description="Minimum order size")
    max_order_size: Optional[Decimal] = Field(description="Maximum order size")
    min_price_increment: Decimal = Field(description="Minimum price increment")
    min_base_amount_increment: Decimal = Field(description="Minimum base amount increment")
    min_quote_amount_increment: Decimal = Field(description="Minimum quote amount increment")


class OrderTypesResponse(BaseModel):
    """Response for supported order types"""
    connector: str = Field(description="Connector name")
    supported_order_types: List[str] = Field(description="List of supported order types")