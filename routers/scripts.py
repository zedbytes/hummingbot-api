import json
import yaml
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from starlette import status

from models import Script, ScriptConfig
from utils.file_system import FileSystemUtil

router = APIRouter(tags=["Scripts"], prefix="/scripts")
file_system = FileSystemUtil()


@router.get("/", response_model=List[str])
async def list_scripts():
    """
    List all available scripts.
    
    Returns:
        List of script names (without .py extension)
    """
    return [f.replace('.py', '') for f in file_system.list_files('scripts') if f.endswith('.py')]


@router.get("/{script_name}", response_model=Dict[str, str])
async def get_script(script_name: str):
    """
    Get script content by name.
    
    Args:
        script_name: Name of the script to retrieve
        
    Returns:
        Dictionary with script name and content
        
    Raises:
        HTTPException: 404 if script not found
    """
    try:
        content = file_system.read_file(f"scripts/{script_name}.py")
        return {
            "name": script_name,
            "content": content
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Script '{script_name}' not found")


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_or_update_script(script: Script):
    """
    Create or update a script.
    
    Args:
        script: Script object with name and content
        
    Returns:
        Success message when script is saved
        
    Raises:
        HTTPException: 400 if save error occurs
    """
    try:
        file_system.add_file('scripts', f"{script.name}.py", script.content, override=True)
        return {"message": f"Script '{script.name}' saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{script_name}")
async def delete_script(script_name: str):
    """
    Delete a script.
    
    Args:
        script_name: Name of the script to delete
        
    Returns:
        Success message when script is deleted
        
    Raises:
        HTTPException: 404 if script not found
    """
    try:
        file_system.delete_file('scripts', f"{script_name}.py")
        return {"message": f"Script '{script_name}' deleted successfully"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Script '{script_name}' not found")


# Script Configuration endpoints
@router.get("/{script_name}/config", response_model=Dict)
async def get_script_config(script_name: str):
    """
    Get script configuration.
    
    Args:
        script_name: Name of the script to get config for
        
    Returns:
        Dictionary with script configuration
        
    Raises:
        HTTPException: 404 if configuration not found
    """
    try:
        config = file_system.read_yaml_file(f"bots/conf/scripts/{script_name}.yml")
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Configuration for script '{script_name}' not found")


@router.get("/{script_name}/config/template", response_model=Dict)
async def get_script_config_template(script_name: str):
    """
    Get script configuration template with default values.
    
    Args:
        script_name: Name of the script to get template for
        
    Returns:
        Dictionary with configuration template and default values
        
    Raises:
        HTTPException: 404 if script configuration class not found
    """
    config_class = file_system.load_script_config_class(script_name)
    if config_class is None:
        raise HTTPException(status_code=404, detail=f"Script configuration class for '{script_name}' not found")

    # Extract fields and default values
    config_fields = {field.name: field.default for field in config_class.__fields__.values()}
    return json.loads(json.dumps(config_fields, default=str))


@router.post("/{script_name}/config", status_code=status.HTTP_201_CREATED)
async def create_or_update_script_config(script_name: str, config: Dict):
    """
    Create or update script configuration.
    
    Args:
        script_name: Name of the script
        config: Configuration dictionary to save
        
    Returns:
        Success message when configuration is saved
        
    Raises:
        HTTPException: 400 if save error occurs
    """
    try:
        yaml_content = yaml.dump(config, default_flow_style=False)
        file_system.add_file('conf/scripts', f"{script_name}.yml", yaml_content, override=True)
        return {"message": f"Configuration for script '{script_name}' saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{script_name}/config")
async def delete_script_config(script_name: str):
    """
    Delete script configuration.
    
    Args:
        script_name: Name of the script to delete config for
        
    Returns:
        Success message when configuration is deleted
        
    Raises:
        HTTPException: 404 if configuration not found
    """
    try:
        file_system.delete_file('conf/scripts', f"{script_name}.yml")
        return {"message": f"Configuration for script '{script_name}' deleted successfully"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Configuration for script '{script_name}' not found")


@router.get("/configs/", response_model=List[str])
async def list_script_configs():
    """
    List all script configurations.
    
    Returns:
        List of script configuration names
    """
    return [f.replace('.yml', '') for f in file_system.list_files('conf/scripts') if f.endswith('.yml')]