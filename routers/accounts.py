from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from hummingbot.client.settings import AllConnectorSettings
from hummingbot.core.data_type.common import PositionMode
from pydantic import BaseModel
from starlette import status

from services.accounts_service import AccountsService
from utils.file_system import FileSystemUtil
from deps import get_accounts_service
from models import PaginatedResponse

router = APIRouter(tags=["Accounts"], prefix="/accounts")
file_system = FileSystemUtil(base_path="bots/credentials")


class LeverageRequest(BaseModel):
    trading_pair: str
    leverage: int




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


class PositionModeRequest(BaseModel):
    position_mode: str

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

