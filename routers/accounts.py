from typing import Dict, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from hummingbot.client.settings import AllConnectorSettings
from starlette import status

from services.accounts_service import AccountsService
from utils.file_system import FileSystemUtil
from deps import get_accounts_service
from models import PaginatedResponse

router = APIRouter(tags=["Accounts"], prefix="/accounts")
file_system = FileSystemUtil(base_path="bots/credentials")


@router.get("/state", response_model=Dict[str, Dict[str, List[Dict]]])
async def get_all_accounts_state(accounts_service: AccountsService = Depends(get_accounts_service)):
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
    return list(AllConnectorSettings.get_connector_settings().keys())


@router.get("/connector-config-map/{connector_name}", response_model=List[str])
async def get_connector_config_map(connector_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    return accounts_service.get_connector_config_map(connector_name)


@router.get("/all-connectors-config-map", response_model=Dict[str, List[str]])
async def get_all_connectors_config_map(accounts_service: AccountsService = Depends(get_accounts_service)):
    all_config_maps = {}
    for connector in list(AllConnectorSettings.get_connector_settings().keys()):
        all_config_maps[connector] = accounts_service.get_connector_config_map(connector)
    return all_config_maps


@router.get("/", response_model=List[str])
async def list_accounts(accounts_service: AccountsService = Depends(get_accounts_service)):
    return accounts_service.list_accounts()


@router.get("/{account_name}/credentials", response_model=List[str])
async def list_credentials(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    try:
        return accounts_service.list_credentials(account_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/add-account", status_code=status.HTTP_201_CREATED)
async def add_account(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    try:
        accounts_service.add_account(account_name)
        return {"message": "Credential added successfully."}
    except FileExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/delete-account")
async def delete_account(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    try:
        if account_name == "master_account":
            raise HTTPException(status_code=400, detail="Cannot delete master account.")
        accounts_service.delete_account(account_name)
        return {"message": "Credential deleted successfully."}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/delete-credential/{account_name}/{connector_name}")
async def delete_credential(account_name: str, connector_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    try:
        accounts_service.delete_credentials(account_name, connector_name)
        return {"message": "Credential deleted successfully."}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/add-connector-keys/{account_name}/{connector_name}", status_code=status.HTTP_201_CREATED)
async def add_connector_keys(account_name: str, connector_name: str, keys: Dict, accounts_service: AccountsService = Depends(get_accounts_service)):
    try:
        await accounts_service.add_connector_keys(account_name, connector_name, keys)
        return {"message": "Connector keys added successfully."}
    except Exception as e:
        accounts_service.delete_credentials(account_name, connector_name)
        raise HTTPException(status_code=400, detail=str(e))


# Account-specific routes
@router.get("/accounts/{account_name}/state", response_model=Dict[str, List[Dict]])
async def get_account_state(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get current state of a specific account."""
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    return state


@router.get("/accounts/{account_name}/state/history", response_model=PaginatedResponse)
async def get_account_history(
    account_name: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """Get historical state of a specific account with pagination."""
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


@router.get("/accounts/{account_name}/value", response_model=Dict)
async def get_account_value(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get total portfolio value for a specific account."""
    value_data = await accounts_service.get_portfolio_value(account_name)
    if account_name not in value_data["accounts"]:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    return {
        "account_name": account_name,
        "total_value": value_data["accounts"].get(account_name, 0)
    }


@router.get("/accounts/{account_name}/tokens", response_model=List[Dict])
async def get_account_tokens(account_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get all tokens held by a specific account."""
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    tokens = {}
    for connector_name, token_list in state.items():
        for token_info in token_list:
            token = token_info["token"]
            if token not in tokens:
                tokens[token] = {
                    "token": token,
                    "total_units": 0,
                    "total_value": 0,
                    "average_price": 0,
                    "connectors": []
                }
            tokens[token]["total_units"] += token_info["units"]
            tokens[token]["total_value"] += token_info["value"]
            tokens[token]["connectors"].append({
                "connector": connector_name,
                "units": token_info["units"],
                "value": token_info["value"]
            })
    
    # Calculate average price
    for token_data in tokens.values():
        if token_data["total_units"] > 0:
            token_data["average_price"] = token_data["total_value"] / token_data["total_units"]
    
    return list(tokens.values())


# Connector-specific routes
@router.get("/accounts/{account_name}/connectors/{connector_name}/state", response_model=List[Dict])
async def get_connector_state(account_name: str, connector_name: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get current state of a specific connector."""
    state = await accounts_service.get_connector_current_state(account_name, connector_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found for account '{account_name}'")
    return state


@router.get("/accounts/{account_name}/connectors/{connector_name}/state/history", response_model=PaginatedResponse)
async def get_connector_history(
    account_name: str,
    connector_name: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Number of items per page"),
    cursor: str = Query(default=None, description="Cursor for next page (ISO timestamp)"),
    start_time: datetime = Query(default=None, description="Start time for filtering"),
    end_time: datetime = Query(default=None, description="End time for filtering"),
    accounts_service: AccountsService = Depends(get_accounts_service)
):
    """Get historical state of a specific connector with pagination."""
    data, next_cursor, has_more = await accounts_service.get_connector_state_history(
        account_name=account_name,
        connector_name=connector_name,
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
                "connector_name": connector_name,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None
            }
        }
    )


# Token-specific routes
@router.get("/tokens", response_model=List[str])
async def get_all_tokens(accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get all unique tokens across all accounts and connectors."""
    return await accounts_service.get_all_unique_tokens()


@router.get("/tokens/{token}/state", response_model=List[Dict])
async def get_token_state(token: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get current state of a specific token across all accounts."""
    state = await accounts_service.get_token_current_state(token)
    if not state:
        raise HTTPException(status_code=404, detail=f"Token '{token}' not found")
    return state


@router.get("/tokens/{token}/accounts", response_model=List[Dict])
async def get_token_accounts(token: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get all accounts that hold a specific token."""
    token_states = await accounts_service.get_token_current_state(token)
    if not token_states:
        raise HTTPException(status_code=404, detail=f"Token '{token}' not found")
    
    accounts = {}
    for state in token_states:
        account_name = state["account_name"]
        if account_name not in accounts:
            accounts[account_name] = {
                "account_name": account_name,
                "total_units": 0,
                "total_value": 0,
                "connectors": []
            }
        accounts[account_name]["total_units"] += state["units"]
        accounts[account_name]["total_value"] += state["value"]
        accounts[account_name]["connectors"].append({
            "connector_name": state["connector_name"],
            "units": state["units"],
            "value": state["value"]
        })
    
    return list(accounts.values())


@router.get("/accounts/{account_name}/tokens/{token}", response_model=Dict)
async def get_account_token_state(account_name: str, token: str, accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get state of a specific token for a specific account."""
    state = await accounts_service.get_account_current_state(account_name)
    if not state:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    token_data = {
        "token": token,
        "account_name": account_name,
        "total_units": 0,
        "total_value": 0,
        "connectors": []
    }
    
    for connector_name, token_list in state.items():
        for token_info in token_list:
            if token_info["token"] == token:
                token_data["total_units"] += token_info["units"]
                token_data["total_value"] += token_info["value"]
                token_data["connectors"].append({
                    "connector_name": connector_name,
                    "units": token_info["units"],
                    "value": token_info["value"],
                    "price": token_info["price"],
                    "available_units": token_info["available_units"]
                })
    
    if not token_data["connectors"]:
        raise HTTPException(status_code=404, detail=f"Token '{token}' not found for account '{account_name}'")
    
    return token_data


# Portfolio aggregation routes
@router.get("/portfolio/value", response_model=Dict)
async def get_portfolio_value(accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get total portfolio value across all accounts."""
    return await accounts_service.get_portfolio_value()


@router.get("/portfolio/tokens", response_model=List[Dict])
async def get_portfolio_tokens(accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get all tokens with aggregated holdings across all accounts."""
    all_states = accounts_service.get_accounts_state()
    
    tokens = {}
    for account_name, connectors in all_states.items():
        for connector_name, token_list in connectors.items():
            for token_info in token_list:
                token = token_info["token"]
                if token not in tokens:
                    tokens[token] = {
                        "token": token,
                        "total_units": 0,
                        "total_value": 0,
                        "accounts": {}
                    }
                tokens[token]["total_units"] += token_info["units"]
                tokens[token]["total_value"] += token_info["value"]
                
                if account_name not in tokens[token]["accounts"]:
                    tokens[token]["accounts"][account_name] = {
                        "units": 0,
                        "value": 0
                    }
                tokens[token]["accounts"][account_name]["units"] += token_info["units"]
                tokens[token]["accounts"][account_name]["value"] += token_info["value"]
    
    # Convert accounts dict to list for response
    result = []
    for token, data in tokens.items():
        token_data = {
            "token": token,
            "total_units": data["total_units"],
            "total_value": data["total_value"],
            "average_price": data["total_value"] / data["total_units"] if data["total_units"] > 0 else 0,
            "accounts": [
                {
                    "account_name": acc_name,
                    "units": acc_data["units"],
                    "value": acc_data["value"]
                }
                for acc_name, acc_data in data["accounts"].items()
            ]
        }
        result.append(token_data)
    
    # Sort by total value descending
    result.sort(key=lambda x: x["total_value"], reverse=True)
    
    return result


@router.get("/portfolio/distribution", response_model=Dict)
async def get_portfolio_distribution(accounts_service: AccountsService = Depends(get_accounts_service)):
    """Get portfolio distribution by token and exchange."""
    all_states = accounts_service.get_accounts_state()
    portfolio_value = await accounts_service.get_portfolio_value()
    total_value = portfolio_value["total_value"]
    
    if total_value == 0:
        return {
            "total_value": 0,
            "by_token": {},
            "by_exchange": {},
            "by_account": {}
        }
    
    # Distribution by token
    by_token = {}
    by_exchange = {}
    
    for account_name, connectors in all_states.items():
        for connector_name, token_list in connectors.items():
            if connector_name not in by_exchange:
                by_exchange[connector_name] = {"value": 0, "percentage": 0}
            
            for token_info in token_list:
                token = token_info["token"]
                value = token_info["value"]
                
                if token not in by_token:
                    by_token[token] = {"value": 0, "percentage": 0}
                
                by_token[token]["value"] += value
                by_exchange[connector_name]["value"] += value
    
    # Calculate percentages
    for token_data in by_token.values():
        token_data["percentage"] = (token_data["value"] / total_value) * 100
    
    for exchange_data in by_exchange.values():
        exchange_data["percentage"] = (exchange_data["value"] / total_value) * 100
    
    # Account distribution from portfolio value
    by_account = {}
    for account_name, value in portfolio_value["accounts"].items():
        by_account[account_name] = {
            "value": value,
            "percentage": (value / total_value) * 100 if total_value > 0 else 0
        }
    
    return {
        "total_value": total_value,
        "by_token": by_token,
        "by_exchange": by_exchange,
        "by_account": by_account
    }
