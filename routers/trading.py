from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from hummingbot.core.data_type.common import PositionMode, TradeType, OrderType, PositionAction
from starlette import status

from services.accounts_service import AccountsService
from deps import get_accounts_service, get_market_data_feed_manager
from models import TradeRequest, TradeResponse
from models.accounts import PositionModeRequest, LeverageRequest

router = APIRouter(tags=["Trading"], prefix="/trading")


# Trade Execution
@router.post("/orders", response_model=TradeResponse, status_code=status.HTTP_201_CREATED)
async def place_trade(trade_request: TradeRequest, 
                     accounts_service: AccountsService = Depends(get_accounts_service),
                     market_data_manager = Depends(get_market_data_feed_manager)):
    """
    Place a buy or sell order using a specific account and connector.
    
    Args:
        trade_request: Trading request with account, connector, trading pair, type, amount, etc.
        accounts_service: Injected accounts service
        market_data_manager: Market data manager for price fetching
        
    Returns:
        TradeResponse with order ID and trading details
        
    Raises:
        HTTPException: 400 for invalid parameters, 404 for account/connector not found, 500 for trade execution errors
    """
    try:
        # Convert string names to enum instances
        trade_type_enum = TradeType[trade_request.trade_type]
        order_type_enum = OrderType[trade_request.order_type]
        position_action_enum = PositionAction[trade_request.position_action]
        
        order_id = await accounts_service.place_trade(
            account_name=trade_request.account_name,
            connector_name=trade_request.connector_name,
            trading_pair=trade_request.trading_pair,
            trade_type=trade_type_enum,
            amount=trade_request.amount,
            order_type=order_type_enum,
            price=trade_request.price,
            position_action=position_action_enum,
            market_data_manager=market_data_manager
        )
        
        return TradeResponse(
            order_id=order_id,
            account_name=trade_request.account_name,
            connector_name=trade_request.connector_name,
            trading_pair=trade_request.trading_pair,
            trade_type=trade_request.trade_type,
            amount=trade_request.amount,
            order_type=trade_request.order_type,
            price=trade_request.price,
            status="submitted"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error placing trade: {str(e)}")


@router.post("/{account_name}/{connector_name}/orders/{client_order_id}/cancel")
async def cancel_order(account_name: str, connector_name: str, client_order_id: str,
                       trading_pair: str = Query(..., description="Trading pair for the order to cancel"),
                       accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Cancel a specific order by its client order ID.

    Args:
        account_name: Name of the account
        connector_name: Name of the connector
        client_order_id: Client order ID to cancel
        trading_pair: Trading pair for the order
        accounts_service: Injected accounts service

    Returns:
        Success message with cancelled order ID

    Raises:
        HTTPException: 404 if account/connector not found, 500 for cancellation errors
    """
    try:
        cancelled_order_id = await accounts_service.cancel_order(
            account_name=account_name,
            connector_name=connector_name,
            trading_pair=trading_pair,
            client_order_id=client_order_id
        )
        return {"message": f"Order {cancelled_order_id} cancelled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling order: {str(e)}")




@router.get("/positions", response_model=List[Dict])
async def get_positions(
        account_names: Optional[List[str]] = Query(default=None, description="Filter by account names"),
        connector_names: Optional[List[str]] = Query(default=None, description="Filter by connector names"),
        accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get current positions across all or filtered perpetual connectors.

    This endpoint fetches real-time position data directly from the connectors,
    including unrealized PnL, leverage, funding fees, and margin information.

    Args:
        account_names: Optional list of account names to filter by
        connector_names: Optional list of connector names to filter by

    Returns:
        List of current position dictionaries with real-time data from filtered accounts/connectors

    Raises:
        HTTPException: 500 if there's an error fetching positions
    """
    try:
        all_positions = []
        all_connectors = accounts_service.connector_manager.get_all_connectors()

        # Filter accounts
        accounts_to_check = account_names if account_names else list(all_connectors.keys())

        for account_name in accounts_to_check:
            if account_name in all_connectors:
                # Filter connectors
                connectors_to_check = connector_names if connector_names else list(all_connectors[account_name].keys())

                for connector_name in connectors_to_check:
                    # Only fetch positions from perpetual connectors
                    if connector_name in all_connectors[account_name] and "_perpetual" in connector_name:
                        try:
                            positions = await accounts_service.get_account_positions(account_name, connector_name)
                            all_positions.extend(positions)
                        except Exception as e:
                            # Log error but continue with other connectors
                            import logging
                            logging.warning(f"Failed to get positions for {account_name}/{connector_name}: {e}")

        return all_positions

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions: {str(e)}")



# Order Management
@router.get("/{account_name}/{connector_name}/orders/active", response_model=Dict[str, Dict])
async def get_connector_active_orders(account_name: str, connector_name: str, 
                                    accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get all active orders for a specific account and connector.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the connector
        accounts_service: Injected accounts service
        
    Returns:
        Dictionary mapping order IDs to order details
        
    Raises:
        HTTPException: 404 if account or connector not found
    """
    try:
        return await accounts_service.get_active_orders(account_name, connector_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving orders: {str(e)}")


# Global Order History
@router.get("/orders", response_model=List[Dict])
async def get_all_orders(
    market: Optional[str] = Query(None, description="Filter by market/connector"),
    symbol: Optional[str] = Query(None, description="Filter by trading pair"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    start_time: Optional[int] = Query(None, description="Start timestamp in milliseconds"),
    end_time: Optional[int] = Query(None, description="End timestamp in milliseconds"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of orders to return"),
    offset: int = Query(0, ge=0, description="Number of orders to skip"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get order history across all accounts.
    
    Args:
        market: Optional filter by market/connector
        symbol: Optional filter by trading pair
        status: Optional filter by order status
        start_time: Optional start timestamp
        end_time: Optional end timestamp
        limit: Maximum number of orders to return
        offset: Number of orders to skip
        
    Returns:
        List of orders across all accounts
    """
    return await accounts_service.get_orders(
        account_name=None,  # Query all accounts
        market=market,
        symbol=symbol,
        status=status,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )


@router.get("/orders/active", response_model=List[Dict])
async def get_all_active_orders(
    market: Optional[str] = Query(None, description="Filter by market/connector"),
    symbol: Optional[str] = Query(None, description="Filter by trading pair"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get active orders across all accounts.
    
    Args:
        market: Optional filter by market/connector
        symbol: Optional filter by trading pair
        accounts_service: Injected accounts service
        
    Returns:
        List of active orders across all accounts
    """
    return await accounts_service.get_active_orders_history(
        account_name=None,  # Query all accounts
        market=market,
        symbol=symbol,
    )


@router.get("/orders/summary", response_model=Dict)
async def get_all_orders_summary(
    start_time: Optional[int] = Query(None, description="Start timestamp in milliseconds"),
    end_time: Optional[int] = Query(None, description="End timestamp in milliseconds"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get order summary statistics across all accounts.
    
    Args:
        start_time: Optional start timestamp
        end_time: Optional end timestamp
        accounts_service: Injected accounts service
        
    Returns:
        Order summary statistics including fill rate, volumes, etc.
    """
    return await accounts_service.get_orders_summary(
        account_name=None,  # Query all accounts
        start_time=start_time,
        end_time=end_time,
    )


# Account-Specific Order History
@router.get("/{account_name}/orders", response_model=List[Dict])
async def get_account_orders(
    account_name: str,
    connector_name: Optional[str] = Query(None, description="Filter by connector"),
    trading_pair: Optional[str] = Query(None, description="Filter by trading pair"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    start_time: Optional[int] = Query(None, description="Start timestamp in milliseconds"),
    end_time: Optional[int] = Query(None, description="End timestamp in milliseconds"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of orders to return"),
    offset: int = Query(0, ge=0, description="Number of orders to skip"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get order history for a specific account.
    
    Args:
        account_name: Name of the account
        connector_name: Optional filter by connector
        trading_pair: Optional filter by trading pair
        status: Optional filter by order status
        start_time: Optional start timestamp
        end_time: Optional end timestamp
        limit: Maximum number of orders to return
        offset: Number of orders to skip
        accounts_service: Injected accounts service
        
    Returns:
        List of orders for the account
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    orders = await accounts_service.get_orders(
        account_name=account_name,
        market=connector_name,
        symbol=trading_pair,
        status=status,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    
    return orders


@router.get("/{account_name}/orders/active", response_model=List[Dict])
async def get_account_active_orders(
    account_name: str,
    connector_name: Optional[str] = Query(None, description="Filter by connector"),
    trading_pair: Optional[str] = Query(None, description="Filter by trading pair"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get active orders for a specific account.
    
    Args:
        account_name: Name of the account
        connector_name: Optional filter by connector
        trading_pair: Optional filter by trading pair
        accounts_service: Injected accounts service
        
    Returns:
        List of active orders
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    orders = await accounts_service.get_active_orders_history(
        account_name=account_name,
        market=connector_name,
        symbol=trading_pair,
    )
    
    return orders

# Trade History
@router.get("/trades", response_model=List[Dict])
async def get_all_trades(
    market: Optional[str] = Query(None, description="Filter by market/connector"),
    symbol: Optional[str] = Query(None, description="Filter by trading pair"),
    trade_type: Optional[str] = Query(None, description="Filter by trade type (BUY/SELL)"),
    start_time: Optional[int] = Query(None, description="Start timestamp in milliseconds"),
    end_time: Optional[int] = Query(None, description="End timestamp in milliseconds"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of trades to return"),
    offset: int = Query(0, ge=0, description="Number of trades to skip"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get trade history across all accounts.
    
    Args:
        market: Optional filter by market/connector
        symbol: Optional filter by trading pair
        trade_type: Optional filter by trade type
        start_time: Optional start timestamp
        end_time: Optional end timestamp
        limit: Maximum number of trades to return
        offset: Number of trades to skip
        accounts_service: Injected accounts service
        
    Returns:
        List of trades across all accounts
    """
    return await accounts_service.get_trades(
        account_name=None,  # Query all accounts
        market=market,
        symbol=symbol,
        trade_type=trade_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )


@router.get("/{account_name}/trades", response_model=List[Dict])
async def get_account_trades(
    account_name: str,
    connector_name: Optional[str] = Query(None, description="Filter by connector"),
    trading_pair: Optional[str] = Query(None, description="Filter by trading pair"),
    trade_type: Optional[str] = Query(None, description="Filter by trade type (BUY/SELL)"),
    start_time: Optional[int] = Query(None, description="Start timestamp in milliseconds"),
    end_time: Optional[int] = Query(None, description="End timestamp in milliseconds"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of trades to return"),
    offset: int = Query(0, ge=0, description="Number of trades to skip"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get trade history for a specific account.
    
    Args:
        account_name: Name of the account
        connector_name: Optional filter by connector
        trading_pair: Optional filter by trading pair
        trade_type: Optional filter by trade type
        start_time: Optional start timestamp
        end_time: Optional end timestamp
        limit: Maximum number of trades to return
        offset: Number of trades to skip
        accounts_service: Injected accounts service
        
    Returns:
        List of trades for the account
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    trades = await accounts_service.get_trades(
        account_name=account_name,
        market=connector_name,
        symbol=trading_pair,
        trade_type=trade_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    
    return trades


@router.post("/{account_name}/{connector_name}/position-mode")
async def set_position_mode(
    account_name: str, 
    connector_name: str, 
    request: PositionModeRequest,
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Set position mode for a perpetual connector.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the perpetual connector
        position_mode: Position mode to set (HEDGE or ONEWAY)
        
    Returns:
        Success message with status
        
    Raises:
        HTTPException: 400 if not a perpetual connector or invalid position mode
    """
    try:
        # Convert string to PositionMode enum
        mode = PositionMode[request.position_mode.upper()]
        result = await accounts_service.set_position_mode(account_name, connector_name, mode)
        return result
    except KeyError:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid position mode '{request.position_mode}'. Must be 'HEDGE' or 'ONEWAY'"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{account_name}/{connector_name}/position-mode")
async def get_position_mode(
    account_name: str, 
    connector_name: str, 
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get current position mode for a perpetual connector.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the perpetual connector
        
    Returns:
        Dictionary with current position mode, connector name, and account name
        
    Raises:
        HTTPException: 400 if not a perpetual connector
    """
    try:
        result = await accounts_service.get_position_mode(account_name, connector_name)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{account_name}/{connector_name}/leverage")
async def set_leverage(
    account_name: str, 
    connector_name: str, 
    request: LeverageRequest,
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Set leverage for a specific trading pair on a perpetual connector.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the perpetual connector
        request: Leverage request with trading pair and leverage value
        accounts_service: Injected accounts service
        
    Returns:
        Dictionary with success status and message
        
    Raises:
        HTTPException: 400 for invalid parameters or non-perpetual connector, 404 for account/connector not found, 500 for execution errors
    """
    try:
        result = await accounts_service.set_leverage(
            account_name=account_name,
            connector_name=connector_name,
            trading_pair=request.trading_pair,
            leverage=request.leverage
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error setting leverage: {str(e)}")

@router.get("/funding-payments", response_model=List[Dict])
async def get_funding_payments(
        account_names: Optional[List[str]] = Query(default=None, description="Filter by account names"),
        connector_names: Optional[List[str]] = Query(default=None, description="Filter by connector names"),
        trading_pair: Optional[str] = Query(default=None, description="Filter by trading pair"),
        limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records"),
        accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get funding payment history across all or filtered perpetual connectors.

    This endpoint retrieves historical funding payment records including
    funding rates, payment amounts, and position data at time of payment.

    Args:
        account_names: Optional list of account names to filter by
        connector_names: Optional list of connector names to filter by
        trading_pair: Optional trading pair filter
        limit: Maximum number of records to return

    Returns:
        List of funding payment records with rates, amounts, and position data

    Raises:
        HTTPException: 500 if there's an error fetching funding payments
    """
    try:
        all_funding_payments = []
        all_connectors = accounts_service.connector_manager.get_all_connectors()

        # Filter accounts
        accounts_to_check = account_names if account_names else list(all_connectors.keys())

        for account_name in accounts_to_check:
            if account_name in all_connectors:
                # Filter connectors
                connectors_to_check = connector_names if connector_names else list(all_connectors[account_name].keys())

                for connector_name in connectors_to_check:
                    # Only fetch funding payments from perpetual connectors
                    if connector_name in all_connectors[account_name] and "_perpetual" in connector_name:
                        try:
                            payments = await accounts_service.get_funding_payments(
                                account_name=account_name,
                                connector_name=connector_name,
                                trading_pair=trading_pair,
                                limit=limit
                            )
                            all_funding_payments.extend(payments)
                        except Exception as e:
                            # Log error but continue with other connectors
                            import logging
                            logging.warning(f"Failed to get funding payments for {account_name}/{connector_name}: {e}")

        # Sort by timestamp (most recent first)
        all_funding_payments.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Apply limit to the combined results
        return all_funding_payments[:limit]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching funding payments: {str(e)}")