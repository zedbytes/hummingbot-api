from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from hummingbot.client.settings import AllConnectorSettings
from starlette import status

from services.accounts_service import AccountsService
from utils.file_system import FileSystemUtil
from deps import get_accounts_service, get_market_data_feed_manager
from models import PaginatedResponse
from models.bot import TradeRequest, TradeResponse

router = APIRouter(tags=["Accounts"], prefix="/accounts")
file_system = FileSystemUtil(base_path="bots/credentials")


@router.get("/state", response_model=Dict[str, Dict[str, List[Dict]]])
async def get_all_accounts_state(accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get the current state of all accounts.
    
    Returns:
        Dict containing account states with connector balances and token information
    """
    return accounts_service.get_accounts_state()


@router.get("/history", response_model=PaginatedResponse)
async def get_account_state_history(
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get the historical state of all accounts with pagination.
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


@router.get("/connectors", response_model=List[str])
async def available_connectors():
    """
    Get a list of all available connectors.
    
    Returns:
        List of connector names supported by the system
    """
    return list(AllConnectorSettings.get_connector_settings().keys())


@router.get("/connector-config-map/{connector_name}", response_model=List[str])
async def get_connector_config_map(connector_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get configuration fields required for a specific connector.
    
    Args:
        connector_name: Name of the connector to get config map for
        
    Returns:
        List of configuration field names required for the connector
    """
    return accounts_service.get_connector_config_map(connector_name)




@router.get("/", response_model=List[str])
async def list_accounts(accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get a list of all account names in the system.
    
    Returns:
        List of account names
    """
    return accounts_service.list_accounts()




@router.post("/add-account", status_code=status.HTTP_201_CREATED)
async def add_account(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Create a new account with default configuration files.
    
    Args:
        account_name: Name of the new account to create
        
    Returns:
        Success message when account is created
        
    Raises:
        HTTPException: 400 if account already exists
    """
    try:
        accounts_service.add_account(account_name)
        return {"message": "Account added successfully."}
    except FileExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/delete-account")
async def delete_account(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Delete an account and all its associated credentials.
    
    Args:
        account_name: Name of the account to delete
        
    Returns:
        Success message when account is deleted
        
    Raises:
        HTTPException: 400 if trying to delete master account, 404 if account not found
    """
    try:
        if account_name == "master_account":
            raise HTTPException(status_code=400, detail="Cannot delete master account.")
        await accounts_service.delete_account(account_name)
        return {"message": "Account deleted successfully."}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/delete-credential/{account_name}/{connector_name}")
async def delete_credential(account_name: str, connector_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Delete a specific connector credential for an account.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the connector to delete credentials for
        
    Returns:
        Success message when credential is deleted
        
    Raises:
        HTTPException: 404 if credential not found
    """
    try:
        await accounts_service.delete_credentials(account_name, connector_name)
        return {"message": "Credential deleted successfully."}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/add-credential/{account_name}/{connector_name}", status_code=status.HTTP_201_CREATED)
async def add_credential(account_name: str, connector_name: str, credentials: Dict, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Add or update connector credentials (API keys) for a specific account and connector.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the connector
        credentials: Dictionary containing the connector credentials
        
    Returns:
        Success message when credentials are added
        
    Raises:
        HTTPException: 400 if there's an error adding the credentials
    """
    try:
        await accounts_service.add_credentials(account_name, connector_name, credentials)
        return {"message": "Connector credentials added successfully."}
    except Exception as e:
        await accounts_service.delete_credentials(account_name, connector_name)
        raise HTTPException(status_code=400, detail=str(e))


# Account-specific routes
@router.get("/{account_name}/state", response_model=Dict[str, List[Dict]])
async def get_account_state(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get current state of a specific account.
    
    Args:
        account_name: Name of the account to get state for
        
    Returns:
        Dictionary mapping connector names to lists of token information
        
    Raises:
        HTTPException: 404 if account not found
    """
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    return state


@router.get("/{account_name}/state/history", response_model=PaginatedResponse)
async def get_account_history(
    account_name: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get historical state of a specific account with pagination.
    
    Args:
        account_name: Name of the account to get history for
        limit: Number of items per page (1-1000)
        cursor: Cursor for pagination (ISO timestamp)
        start_time: Start time for filtering results
        end_time: End time for filtering results
        
    Returns:
        Paginated response with historical account state data
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

# Trading endpoints
@router.post("/trade", response_model=TradeResponse, status_code=status.HTTP_201_CREATED)
async def place_trade(trade_request: TradeRequest, 
                     accounts_service: AccountsService = Depends(get_accounts_service),
                     market_data_manager = Depends(get_market_data_feed_manager)):
    """
    Place a buy or sell order using a specific account and connector.
    
    Args:
        trade_request: Trading request with account, connector, trading pair, type, amount, etc.
        accounts_service: Injected accounts service
        
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


@router.get("/{account_name}/connectors/{connector_name}/orders", response_model=Dict[str, Dict])
async def get_active_orders(account_name: str, connector_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
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
        return accounts_service.get_active_orders(account_name, connector_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving orders: {str(e)}")


@router.post("/{account_name}/connectors/{connector_name}/orders/{client_order_id}/cancel")
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


@router.get("/{account_name}/connectors/{connector_name}/trading-rules/{trading_pair}")
async def get_trading_rules(account_name: str, connector_name: str, trading_pair: str, 
                           accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get trading rules for a specific trading pair on a connector.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the connector
        trading_pair: Trading pair to get rules for
        accounts_service: Injected accounts service
        
    Returns:
        Trading rules including minimum order size, price increment, etc.
        
    Raises:
        HTTPException: 404 if account/connector/trading pair not found
    """
    try:
        connector = accounts_service.get_connector_instance(account_name, connector_name)
        
        if trading_pair not in connector.trading_rules:
            raise HTTPException(status_code=404, detail=f"Trading pair '{trading_pair}' not found")
        
        trading_rule = connector.trading_rules[trading_pair]
        return {
            "trading_pair": trading_pair,
            "min_order_size": float(trading_rule.min_order_size),
            "max_order_size": float(trading_rule.max_order_size) if trading_rule.max_order_size else None,
            "min_price_increment": float(trading_rule.min_price_increment),
            "min_base_amount_increment": float(trading_rule.min_base_amount_increment),
            "min_notional_size": float(trading_rule.min_notional_size),
            "max_price_significant_digits": trading_rule.max_price_significant_digits,
            "max_quantity_significant_digits": trading_rule.max_quantity_significant_digits,
            "supports_limit_orders": trading_rule.supports_limit_orders,
            "supports_market_orders": trading_rule.supports_market_orders,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving trading rules: {str(e)}")


@router.get("/{account_name}/connectors/{connector_name}/supported-order-types")
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
        connector = accounts_service.get_connector_instance(account_name, connector_name)
        return [order_type.name for order_type in connector.supported_order_types()]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving order types: {str(e)}")


# Global order/trade endpoints for all accounts
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
        
    Returns:
        Order summary statistics including fill rate, volumes, etc.
    """
    return await accounts_service.get_orders_summary(
        account_name=None,  # Query all accounts
        start_time=start_time,
        end_time=end_time,
    )


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


# Order history endpoints integrated with accounts
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
        
    Returns:
        List of orders for the account
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    # Get orders from accounts service (will be implemented)
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
        
    Returns:
        List of active orders
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    # Get active orders from accounts service (will be implemented)
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
        
    Returns:
        Order summary statistics including fill rate, volumes, etc.
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    # Get summary from accounts service (will be implemented)
    summary = await accounts_service.get_orders_summary(
        account_name=account_name,
        start_time=start_time,
        end_time=end_time,
    )
    
    return summary


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
        
    Returns:
        List of trades for the account
        
    Raises:
        HTTPException: 404 if account not found
    """
    # Verify account exists
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    # Get trades from accounts service (will be implemented)
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
