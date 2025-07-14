from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Trade, Order


class TradeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_trade(self, trade_data: Dict) -> Trade:
        """Create a new trade record."""
        trade = Trade(**trade_data)
        self.session.add(trade)
        await self.session.flush()  # Get the ID
        return trade

    async def get_trades(self, account_name: Optional[str] = None,
                        connector_name: Optional[str] = None,
                        trading_pair: Optional[str] = None,
                        trade_type: Optional[str] = None,
                        start_time: Optional[int] = None,
                        end_time: Optional[int] = None,
                        limit: int = 100, offset: int = 0) -> List[Trade]:
        """Get trades with filtering and pagination."""
        # Join trades with orders to get account information
        query = select(Trade).join(Order, Trade.order_id == Order.id)
        
        # Apply filters
        if account_name:
            query = query.where(Order.account_name == account_name)
        if connector_name:
            query = query.where(Order.connector_name == connector_name)
        if trading_pair:
            query = query.where(Trade.trading_pair == trading_pair)
        if trade_type:
            query = query.where(Trade.trade_type == trade_type)
        if start_time:
            start_dt = datetime.fromtimestamp(start_time / 1000)
            query = query.where(Trade.timestamp >= start_dt)
        if end_time:
            end_dt = datetime.fromtimestamp(end_time / 1000)
            query = query.where(Trade.timestamp <= end_dt)
        
        # Apply ordering and pagination
        query = query.order_by(Trade.timestamp.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_trades_with_orders(self, account_name: Optional[str] = None,
                                   connector_name: Optional[str] = None,
                                   trading_pair: Optional[str] = None,
                                   trade_type: Optional[str] = None,
                                   start_time: Optional[int] = None,
                                   end_time: Optional[int] = None,
                                   limit: int = 100, offset: int = 0) -> List[tuple]:
        """Get trades with their associated order information."""
        # Join trades with orders to get complete information
        query = select(Trade, Order).join(Order, Trade.order_id == Order.id)
        
        # Apply filters
        if account_name:
            query = query.where(Order.account_name == account_name)
        if connector_name:
            query = query.where(Order.connector_name == connector_name)
        if trading_pair:
            query = query.where(Trade.trading_pair == trading_pair)
        if trade_type:
            query = query.where(Trade.trade_type == trade_type)
        if start_time:
            start_dt = datetime.fromtimestamp(start_time / 1000)
            query = query.where(Trade.timestamp >= start_dt)
        if end_time:
            end_dt = datetime.fromtimestamp(end_time / 1000)
            query = query.where(Trade.timestamp <= end_dt)
        
        # Apply ordering and pagination
        query = query.order_by(Trade.timestamp.desc())
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return result.all()  # Returns tuples of (Trade, Order)

    def to_dict(self, trade: Trade, order: Optional[Order] = None) -> Dict:
        """Convert Trade model to dictionary format."""
        return {
            "trade_id": trade.trade_id,
            "order_id": order.client_order_id if order else None,
            "account_name": order.account_name if order else None,
            "connector_name": order.connector_name if order else None,
            "trading_pair": trade.trading_pair,
            "trade_type": trade.trade_type,
            "amount": float(trade.amount),
            "price": float(trade.price),
            "fee_paid": float(trade.fee_paid),
            "fee_currency": trade.fee_currency,
            "timestamp": trade.timestamp.isoformat(),
        }