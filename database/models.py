from sqlalchemy import (
    TIMESTAMP,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class AccountState(Base):
    __tablename__ = "account_states"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)
    account_name = Column(String, nullable=False, index=True)
    connector_name = Column(String, nullable=False, index=True)
    
    token_states = relationship("TokenState", back_populates="account_state", cascade="all, delete-orphan")


class TokenState(Base):
    __tablename__ = "token_states"

    id = Column(Integer, primary_key=True, index=True)
    account_state_id = Column(Integer, ForeignKey("account_states.id"), nullable=False)
    token = Column(String, nullable=False, index=True)
    units = Column(Numeric(precision=30, scale=18), nullable=False)
    price = Column(Numeric(precision=30, scale=18), nullable=False)
    value = Column(Numeric(precision=30, scale=18), nullable=False)
    available_units = Column(Numeric(precision=30, scale=18), nullable=False)
    
    account_state = relationship("AccountState", back_populates="token_states")


class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    # Order identification
    client_order_id = Column(String, nullable=False, unique=True, index=True)
    exchange_order_id = Column(String, nullable=True, index=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Account and connector info
    account_name = Column(String, nullable=False, index=True)
    connector_name = Column(String, nullable=False, index=True)
    
    # Order details
    trading_pair = Column(String, nullable=False, index=True)
    trade_type = Column(String, nullable=False)  # BUY, SELL
    order_type = Column(String, nullable=False)  # LIMIT, MARKET, LIMIT_MAKER
    amount = Column(Numeric(precision=30, scale=18), nullable=False)
    price = Column(Numeric(precision=30, scale=18), nullable=True)  # Null for market orders
    
    # Order status and execution
    status = Column(String, nullable=False, default="SUBMITTED", index=True)  # SUBMITTED, OPEN, FILLED, CANCELLED, FAILED
    filled_amount = Column(Numeric(precision=30, scale=18), nullable=False, default=0)
    average_fill_price = Column(Numeric(precision=30, scale=18), nullable=True)
    
    # Fee information
    fee_paid = Column(Numeric(precision=30, scale=18), nullable=True)
    fee_currency = Column(String, nullable=True)
    
    # Additional metadata
    error_message = Column(Text, nullable=True)
    
    # Relationships for future enhancements
    trades = relationship("Trade", back_populates="order", cascade="all, delete-orphan")


class Trade(Base):
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    
    # Trade identification
    trade_id = Column(String, nullable=False, unique=True, index=True)
    
    # Timestamps
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    
    # Trade details
    trading_pair = Column(String, nullable=False, index=True)
    trade_type = Column(String, nullable=False)  # BUY, SELL
    amount = Column(Numeric(precision=30, scale=18), nullable=False)
    price = Column(Numeric(precision=30, scale=18), nullable=False)
    
    # Fee information
    fee_paid = Column(Numeric(precision=30, scale=18), nullable=False, default=0)
    fee_currency = Column(String, nullable=True)
    
    # Relationship
    order = relationship("Order", back_populates="trades")


