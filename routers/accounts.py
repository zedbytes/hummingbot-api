from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from hummingbot.client.settings import AllConnectorSettings
from starlette import status

from services.accounts_service import AccountsService
from deps import get_accounts_service
from models import PaginatedResponse

router = APIRouter(tags=["Accounts"], prefix="/accounts")


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


@router.get("/portfolio/state/{account_name}", response_model=Dict[str, List[Dict]])
async def get_account_portfolio_state(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get current portfolio state of a specific account.
    
    Args:
        account_name: Name of the account to get portfolio state for
        
    Returns:
        Dictionary mapping connector names to lists of token information
        
    Raises:
        HTTPException: 404 if account not found
    """
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    return state


@router.get("/portfolio/history/{account_name}", response_model=PaginatedResponse)
async def get_account_portfolio_history(
    account_name: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get historical portfolio state of a specific account with pagination.
    
    Args:
        account_name: Name of the account to get history for
        limit: Number of items per page (1-1000)
        cursor: Cursor for pagination (ISO timestamp)
        start_time: Start time for filtering results
        end_time: End time for filtering results
        
    Returns:
        Paginated response with historical account portfolio data
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


@router.get("/portfolio/distribution")
async def get_portfolio_distribution(accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get portfolio distribution by tokens with percentages across all accounts.
    
    Returns:
        Dictionary with token distribution including percentages, values, and breakdown by accounts/connectors
    """
    return accounts_service.get_portfolio_distribution()


@router.get("/portfolio/distribution/{account_name}")
async def get_account_portfolio_distribution(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get portfolio distribution by tokens with percentages for a specific account.
    
    Args:
        account_name: Name of the account to get distribution for
        
    Returns:
        Dictionary with token distribution for the specified account
        
    Raises:
        HTTPException: 404 if account not found
    """
    result = accounts_service.get_portfolio_distribution(account_name)
    
    # Check if account exists by looking at the distribution
    if result.get("token_count", 0) == 0 and not result.get("error") and account_name not in accounts_service.get_accounts_state():
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    return result


@router.get("/portfolio/accounts-distribution")
async def get_accounts_distribution(accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get portfolio distribution by accounts with percentages.
    
    Returns:
        Dictionary with account distribution including percentages, values, and breakdown by connectors
    """
    return accounts_service.get_account_distribution()


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


@router.get("/{account_name}/credentials", response_model=List[str])
async def list_account_credentials(account_name: str,
                                   accounts_service: AccountsService = Depends(get_accounts_service)):
    """
    Get a list of all connectors that have credentials configured for a specific account.

    Args:
        account_name: Name of the account to list credentials for

    Returns:
        List of connector names that have credentials configured

    Raises:
        HTTPException: 404 if account not found
    """
    try:
        credentials = accounts_service.list_credentials(account_name)
        # Remove .yml extension from filenames
        return [cred.replace('.yml', '') for cred in credentials]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


# Position Management Endpoints

@router.get("/{account_name}/{connector_name}/positions", response_model=List[Dict])
async def get_account_positions(
    account_name: str,
    connector_name: str,
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get current positions for a specific perpetual connector.
    
    This endpoint fetches real-time position data directly from the connector,
    including unrealized PnL, leverage, funding fees, and margin information.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the perpetual connector
        
    Returns:
        List of current position dictionaries with real-time data
        
    Raises:
        HTTPException: 400 if connector is not perpetual or doesn't support positions
        HTTPException: 404 if account or connector not found
        HTTPException: 500 if there's an error fetching positions
    """
    try:
        return await accounts_service.get_account_positions(account_name, connector_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions: {str(e)}")

@router.get("/{account_name}/positions/snapshots", response_model=List[Dict])
async def get_position_snapshots(
    account_name: str,
    connector_name: Optional[str] = Query(default=None, description="Filter by specific connector"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get latest position snapshots from database for historical analysis.
    
    Returns the most recent position snapshots for the specified account,
    optionally filtered by connector. Useful for tracking position history
    and performance over time.
    
    Args:
        account_name: Name of the account
        connector_name: Optional connector name to filter results
        
    Returns:
        List of latest position snapshot dictionaries from database
        
    Raises:
        HTTPException: 404 if account not found
        HTTPException: 500 if there's an error fetching snapshots
    """
    try:
        return await accounts_service.get_position_snapshots(account_name, connector_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching position snapshots: {str(e)}")


@router.get("/{account_name}/positions", response_model=List[Dict])
async def get_all_account_positions(
    account_name: str,
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get current positions across all perpetual connectors for an account.
    
    This endpoint aggregates real-time position data from all perpetual connectors
    associated with the specified account, providing a complete portfolio view.
    
    Args:
        account_name: Name of the account
        
    Returns:
        List of position dictionaries from all perpetual connectors
        
    Raises:
        HTTPException: 404 if account not found
        HTTPException: 500 if there's an error fetching positions
    """
    try:
        all_positions = []
        
        # Get all connectors for the account
        all_connectors = accounts_service.connector_manager.get_all_connectors()
        
        if account_name in all_connectors:
            for connector_name in all_connectors[account_name].keys():
                # Only fetch positions from perpetual connectors
                if "_perpetual" in connector_name:
                    try:
                        positions = await accounts_service.get_account_positions(account_name, connector_name)
                        all_positions.extend(positions)
                    except Exception as e:
                        # Log error but continue with other connectors
                        import logging
                        logging.warning(f"Failed to get positions for {connector_name}: {e}")
        
        return all_positions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching account positions: {str(e)}")


# Funding Fee Management Endpoints

@router.get("/{account_name}/{connector_name}/funding-payments", response_model=List[Dict])
async def get_funding_payments(
    account_name: str,
    connector_name: str,
    trading_pair: Optional[str] = Query(default=None, description="Filter by trading pair"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get funding payment history for a specific perpetual connector.
    
    This endpoint retrieves historical funding payment records including
    funding rates, payment amounts, and position data at time of payment.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the perpetual connector
        trading_pair: Optional trading pair filter
        limit: Maximum number of records to return
        
    Returns:
        List of funding payment records with rates, amounts, and position data
        
    Raises:
        HTTPException: 400 if connector is not perpetual
        HTTPException: 404 if account or connector not found
        HTTPException: 500 if there's an error fetching funding payments
    """
    try:
        # Validate this is a perpetual connector
        if "_perpetual" not in connector_name:
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' is not a perpetual connector")
        
        return await accounts_service.get_funding_payments(
            account_name=account_name,
            connector_name=connector_name,
            trading_pair=trading_pair,
            limit=limit
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching funding payments: {str(e)}")


@router.get("/{account_name}/{connector_name}/funding-fees/{trading_pair}", response_model=Dict)
async def get_total_funding_fees(
    account_name: str,
    connector_name: str,
    trading_pair: str,
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get total funding fees summary for a specific trading pair.
    
    This endpoint provides aggregated funding fee information including
    total fees paid/received, payment count, and fee currency.
    
    Args:
        account_name: Name of the account
        connector_name: Name of the perpetual connector
        trading_pair: Trading pair to get fees for
        
    Returns:
        Dictionary with total funding fees summary
        
    Raises:
        HTTPException: 400 if connector is not perpetual
        HTTPException: 404 if account or connector not found
        HTTPException: 500 if there's an error calculating fees
    """
    try:
        # Validate this is a perpetual connector
        if "_perpetual" not in connector_name:
            raise HTTPException(status_code=400, detail=f"Connector '{connector_name}' is not a perpetual connector")
        
        return await accounts_service.get_total_funding_fees(
            account_name=account_name,
            connector_name=connector_name,
            trading_pair=trading_pair
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating funding fees: {str(e)}")


@router.get("/{account_name}/funding-payments", response_model=List[Dict])
async def get_all_account_funding_payments(
    account_name: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get funding payment history across all perpetual connectors for an account.
    
    This endpoint aggregates funding payment data from all perpetual connectors
    associated with the specified account, providing a complete funding fee view.
    
    Args:
        account_name: Name of the account
        limit: Maximum number of records to return
        
    Returns:
        List of funding payment records from all perpetual connectors
        
    Raises:
        HTTPException: 404 if account not found
        HTTPException: 500 if there's an error fetching funding payments
    """
    try:
        all_funding_payments = []
        
        # Get all connectors for the account
        all_connectors = accounts_service.connector_manager.get_all_connectors()
        
        if account_name in all_connectors:
            for connector_name in all_connectors[account_name].keys():
                # Only fetch funding payments from perpetual connectors
                if "_perpetual" in connector_name:
                    try:
                        payments = await accounts_service.get_funding_payments(
                            account_name=account_name,
                            connector_name=connector_name,
                            limit=limit
                        )
                        all_funding_payments.extend(payments)
                    except Exception as e:
                        # Log error but continue with other connectors
                        import logging
                        logging.warning(f"Failed to get funding payments for {connector_name}: {e}")
        
        # Sort by timestamp (most recent first)
        all_funding_payments.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # Apply limit to the combined results
        return all_funding_payments[:limit]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching account funding payments: {str(e)}")



