from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from starlette import status

from services.accounts_service import AccountsService
from deps import get_accounts_service
from models import PaginatedResponse

router = APIRouter(tags=["Accounts"], prefix="/accounts")


# Portfolio & Account State Monitoring
@router.get("/portfolio/state", response_model=Dict[str, Dict[str, List[Dict]]])
async def get_portfolio_state(
    account_names: Optional[List[str]] = Query(default=None, description="Filter by account names"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get the current state of all or filtered accounts portfolio.
    
    Args:
        account_names: Optional list of account names to filter by
        
    Returns:
        Dict containing account states with connector balances and token information
    """
    all_states = accounts_service.get_accounts_state()
    
    # If no filter, return all accounts
    if not account_names:
        return all_states
    
    # Filter by requested accounts
    filtered_states = {}
    for account_name in account_names:
        if account_name in all_states:
            filtered_states[account_name] = all_states[account_name]
    
    return filtered_states


@router.get("/portfolio/history", response_model=PaginatedResponse)
async def get_portfolio_history(
    account_names: Optional[List[str]] = Query(default=None, description="Filter by account names"),
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get the historical state of all or filtered accounts portfolio with pagination.
    
    Args:
        account_names: Optional list of account names to filter by
        limit: Number of items per page (1-1000)
        cursor: Cursor for pagination (ISO timestamp)
        start_time: Start time for filtering results
        end_time: End time for filtering results
        
    Returns:
        Paginated response with historical portfolio data
    """
    try:
        if not account_names:
            # Get history for all accounts
            data, next_cursor, has_more = await accounts_service.load_account_state_history(
                limit=limit,
                cursor=cursor,
                start_time=start_time,
                end_time=end_time
            )
        else:
            # Get history for specific accounts - need to aggregate
            all_data = []
            for account_name in account_names:
                acc_data, _, _ = await accounts_service.get_account_state_history(
                    account_name=account_name,
                    limit=limit,
                    cursor=cursor,
                    start_time=start_time,
                    end_time=end_time
                )
                all_data.extend(acc_data)
            
            # Sort by timestamp and apply pagination
            all_data.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            
            # Apply limit
            data = all_data[:limit]
            has_more = len(all_data) > limit
            next_cursor = data[-1]["timestamp"] if data and has_more else None
        
        return PaginatedResponse(
            data=data,
            pagination={
                "limit": limit,
                "has_more": has_more,
                "next_cursor": next_cursor,
                "current_cursor": cursor,
                "filters": {
                    "account_names": account_names,
                    "start_time": start_time.isoformat() if start_time else None,
                    "end_time": end_time.isoformat() if end_time else None
                }
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/portfolio/distribution")
async def get_portfolio_distribution(
    account_names: Optional[List[str]] = Query(default=None, description="Filter by account names"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get portfolio distribution by tokens with percentages across all or filtered accounts.
    
    Args:
        account_names: Optional list of account names to filter by
        
    Returns:
        Dictionary with token distribution including percentages, values, and breakdown by accounts/connectors
    """
    if not account_names:
        # Get distribution for all accounts
        return accounts_service.get_portfolio_distribution()
    elif len(account_names) == 1:
        # Single account - use existing method
        return accounts_service.get_portfolio_distribution(account_names[0])
    else:
        # Multiple accounts - need to aggregate
        aggregated_distribution = {
            "tokens": {},
            "total_value": 0,
            "token_count": 0,
            "accounts": {}
        }
        
        for account_name in account_names:
            account_dist = accounts_service.get_portfolio_distribution(account_name)
            
            # Skip if account doesn't exist or has error
            if account_dist.get("error") or account_dist.get("token_count", 0) == 0:
                continue
            
            # Aggregate token data
            for token, token_data in account_dist.get("tokens", {}).items():
                if token not in aggregated_distribution["tokens"]:
                    aggregated_distribution["tokens"][token] = {
                        "token": token,
                        "value": 0,
                        "percentage": 0,
                        "accounts": {}
                    }
                
                aggregated_distribution["tokens"][token]["value"] += token_data.get("value", 0)
                
                # Copy account-specific data
                for acc_name, acc_data in token_data.get("accounts", {}).items():
                    aggregated_distribution["tokens"][token]["accounts"][acc_name] = acc_data
            
            aggregated_distribution["total_value"] += account_dist.get("total_value", 0)
            aggregated_distribution["accounts"][account_name] = account_dist.get("accounts", {}).get(account_name, {})
        
        # Recalculate percentages
        total_value = aggregated_distribution["total_value"]
        if total_value > 0:
            for token_data in aggregated_distribution["tokens"].values():
                token_data["percentage"] = (token_data["value"] / total_value) * 100
        
        aggregated_distribution["token_count"] = len(aggregated_distribution["tokens"])
        
        return aggregated_distribution




@router.get("/portfolio/accounts-distribution")
async def get_accounts_distribution(
    account_names: Optional[List[str]] = Query(default=None, description="Filter by account names"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """
    Get portfolio distribution by accounts with percentages.
    
    Args:
        account_names: Optional list of account names to filter by
        
    Returns:
        Dictionary with account distribution including percentages, values, and breakdown by connectors
    """
    all_distribution = accounts_service.get_account_distribution()
    
    # If no filter, return all accounts
    if not account_names:
        return all_distribution
    
    # Filter the distribution by requested accounts
    filtered_distribution = {
        "accounts": {},
        "total_value": 0,
        "account_count": 0
    }
    
    for account_name in account_names:
        if account_name in all_distribution.get("accounts", {}):
            filtered_distribution["accounts"][account_name] = all_distribution["accounts"][account_name]
            filtered_distribution["total_value"] += all_distribution["accounts"][account_name].get("total_value", 0)
    
    # Recalculate percentages
    total_value = filtered_distribution["total_value"]
    if total_value > 0:
        for account_data in filtered_distribution["accounts"].values():
            account_data["percentage"] = (account_data.get("total_value", 0) / total_value) * 100
    
    filtered_distribution["account_count"] = len(filtered_distribution["accounts"])
    
    return filtered_distribution

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
