import logging
import os
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends

from models import StartBotAction, StopBotAction, HummingbotInstanceConfig, V2ControllerDeployment
from services.bots_orchestrator import BotsOrchestrator
from services.docker_service import DockerService
from deps import get_bots_orchestrator, get_docker_service, get_bot_archiver
from utils.file_system import FileSystemUtil
from utils.bot_archiver import BotArchiver

router = APIRouter(tags=["Bot Orchestration"], prefix="/bot-orchestration")


@router.get("/status")
def get_active_bots_status(bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    """Returns the cached status of all active bots."""
    return {"status": "success", "data": bots_manager.get_all_bots_status()}


@router.get("/mqtt")
def get_mqtt_status(bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    """Get MQTT connection status and discovered bots."""
    mqtt_connected = bots_manager.mqtt_manager.is_connected
    discovered_bots = bots_manager.mqtt_manager.get_discovered_bots()
    active_bots = list(bots_manager.active_bots.keys())
    
    # Check client state
    client_state = "connected" if bots_manager.mqtt_manager.is_connected else "disconnected"
    
    return {
        "status": "success",
        "data": {
            "mqtt_connected": mqtt_connected,
            "discovered_bots": discovered_bots,
            "active_bots": active_bots,
            "broker_host": bots_manager.broker_host,
            "broker_port": bots_manager.broker_port,
            "broker_username": bots_manager.broker_username,
            "client_state": client_state
        }
    }


@router.get("/{bot_name}/status")
def get_bot_status(bot_name: str, bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    response = bots_manager.get_bot_status(bot_name)
    if not response:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {
        "status": "success",
        "data": response
    }


@router.get("/{bot_name}/history")
async def get_bot_history(
    bot_name: str, 
    days: int = 0, 
    verbose: bool = False, 
    precision: int = None, 
    timeout: float = 30.0,
    bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)
):
    """Get trading history for a bot with optional parameters."""
    response = await bots_manager.get_bot_history(
        bot_name, 
        days=days, 
        verbose=verbose, 
        precision=precision, 
        timeout=timeout
    )
    return {"status": "success", "response": response}


@router.post("/start-bot")
async def start_bot(action: StartBotAction, bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    response = await bots_manager.start_bot(action.bot_name, log_level=action.log_level, script=action.script,
                                      conf=action.conf, async_backend=action.async_backend)
    return {"status": "success", "response": response}


@router.post("/stop-bot")
async def stop_bot(action: StopBotAction, bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    response = await bots_manager.stop_bot(action.bot_name, skip_order_cancellation=action.skip_order_cancellation,
                                     async_backend=action.async_backend)
    return {"status": "success", "response": response}


@router.post("/stop-and-archive-bot/{bot_name}")
async def stop_and_archive_bot(
    bot_name: str,
    skip_order_cancellation: bool = True,
    async_backend: bool = True,
    archive_locally: bool = True,
    s3_bucket: str = None,
    timeout: float = 30.0,
    bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator),
    docker_manager: DockerService = Depends(get_docker_service),
    bot_archiver: BotArchiver = Depends(get_bot_archiver)
):
    """
    Gracefully stop a bot and archive its data.
    This combines the complete shutdown workflow:
    1. Stop the bot trading process via MQTT
    2. Wait for graceful shutdown
    3. Stop the Docker container
    4. Archive the bot data (locally or to S3)
    5. Remove the container
    """
    try:
        # Step 1: Normalize bot name and container name
        # Handle both "process-king" and "hummingbot-process-king" input formats
        if bot_name.startswith("hummingbot-"):
            # If full container name is passed, extract the bot name
            actual_bot_name = bot_name.replace("hummingbot-", "")
            container_name = bot_name
        else:
            # If just bot name is passed, construct container name
            actual_bot_name = bot_name
            container_name = f"hummingbot-{bot_name}"
        
        logging.info(f"Normalized bot_name: {actual_bot_name}, container_name: {container_name}")
        
        # Step 2: Validate bot exists in active bots
        active_bots = list(bots_manager.active_bots.keys())
        
        # Check if bot exists in active bots (could be stored as either format)
        bot_found = (actual_bot_name in active_bots) or (container_name in active_bots)
        
        if not bot_found:
            return {
                "status": "error",
                "message": f"Bot '{actual_bot_name}' not found in active bots. Active bots: {active_bots}. Cannot perform graceful shutdown.",
                "details": {
                    "input_name": bot_name,
                    "actual_bot_name": actual_bot_name,
                    "container_name": container_name,
                    "active_bots": active_bots,
                    "reason": "Bot must be actively managed via MQTT for graceful shutdown"
                }
            }
        
        # Step 3: Stop the bot trading process
        # Use the format that's actually stored in active bots
        bot_name_for_orchestrator = container_name if container_name in active_bots else actual_bot_name
        logging.info(f"Stopping bot trading process for {bot_name_for_orchestrator}")
        stop_response = await bots_manager.stop_bot(
            bot_name_for_orchestrator, 
            skip_order_cancellation=skip_order_cancellation,
            async_backend=async_backend
        )
        
        if not stop_response or not stop_response.get("success", False):
            error_msg = stop_response.get('error', 'Unknown error') if stop_response else 'No response from bot orchestrator'
            return {
                "status": "error", 
                "message": f"Failed to stop bot process: {error_msg}",
                "details": {
                    "input_name": bot_name,
                    "actual_bot_name": actual_bot_name,
                    "container_name": container_name,
                    "stop_response": stop_response
                }
            }
        
        # Step 3: Wait a bit for graceful shutdown
        await asyncio.sleep(5)  # Give the bot time to clean up
        
        # Step 4: Stop the container
        logging.info(f"Stopping container {container_name}")
        stop_container_response = docker_manager.stop_container(container_name)
        
        if not stop_container_response.get("success", True):
            logging.warning(f"Container stop returned: {stop_container_response}")
        
        # Step 5: Archive the bot data
        instance_dir = os.path.join('bots', 'instances', container_name)
        logging.info(f"Archiving bot data from {instance_dir}")
        
        try:
            if archive_locally:
                bot_archiver.archive_locally(container_name, instance_dir)
            else:
                bot_archiver.archive_and_upload(container_name, instance_dir, bucket_name=s3_bucket)
        except Exception as e:
            logging.error(f"Archive failed: {str(e)}")
            # Continue with removal even if archive fails
            
        # Step 6: Remove the container
        logging.info(f"Removing container {container_name}")
        remove_response = docker_manager.remove_container(container_name, force=False)
        
        if not remove_response.get("success"):
            # If graceful remove fails, try force remove
            logging.warning("Graceful container removal failed, attempting force removal")
            remove_response = docker_manager.remove_container(container_name, force=True)
        
        return {
            "status": "success",
            "message": f"Bot {actual_bot_name} stopped and archived successfully",
            "details": {
                "input_name": bot_name,
                "actual_bot_name": actual_bot_name,
                "container_name": container_name,
                "bot_stopped": True,
                "container_stopped": stop_container_response.get("success", True),
                "archived": archive_locally or s3_bucket is not None,
                "container_removed": remove_response.get("success", False)
            }
        }
        
    except Exception as e:
        logging.error(f"Error in stop_and_archive_bot for {bot_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-hummingbot-instance")
async def create_hummingbot_instance(
    config: HummingbotInstanceConfig, 
    docker_manager: DockerService = Depends(get_docker_service)
):
    """Create a new Hummingbot instance with the specified configuration."""
    logging.info(f"Creating hummingbot instance with config: {config}")
    response = docker_manager.create_hummingbot_instance(config)
    return response


@router.post("/deploy-v2-controllers")
async def deploy_v2_controllers(
    deployment: V2ControllerDeployment,
    docker_manager: DockerService = Depends(get_docker_service)
):
    """
    Deploy a V2 strategy with controllers by generating the script config and creating the instance.
    This endpoint simplifies the deployment process for V2 controller strategies.
    """
    try:
        # Generate unique script config filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        script_config_filename = f"{deployment.instance_name}-{timestamp}.yml"
        
        # Create the script config content
        script_config_content = {
            "script_file_name": "v2_with_controllers.py",
            "candles_config": [],
            "markets": {},
            "controllers_config": deployment.controllers_config,
        }
        
        # Add optional drawdown parameters if provided
        if deployment.max_global_drawdown is not None:
            script_config_content["max_global_drawdown"] = deployment.max_global_drawdown
        if deployment.max_controller_drawdown is not None:
            script_config_content["max_controller_drawdown"] = deployment.max_controller_drawdown
        
        # Save the script config to the scripts directory
        scripts_dir = os.path.join("bots", "conf", "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        
        script_config_path = os.path.join(scripts_dir, script_config_filename)
        FileSystemUtil.dump_dict_to_yaml(script_config_path, script_config_content)
        
        logging.info(f"Generated script config: {script_config_filename} with content: {script_config_content}")
        
        # Create the HummingbotInstanceConfig with the generated script config
        instance_config = HummingbotInstanceConfig(
            instance_name=deployment.instance_name,
            credentials_profile=deployment.credentials_profile,
            image=deployment.image,
            script="v2_with_controllers.py",
            script_config=script_config_filename
        )
        
        # Deploy the instance using the existing method
        response = docker_manager.create_hummingbot_instance(instance_config)
        
        if response.get("success"):
            response["script_config_generated"] = script_config_filename
            response["controllers_deployed"] = deployment.controllers_config
            
        return response
        
    except Exception as e:
        logging.error(f"Error deploying V2 controllers: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))