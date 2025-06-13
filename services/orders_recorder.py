import asyncio
import logging
from typing import Any, Optional, Union
from decimal import Decimal
from datetime import datetime

from hummingbot.core.event.event_forwarder import SourceInfoEventForwarder
from hummingbot.core.event.events import (
    OrderType,
    TradeType,
    BuyOrderCreatedEvent,
    SellOrderCreatedEvent,
    OrderFilledEvent,
    OrderCancelledEvent,
    MarketEvent,
    BuyOrderCompletedEvent,
    SellOrderCompletedEvent,
    MarketOrderFailureEvent
)
from hummingbot.connector.connector_base import ConnectorBase
from sqlalchemy import select

from database import AsyncDatabaseManager
from database.models import Order, Trade


class OrdersRecorder:
    """
    Custom orders recorder that mimics Hummingbot's MarketsRecorder functionality
    but uses our AsyncDatabaseManager for storage.
    """
    
    def __init__(self, db_manager: AsyncDatabaseManager, account_name: str, connector_name: str):
        self.db_manager = db_manager
        self.account_name = account_name
        self.connector_name = connector_name
        self._connector: Optional[ConnectorBase] = None
        
        # Create event forwarders similar to MarketsRecorder
        self._create_order_forwarder = SourceInfoEventForwarder(self._did_create_order)
        self._fill_order_forwarder = SourceInfoEventForwarder(self._did_fill_order)
        self._cancel_order_forwarder = SourceInfoEventForwarder(self._did_cancel_order)
        self._fail_order_forwarder = SourceInfoEventForwarder(self._did_fail_order)
        self._complete_order_forwarder = SourceInfoEventForwarder(self._did_complete_order)
        
        # Event pairs mapping events to forwarders
        self._event_pairs = [
            (MarketEvent.BuyOrderCreated, self._create_order_forwarder),
            (MarketEvent.SellOrderCreated, self._create_order_forwarder),
            (MarketEvent.OrderFilled, self._fill_order_forwarder),
            (MarketEvent.OrderCancelled, self._cancel_order_forwarder),
            (MarketEvent.OrderFailure, self._fail_order_forwarder),
            (MarketEvent.BuyOrderCompleted, self._complete_order_forwarder),
            (MarketEvent.SellOrderCompleted, self._complete_order_forwarder),
        ]
        
    def start(self, connector: ConnectorBase):
        """Start recording orders for the given connector"""
        self._connector = connector
        
        # Subscribe to order events using the same pattern as MarketsRecorder
        for event, forwarder in self._event_pairs:
            connector.add_listener(event, forwarder)
            logging.info(f"OrdersRecorder: Added listener for {event} with forwarder {forwarder}")
            
            # Debug: Check if listeners were actually added
            if hasattr(connector, '_event_listeners'):
                listeners = connector._event_listeners.get(event, [])
                logging.info(f"OrdersRecorder: Event {event} now has {len(listeners)} listeners")
                for i, listener in enumerate(listeners):
                    logging.info(f"OrdersRecorder: Listener {i}: {listener}")
        
        logging.info(f"OrdersRecorder started for {self.account_name}/{self.connector_name} with {len(self._event_pairs)} event listeners")
        
        # Debug: Print connector info
        logging.info(f"OrdersRecorder: Connector type: {type(connector)}")
        logging.info(f"OrdersRecorder: Connector name: {getattr(connector, 'name', 'unknown')}")
        logging.info(f"OrdersRecorder: Connector ready: {getattr(connector, 'ready', 'unknown')}")
        
        # Test if forwarders are callable
        for event, forwarder in self._event_pairs:
            if callable(forwarder):
                logging.info(f"OrdersRecorder: Forwarder for {event} is callable")
            else:
                logging.error(f"OrdersRecorder: Forwarder for {event} is NOT callable: {type(forwarder)}")
    
    async def stop(self):
        """Stop recording orders"""
        if self._connector:
            # Remove all event listeners
            for event, forwarder in self._event_pairs:
                self._connector.remove_listener(event, forwarder)
            
        logging.info(f"OrdersRecorder stopped for {self.account_name}/{self.connector_name}")
    
    def _did_create_order(self, event_tag: int, market: ConnectorBase, event: Union[BuyOrderCreatedEvent, SellOrderCreatedEvent]):
        """Handle order creation events - called by SourceInfoEventForwarder"""
        logging.info(f"OrdersRecorder: _did_create_order called for order {getattr(event, 'order_id', 'unknown')}")
        try:
            # Determine trade type from event
            trade_type = TradeType.BUY if isinstance(event, BuyOrderCreatedEvent) else TradeType.SELL
            logging.info(f"OrdersRecorder: Creating task to handle order created - {trade_type} order")
            asyncio.create_task(self._handle_order_created(event, trade_type))
        except Exception as e:
            logging.error(f"Error in _did_create_order: {e}")
    
    def _did_fill_order(self, event_tag: int, market: ConnectorBase, event: OrderFilledEvent):
        """Handle order fill events - called by SourceInfoEventForwarder"""
        try:
            asyncio.create_task(self._handle_order_filled(event))
        except Exception as e:
            logging.error(f"Error in _did_fill_order: {e}")
    
    def _did_cancel_order(self, event_tag: int, market: ConnectorBase, event: Any):
        """Handle order cancel events - called by SourceInfoEventForwarder"""
        try:
            asyncio.create_task(self._handle_order_cancelled(event))
        except Exception as e:
            logging.error(f"Error in _did_cancel_order: {e}")
    
    def _did_fail_order(self, event_tag: int, market: ConnectorBase, event: Any):
        """Handle order failure events - called by SourceInfoEventForwarder"""
        try:
            asyncio.create_task(self._handle_order_failed(event))
        except Exception as e:
            logging.error(f"Error in _did_fail_order: {e}")
    
    def _did_complete_order(self, event_tag: int, market: ConnectorBase, event: Any):
        """Handle order completion events - called by SourceInfoEventForwarder"""
        try:
            asyncio.create_task(self._handle_order_completed(event))
        except Exception as e:
            logging.error(f"Error in _did_complete_order: {e}")
    
    async def _handle_order_created(self, event: Union[BuyOrderCreatedEvent, SellOrderCreatedEvent], trade_type: TradeType):
        """Handle order creation events"""
        logging.info(f"OrdersRecorder: _handle_order_created started for order {event.order_id}")
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
                
            logging.info(f"OrdersRecorder: Successfully recorded order created: {event.order_id}")
        except Exception as e:
            logging.error(f"OrdersRecorder: Error recording order created: {e}")
    
    async def _handle_order_filled(self, event: OrderFilledEvent):
        """Handle order fill events"""
        try:
            async with self.db_manager.get_session_context() as session:
                # Update order with fill information
                result = await session.execute(
                    select(Order).where(Order.client_order_id == event.order_id)
                )
                order = result.scalar_one_or_none()
                if order:
                    order.filled_amount = float(event.amount)
                    order.average_fill_price = float(event.price)
                    order.status = "FILLED" if event.amount >= Decimal(str(order.amount)) else "PARTIALLY_FILLED"
                    
                    # Calculate fee properly using the same method as MarketsRecorder
                    if event.trade_fee:
                        try:
                            base_asset, quote_asset = event.trading_pair.split("-")
                            fee_in_quote = event.trade_fee.fee_amount_in_token(
                                trading_pair=event.trading_pair,
                                price=event.price,
                                order_amount=event.amount,
                                token=quote_asset,
                                exchange=self._connector
                            )
                            order.fee_paid = float(fee_in_quote)
                            order.fee_currency = quote_asset
                        except Exception as e:
                            logging.error(f"Error calculating fee in quote: {e}, will be stored as 0")
                            order.fee_paid = 0
                            order.fee_currency = None
                
                # Create trade record
                trade_fee_paid = 0
                trade_fee_currency = None
                
                if event.trade_fee:
                    try:
                        base_asset, quote_asset = event.trading_pair.split("-")
                        fee_in_quote = event.trade_fee.fee_amount_in_token(
                            trading_pair=event.trading_pair,
                            price=event.price,
                            order_amount=event.amount,
                            token=quote_asset,
                            exchange=self._connector
                        )
                        trade_fee_paid = float(fee_in_quote)
                        trade_fee_currency = quote_asset
                    except Exception as e:
                        logging.error(f"Error calculating trade fee: {e}")
                        trade_fee_paid = 0
                        trade_fee_currency = None
                
                trade = Trade(
                    order_id=order.id if order else None,
                    trade_id=f"{event.order_id}_{event.timestamp}",
                    timestamp=datetime.fromtimestamp(event.timestamp),
                    trading_pair=event.trading_pair,
                    trade_type=event.trade_type.name,
                    amount=float(event.amount),
                    price=float(event.price),
                    fee_paid=trade_fee_paid,
                    fee_currency=trade_fee_currency
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
                result = await session.execute(
                    select(Order).where(Order.client_order_id == event.order_id)
                )
                order = result.scalar_one_or_none()
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
                result = await session.execute(
                    select(Order).where(Order.client_order_id == event.order_id)
                )
                order = result.scalar_one_or_none()
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
                result = await session.execute(
                    select(Order).where(Order.client_order_id == event.order_id)
                )
                order = result.scalar_one_or_none()
                if order:
                    order.status = "FILLED"
                    order.exchange_order_id = getattr(event, 'exchange_order_id', None)
                    await session.commit()
                    
            logging.debug(f"Recorded order completed: {event.order_id}")
        except Exception as e:
            logging.error(f"Error recording order completion: {e}")