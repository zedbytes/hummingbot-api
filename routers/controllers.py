import json
import yaml
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from starlette import status

from models import Controller, ControllerConfig, ControllerType
from utils.file_system import FileSystemUtil

router = APIRouter(tags=["Controllers"], prefix="/controllers")
file_system = FileSystemUtil()


@router.get("/", response_model=Dict[str, List[str]])
async def list_controllers():
    """List all controllers organized by type."""
    result = {}
    for controller_type in ControllerType:
        try:
            files = file_system.list_files(f'controllers/{controller_type.value}')
            result[controller_type.value] = [
                f.replace('.py', '') for f in files 
                if f.endswith('.py') and f != "__init__.py"
            ]
        except FileNotFoundError:
            result[controller_type.value] = []
    return result


@router.get("/{controller_type}", response_model=List[str])
async def list_controllers_by_type(controller_type: ControllerType):
    """List controllers of a specific type."""
    try:
        files = file_system.list_files(f'controllers/{controller_type.value}')
        return [f.replace('.py', '') for f in files if f.endswith('.py') and f != "__init__.py"]
    except FileNotFoundError:
        return []


@router.get("/{controller_type}/{controller_name}", response_model=Dict[str, str])
async def get_controller(controller_type: ControllerType, controller_name: str):
    """Get controller content by type and name."""
    try:
        content = file_system.read_file(f"controllers/{controller_type.value}/{controller_name}.py")
        return {
            "name": controller_name,
            "type": controller_type.value,
            "content": content
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, 
            detail=f"Controller '{controller_name}' not found in '{controller_type.value}'"
        )


@router.post("/{controller_type}", status_code=status.HTTP_201_CREATED)
async def create_or_update_controller(controller_type: ControllerType, controller: Controller):
    """Create or update a controller."""
    if controller.type != controller_type:
        raise HTTPException(
            status_code=400, 
            detail=f"Controller type mismatch: URL has '{controller_type}', body has '{controller.type}'"
        )
    
    try:
        file_system.add_file(
            f'controllers/{controller_type.value}', 
            f"{controller.name}.py", 
            controller.content, 
            override=True
        )
        return {"message": f"Controller '{controller.name}' saved successfully in '{controller_type.value}'"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{controller_type}/{controller_name}")
async def delete_controller(controller_type: ControllerType, controller_name: str):
    """Delete a controller."""
    try:
        file_system.delete_file(f'controllers/{controller_type.value}', f"{controller_name}.py")
        return {"message": f"Controller '{controller_name}' deleted successfully from '{controller_type.value}'"}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, 
            detail=f"Controller '{controller_name}' not found in '{controller_type.value}'"
        )


# Controller Configuration endpoints
@router.get("/{controller_name}/config", response_model=Dict)
async def get_controller_config(controller_name: str):
    """Get controller configuration."""
    try:
        config = file_system.read_yaml_file(f"bots/conf/controllers/{controller_name}.yml")
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Configuration for controller '{controller_name}' not found")


@router.get("/{controller_type}/{controller_name}/config/template", response_model=Dict)
async def get_controller_config_template(controller_type: ControllerType, controller_name: str):
    """Get controller configuration template with default values."""
    config_class = file_system.load_controller_config_class(controller_type.value, controller_name)
    if config_class is None:
        raise HTTPException(
            status_code=404, 
            detail=f"Controller configuration class for '{controller_name}' not found"
        )

    # Extract fields and default values
    config_fields = {name: field.default for name, field in config_class.model_fields.items()}
    return json.loads(json.dumps(config_fields, default=str))


@router.post("/{controller_name}/config", status_code=status.HTTP_201_CREATED)
async def create_or_update_controller_config(controller_name: str, config: Dict):
    """Create or update controller configuration."""
    try:
        yaml_content = yaml.dump(config, default_flow_style=False)
        file_system.add_file('conf/controllers', f"{controller_name}.yml", yaml_content, override=True)
        return {"message": f"Configuration for controller '{controller_name}' saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{controller_name}/config")
async def delete_controller_config(controller_name: str):
    """Delete controller configuration."""
    try:
        file_system.delete_file('conf/controllers', f"{controller_name}.yml")
        return {"message": f"Configuration for controller '{controller_name}' deleted successfully"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Configuration for controller '{controller_name}' not found")


@router.get("/configs/", response_model=List[str])
async def list_controller_configs():
    """List all controller configurations."""
    return [f.replace('.yml', '') for f in file_system.list_files('conf/controllers') if f.endswith('.yml')]


# Bot-specific controller config endpoints
@router.get("/bots/{bot_name}/configs", response_model=List[Dict])
async def get_bot_controller_configs(bot_name: str):
    """Get all controller configurations for a specific bot."""
    bots_config_path = f"instances/{bot_name}/conf/controllers"
    if not file_system.path_exists(bots_config_path):
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")
    
    configs = []
    for controller_file in file_system.list_files(bots_config_path):
        if controller_file.endswith('.yml'):
            config = file_system.read_yaml_file(f"bots/{bots_config_path}/{controller_file}")
            config['_config_name'] = controller_file.replace('.yml', '')
            configs.append(config)
    return configs


@router.post("/bots/{bot_name}/{controller_name}/config")
async def update_bot_controller_config(bot_name: str, controller_name: str, config: Dict):
    """Update controller configuration for a specific bot."""
    bots_config_path = f"instances/{bot_name}/conf/controllers"
    if not file_system.path_exists(bots_config_path):
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")
    
    try:
        current_config = file_system.read_yaml_file(f"bots/{bots_config_path}/{controller_name}.yml")
        current_config.update(config)
        file_system.dump_dict_to_yaml(f"bots/{bots_config_path}/{controller_name}.yml", current_config)
        return {"message": f"Controller configuration for bot '{bot_name}' updated successfully"}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, 
            detail=f"Controller configuration '{controller_name}' not found for bot '{bot_name}'"
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))