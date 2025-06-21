from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal

from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import PositionSnapshot


class PositionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_position_snapshot(self, position_data: Dict) -> PositionSnapshot:
        """Create a new position snapshot record."""
        position = PositionSnapshot(**position_data)
        self.session.add(position)
        await self.session.flush()  # Get the ID
        return position

    async def get_latest_positions(self, account_name: str, connector_name: str) -> List[PositionSnapshot]:
        """Get the latest position snapshots for an account-connector pair."""
        # Get the latest snapshot for each trading pair
        subquery = (
            select(PositionSnapshot.trading_pair, 
                   func.max(PositionSnapshot.timestamp).label('max_timestamp'))
            .where(
                PositionSnapshot.account_name == account_name,
                PositionSnapshot.connector_name == connector_name,
                PositionSnapshot.exchange_size != 0  # Only active positions
            )
            .group_by(PositionSnapshot.trading_pair)
            .subquery()
        )
        
        query = (
            select(PositionSnapshot)
            .join(subquery, 
                  (PositionSnapshot.trading_pair == subquery.c.trading_pair) &
                  (PositionSnapshot.timestamp == subquery.c.max_timestamp))
            .where(
                PositionSnapshot.account_name == account_name,
                PositionSnapshot.connector_name == connector_name
            )
        )
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_position_history(self, account_name: str, connector_name: str, 
                                 trading_pair: str, limit: int = 100) -> List[PositionSnapshot]:
        """Get position history for a specific trading pair."""
        query = (
            select(PositionSnapshot)
            .where(
                PositionSnapshot.account_name == account_name,
                PositionSnapshot.connector_name == connector_name,
                PositionSnapshot.trading_pair == trading_pair
            )
            .order_by(PositionSnapshot.timestamp.desc())
            .limit(limit)
        )
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def update_position_reconciliation(self, position_id: int, 
                                           calculated_size: Decimal,
                                           calculated_entry_price: Decimal = None) -> Optional[PositionSnapshot]:
        """Update position with calculated values for reconciliation."""
        result = await self.session.execute(
            select(PositionSnapshot).where(PositionSnapshot.id == position_id)
        )
        position = result.scalar_one_or_none()
        
        if position:
            position.calculated_size = float(calculated_size)
            if calculated_entry_price:
                position.calculated_entry_price = float(calculated_entry_price)
            
            # Calculate difference and reconciliation status
            size_diff = abs(calculated_size - Decimal(str(position.exchange_size)))
            position.size_difference = float(size_diff)
            
            # Set reconciliation status (within 0.1% tolerance)
            tolerance = Decimal(str(position.exchange_size)) * Decimal('0.001')
            if size_diff <= tolerance:
                position.is_reconciled = "RECONCILED"
            else:
                position.is_reconciled = "MISMATCH"
                
            await self.session.flush()
        
        return position

    async def get_reconciliation_mismatches(self, account_name: str = None) -> List[PositionSnapshot]:
        """Get positions with reconciliation mismatches."""
        query = select(PositionSnapshot).where(PositionSnapshot.is_reconciled == "MISMATCH")
        
        if account_name:
            query = query.where(PositionSnapshot.account_name == account_name)
            
        query = query.order_by(PositionSnapshot.timestamp.desc())
        
        result = await self.session.execute(query)
        return result.scalars().all()

    def to_dict(self, position: PositionSnapshot) -> Dict:
        """Convert PositionSnapshot model to dictionary format."""
        return {
            "id": position.id,
            "account_name": position.account_name,
            "connector_name": position.connector_name,
            "trading_pair": position.trading_pair,
            "timestamp": position.timestamp.isoformat(),
            "side": position.side,
            "exchange_size": float(position.exchange_size),
            "entry_price": float(position.entry_price) if position.entry_price else None,
            "mark_price": float(position.mark_price) if position.mark_price else None,
            "unrealized_pnl": float(position.unrealized_pnl) if position.unrealized_pnl else None,
            "percentage_pnl": float(position.percentage_pnl) if position.percentage_pnl else None,
            "leverage": float(position.leverage) if position.leverage else None,
            "initial_margin": float(position.initial_margin) if position.initial_margin else None,
            "maintenance_margin": float(position.maintenance_margin) if position.maintenance_margin else None,
            "cumulative_funding_fees": float(position.cumulative_funding_fees),
            "fee_currency": position.fee_currency,
            "calculated_size": float(position.calculated_size) if position.calculated_size else None,
            "calculated_entry_price": float(position.calculated_entry_price) if position.calculated_entry_price else None,
            "size_difference": float(position.size_difference) if position.size_difference else None,
            "exchange_position_id": position.exchange_position_id,
            "is_reconciled": position.is_reconciled,
        }