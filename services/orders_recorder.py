import asyncio
import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime

from hummingbot.core.event.event_listener import EventListener
from hummingbot.core.event.events import (
    OrderType,
    TradeType,
    BuyOrderCreatedEvent,
    SellOrderCreatedEvent,
    OrderFilledEvent,
    OrderCancelledEvent,
    MarketEvent,
    BuyOrderCompletedEvent,
    SellOrderCompletedEvent
)
from hummingbot.connector.connector_base import ConnectorBase

from database import AsyncDatabaseManager
from database.models import Order, Trade


class OrdersRecorder(EventListener):
    """
    Custom orders recorder that mimics Hummingbot's MarketsRecorder functionality
    but uses our AsyncDatabaseManager for storage.
    """
    
    def __init__(self, db_manager: AsyncDatabaseManager, account_name: str, connector_name: str):
        super().__init__()
        self.db_manager = db_manager
        self.account_name = account_name
        self.connector_name = connector_name
        self._connector: Optional[ConnectorBase] = None
        self._session = None
        
    def start(self, connector: ConnectorBase):
        """Start recording orders for the given connector"""
        self._connector = connector
        
        # Subscribe to order events
        connector.add_listener(MarketEvent.BuyOrderCreated, self)
        connector.add_listener(MarketEvent.SellOrderCreated, self)
        connector.add_listener(MarketEvent.OrderFilled, self)
        connector.add_listener(MarketEvent.OrderCancelled, self)
        connector.add_listener(MarketEvent.OrderFailure, self)
        connector.add_listener(MarketEvent.BuyOrderCompleted, self)
        connector.add_listener(MarketEvent.SellOrderCompleted, self)
        
        logging.info(f"OrdersRecorder started for {self.account_name}/{self.connector_name}")
    
    async def stop(self):
        """Stop recording orders"""
        if self._connector:
            # Remove all event listeners
            self._connector.remove_listener(MarketEvent.BuyOrderCreated, self)
            self._connector.remove_listener(MarketEvent.SellOrderCreated, self)
            self._connector.remove_listener(MarketEvent.OrderFilled, self)
            self._connector.remove_listener(MarketEvent.OrderCancelled, self)
            self._connector.remove_listener(MarketEvent.OrderFailure, self)
            self._connector.remove_listener(MarketEvent.BuyOrderCompleted, self)
            self._connector.remove_listener(MarketEvent.SellOrderCompleted, self)
            
        logging.info(f"OrdersRecorder stopped for {self.account_name}/{self.connector_name}")
    
    async def __call__(self, event_tag: int, market: ConnectorBase, event: Any):
        """Handle incoming events"""
        try:
            if event_tag == MarketEvent.BuyOrderCreated.value:
                await self._handle_order_created(event, TradeType.BUY)
            elif event_tag == MarketEvent.SellOrderCreated.value:
                await self._handle_order_created(event, TradeType.SELL)
            elif event_tag == MarketEvent.OrderFilled.value:
                await self._handle_order_filled(event)
            elif event_tag == MarketEvent.OrderCancelled.value:
                await self._handle_order_cancelled(event)
            elif event_tag == MarketEvent.OrderFailure.value:
                await self._handle_order_failed(event)
            elif event_tag == MarketEvent.BuyOrderCompleted.value:
                await self._handle_order_completed(event)
            elif event_tag == MarketEvent.SellOrderCompleted.value:
                await self._handle_order_completed(event)
            else:
                logging.error(f"Unknown event tag {event_tag} received, event {event}")
        except Exception as e:
            logging.error(f"Error handling event {event_tag}: {e}")
    
    async def _handle_order_created(self, event: Any, trade_type: TradeType):
        """Handle order creation events"""
        try:
            async with self.db_manager.get_session_context() as session:
                order = Order(
                    client_order_id=event.order_id,
                    account_name=self.account_name,
                    connector_name=self.connector_name,
                    trading_pair=event.trading_pair,
                    trade_type=trade_type.name,
                    order_type=event.order_type.name if hasattr(event, 'order_type') else 'UNKNOWN',
                    amount=float(event.amount),
                    price=float(event.price) if event.price else None,
                    status="SUBMITTED"
                )
                session.add(order)
                await session.commit()
                
            logging.debug(f"Recorded order created: {event.order_id}")
        except Exception as e:
            logging.error(f"Error recording order created: {e}")
    
    async def _handle_order_filled(self, event: OrderFilledEvent):
        """Handle order fill events"""
        try:
            async with self.db_manager.get_session_context() as session:
                # Update order with fill information
                order = await session.get(Order, {"client_order_id": event.order_id})
                if order:
                    order.filled_amount = float(event.amount)
                    order.average_fill_price = float(event.price)
                    order.status = "FILLED" if event.amount >= Decimal(str(order.amount)) else "PARTIALLY_FILLED"
                    order.fee_paid = float(event.trade_fee.fee) if event.trade_fee else None
                    order.fee_currency = event.trade_fee.fee_asset if event.trade_fee else None
                
                # Create trade record
                trade = Trade(
                    order_id=order.id if order else None,
                    trade_id=f"{event.order_id}_{event.timestamp}",
                    timestamp=datetime.fromtimestamp(event.timestamp),
                    trading_pair=event.trading_pair,
                    trade_type=event.trade_type.name,
                    amount=float(event.amount),
                    price=float(event.price),
                    fee_paid=float(event.trade_fee.fee) if event.trade_fee else 0,
                    fee_currency=event.trade_fee.fee_asset if event.trade_fee else None
                )
                session.add(trade)
                await session.commit()
                
            logging.debug(f"Recorded order fill: {event.order_id} - {event.amount} @ {event.price}")
        except Exception as e:
            logging.error(f"Error recording order fill: {e}")
    
    async def _handle_order_cancelled(self, event: Any):
        """Handle order cancellation events"""
        try:
            async with self.db_manager.get_session_context() as session:
                order = await session.get(Order, {"client_order_id": event.order_id})
                if order:
                    order.status = "CANCELLED"
                    await session.commit()
                    
            logging.debug(f"Recorded order cancelled: {event.order_id}")
        except Exception as e:
            logging.error(f"Error recording order cancellation: {e}")
    
    async def _handle_order_failed(self, event: Any):
        """Handle order failure events"""
        try:
            async with self.db_manager.get_session_context() as session:
                order = await session.get(Order, {"client_order_id": event.order_id})
                if order:
                    order.status = "FAILED"
                    order.error_message = getattr(event, 'error_message', None)
                    await session.commit()
                    
            logging.debug(f"Recorded order failed: {event.order_id}")
        except Exception as e:
            logging.error(f"Error recording order failure: {e}")
    
    async def _handle_order_completed(self, event: Any):
        """Handle order completion events"""
        try:
            async with self.db_manager.get_session_context() as session:
                order = await session.get(Order, {"client_order_id": event.order_id})
                if order:
                    order.status = "FILLED"
                    order.exchange_order_id = getattr(event, 'exchange_order_id', None)
                    await session.commit()
                    
            logging.debug(f"Recorded order completed: {event.order_id}")
        except Exception as e:
            logging.error(f"Error recording order completion: {e}")