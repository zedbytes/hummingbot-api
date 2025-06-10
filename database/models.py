from sqlalchemy import (
    TIMESTAMP,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
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