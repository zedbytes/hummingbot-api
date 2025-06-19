from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from starlette import status

from services.accounts_service import AccountsService
from deps import get_accounts_service, get_market_data_feed_manager
from models import PaginatedResponse
from models.bot import TradeRequest, TradeResponse, LeverageRequest

router = APIRouter(tags=["Trading"], prefix="/trading")


# Portfolio & Account State Monitoring
@router.get("/portfolio/state", response_model=Dict[str, Dict[str, List[Dict]]])
async def get_portfolio_state(accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get the current state of all accounts portfolio.
    
    Returns:
        Dict containing all account states with connector balances and token information
    """
    return accounts_service.get_accounts_state()


@router.get("/portfolio/history", response_model=PaginatedResponse)
async def get_portfolio_history(
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get the historical state of all accounts portfolio with pagination.
    """
    try:
        data, next_cursor, has_more = await accounts_service.load_account_state_history(
            limit=limit,
            cursor=cursor,
            start_time=start_time,
            end_time=end_time
        )
        
        return PaginatedResponse(
            data=data,
            pagination={
                "limit": limit,
                "has_more": has_more,
                "next_cursor": next_cursor,
                "current_cursor": cursor
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{account_name}/balance", response_model=Dict[str, List[Dict]])
async def get_account_balance(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get current balance state of a specific account.
    
    Args:
        account_name: Name of the account to get balance for
        
    Returns:
        Dictionary mapping connector names to lists of token information
        
    Raises:
        HTTPException: 404 if account not found
    """
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    return state


@router.get("/{account_name}/balance/history", response_model=PaginatedResponse)
async def get_account_balance_history(
    account_name: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get historical balance state of a specific account with pagination.
    
    Args:
        account_name: Name of the account to get history for
        limit: Number of items per page (1-1000)
        cursor: Cursor for pagination (ISO timestamp)
        start_time: Start time for filtering results
        end_time: End time for filtering results
        
    Returns:
        Paginated response with historical account balance data
    """
    data, next_cursor, has_more = await accounts_service.get_account_state_history(
        account_name=account_name,
        limit=limit,
        cursor=cursor,
        start_time=start_time,
        end_time=end_time
    )
    
    return PaginatedResponse(
        data=data,
        pagination={
            "limit": limit,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "current_cursor": cursor,
            "filters": {
                "account_name": account_name,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None
            }
        }
    )


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
        order_id = await accounts_service.place_trade(
            account_name=trade_request.account_name,
            connector_name=trade_request.connector_name,
            trading_pair=trade_request.trading_pair,
            trade_type=trade_request.trade_type,
            amount=trade_request.amount,
            order_type=trade_request.order_type,
            price=trade_request.price,
            position_action=trade_request.position_action,
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


@router.post("/leverage", response_model=Dict[str, str], status_code=status.HTTP_200_OK)
async def set_leverage(leverage_request: LeverageRequest,
                      accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Set leverage for a specific trading pair on a perpetual connector.
    
    Args:
        leverage_request: Leverage request with account, connector, trading pair, and leverage value
        accounts_service: Injected accounts service
        
    Returns:
        Dictionary with success status and message
        
    Raises:
        HTTPException: 400 for invalid parameters or non-perpetual connector, 404 for account/connector not found, 500 for execution errors
    """
    try:
        result = await accounts_service.set_leverage(
            account_name=leverage_request.account_name,
            connector_name=leverage_request.connector_name,
            trading_pair=leverage_request.trading_pair,
            leverage=leverage_request.leverage
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error setting leverage: {str(e)}")


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


@router.get("/{account_name}/orders/summary", response_model=Dict)
async def get_account_orders_summary(
    account_name: str,
    start_time: Optional[int] = Query(None, description="Start timestamp in milliseconds"),
    end_time: Optional[int] = Query(None, description="End timestamp in milliseconds"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get order summary statistics for a specific account.
    
    Args:
        account_name: Name of the account
        start_time: Optional start timestamp
        end_time: Optional end timestamp
        accounts_service: Injected accounts service
        
    Returns:
        Order summary statistics including fill rate, volumes, etc.
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    summary = await accounts_service.get_orders_summary(
        account_name=account_name,
        start_time=start_time,
        end_time=end_time,
    )
    
    return summary


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


# Trading Rules & Configuration

@router.get("/{account_name}/{connector_name}/order-types")
async def get_supported_order_types(account_name: str, connector_name: str, 
                                   accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get order types supported by a specific connector.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the connector
        accounts_service: Injected accounts service
        
    Returns:
        List of supported order types (LIMIT, MARKET, LIMIT_MAKER)
        
    Raises:
        HTTPException: 404 if account or connector not found
    """
    try:
        connector = await accounts_service.get_connector_instance(account_name, connector_name)
        return [order_type.name for order_type in connector.supported_order_types()]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving order types: {str(e)}")