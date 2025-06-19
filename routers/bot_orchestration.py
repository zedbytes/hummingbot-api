import logging
import os
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks

from models import StartBotAction, StopBotAction, HummingbotInstanceConfig, V2ControllerDeployment
from services.bots_orchestrator import BotsOrchestrator
from services.docker_service import DockerService
from deps import get_bots_orchestrator, get_docker_service, get_bot_archiver
from utils.file_system import FileSystemUtil
from utils.bot_archiver import BotArchiver

router = APIRouter(tags=["Bot Orchestration"], prefix="/bot-orchestration")


@router.get("/status")
def get_active_bots_status(bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    """
    Get the status of all active bots.
    
    Args:
        bots_manager: Bot orchestrator service dependency
        
    Returns:
        Dictionary with status and data containing all active bot statuses
    """
    return {"status": "success", "data": bots_manager.get_all_bots_status()}


@router.get("/mqtt")
def get_mqtt_status(bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    """
    Get MQTT connection status and discovered bots.
    
    Args:
        bots_manager: Bot orchestrator service dependency
        
    Returns:
        Dictionary with MQTT connection status, discovered bots, and broker information
    """
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
    """
    Get the status of a specific bot.
    
    Args:
        bot_name: Name of the bot to get status for
        bots_manager: Bot orchestrator service dependency
        
    Returns:
        Dictionary with bot status information
        
    Raises:
        HTTPException: 404 if bot not found
    """
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
    """
    Get trading history for a bot with optional parameters.
    
    Args:
        bot_name: Name of the bot to get history for
        days: Number of days of history to retrieve (0 for all)
        verbose: Whether to include verbose output
        precision: Decimal precision for numerical values
        timeout: Timeout in seconds for the operation
        bots_manager: Bot orchestrator service dependency
        
    Returns:
        Dictionary with bot trading history
    """
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
    """
    Start a bot with the specified configuration.
    
    Args:
        action: StartBotAction containing bot configuration parameters
        bots_manager: Bot orchestrator service dependency
        
    Returns:
        Dictionary with status and response from bot start operation
    """
    response = await bots_manager.start_bot(action.bot_name, log_level=action.log_level, script=action.script,
                                      conf=action.conf, async_backend=action.async_backend)
    return {"status": "success", "response": response}


@router.post("/stop-bot")
async def stop_bot(action: StopBotAction, bots_manager: BotsOrchestrator = Depends(get_bots_orchestrator)):
    """
    Stop a bot with the specified configuration.
    
    Args:
        action: StopBotAction containing bot stop parameters
        bots_manager: Bot orchestrator service dependency
        
    Returns:
        Dictionary with status and response from bot stop operation
    """
    response = await bots_manager.stop_bot(action.bot_name, skip_order_cancellation=action.skip_order_cancellation,
                                     async_backend=action.async_backend)
    return {"status": "success", "response": response}


async def _background_stop_and_archive(
    bot_name: str,
    actual_bot_name: str,
    container_name: str,
    bot_name_for_orchestrator: str,
    skip_order_cancellation: bool,
    archive_locally: bool,
    s3_bucket: str,
    bots_manager: BotsOrchestrator,
    docker_manager: DockerService,
    bot_archiver: BotArchiver
):
    """Background task to handle the stop and archive process"""
    try:
        logging.info(f"Starting background stop-and-archive for {bot_name}")
        
        # Step 1: Stop the bot trading process
        logging.info(f"Stopping bot trading process for {bot_name_for_orchestrator}")
        stop_response = await bots_manager.stop_bot(
            bot_name_for_orchestrator, 
            skip_order_cancellation=skip_order_cancellation,
            async_backend=True  # Always use async for background tasks
        )
        
        if not stop_response or not stop_response.get("success", False):
            error_msg = stop_response.get('error', 'Unknown error') if stop_response else 'No response from bot orchestrator'
            logging.error(f"Failed to stop bot process: {error_msg}")
            return
        
        # Step 2: Wait for graceful shutdown (15 seconds as requested)
        logging.info(f"Waiting 15 seconds for bot {bot_name} to gracefully shutdown")
        await asyncio.sleep(15)
        
        # Step 3: Stop the container with monitoring
        max_retries = 10
        retry_interval = 2
        container_stopped = False
        
        for i in range(max_retries):
            logging.info(f"Attempting to stop container {container_name} (attempt {i+1}/{max_retries})")
            stop_container_response = docker_manager.stop_container(container_name)
            
            if stop_container_response.get("success", False):
                container_stopped = True
                break
                
            # Check if container is already stopped
            container_status = docker_manager.get_container_status(container_name)
            if container_status.get("state", {}).get("status") == "exited":
                container_stopped = True
                logging.info(f"Container {container_name} is already stopped")
                break
                
            await asyncio.sleep(retry_interval)
        
        if not container_stopped:
            logging.error(f"Failed to stop container {container_name} after {max_retries} attempts")
            return
        
        # Step 4: Archive the bot data
        instance_dir = os.path.join('bots', 'instances', container_name)
        logging.info(f"Archiving bot data from {instance_dir}")
        
        try:
            if archive_locally:
                bot_archiver.archive_locally(container_name, instance_dir)
            else:
                bot_archiver.archive_and_upload(container_name, instance_dir, bucket_name=s3_bucket)
            logging.info(f"Successfully archived bot data for {container_name}")
        except Exception as e:
            logging.error(f"Archive failed: {str(e)}")
            # Continue with removal even if archive fails
            
        # Step 5: Remove the container
        logging.info(f"Removing container {container_name}")
        remove_response = docker_manager.remove_container(container_name, force=False)
        
        if not remove_response.get("success"):
            # If graceful remove fails, try force remove
            logging.warning("Graceful container removal failed, attempting force removal")
            remove_response = docker_manager.remove_container(container_name, force=True)
        
        if remove_response.get("success"):
            logging.info(f"Successfully completed stop-and-archive for bot {bot_name}")
        else:
            logging.error(f"Failed to remove container {container_name}")
            
    except Exception as e:
        logging.error(f"Error in background stop-and-archive for {bot_name}: {str(e)}")


@router.post("/stop-and-archive-bot/{bot_name}")
async def stop_and_archive_bot(
    bot_name: str,
    background_tasks: BackgroundTasks,
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
    Gracefully stop a bot and archive its data in the background.
    This initiates a background task that will:
    1. Stop the bot trading process via MQTT
    2. Wait 15 seconds for graceful shutdown
    3. Monitor and stop the Docker container
    4. Archive the bot data (locally or to S3)
    5. Remove the container
    
    Returns immediately with a success message while the process continues in the background.
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
        
        # Use the format that's actually stored in active bots
        bot_name_for_orchestrator = container_name if container_name in active_bots else actual_bot_name
        
        # Add the background task
        background_tasks.add_task(
            _background_stop_and_archive,
            bot_name=bot_name,
            actual_bot_name=actual_bot_name,
            container_name=container_name,
            bot_name_for_orchestrator=bot_name_for_orchestrator,
            skip_order_cancellation=skip_order_cancellation,
            archive_locally=archive_locally,
            s3_bucket=s3_bucket,
            bots_manager=bots_manager,
            docker_manager=docker_manager,
            bot_archiver=bot_archiver
        )
        
        return {
            "status": "success",
            "message": f"Stop and archive process started for bot {actual_bot_name}",
            "details": {
                "input_name": bot_name,
                "actual_bot_name": actual_bot_name,
                "container_name": container_name,
                "process": "The bot will be gracefully stopped, archived, and removed in the background. This process typically takes 20-30 seconds."
            }
        }
        
    except Exception as e:
        logging.error(f"Error initiating stop_and_archive_bot for {bot_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-hummingbot-instance")
async def create_hummingbot_instance(
    config: HummingbotInstanceConfig, 
    docker_manager: DockerService = Depends(get_docker_service)
):
    """
    Create a new Hummingbot instance with the specified configuration.
    
    Args:
        config: Configuration for the new Hummingbot instance
        docker_manager: Docker service dependency
        
    Returns:
        Dictionary with creation response and instance details
    """
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
    
    Args:
        deployment: V2ControllerDeployment configuration
        docker_manager: Docker service dependency
        
    Returns:
        Dictionary with deployment response and generated configuration details
        
    Raises:
        HTTPException: 500 if deployment fails
    """
    try:
        # Generate unique script config filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        script_config_filename = f"{deployment.instance_name}-{timestamp}.yml"
        
        # Ensure controller config names have .yml extension
        controllers_with_extension = []
        for controller in deployment.controllers_config:
            if not controller.endswith('.yml'):
                controllers_with_extension.append(f"{controller}.yml")
            else:
                controllers_with_extension.append(controller)
        
        # Create the script config content
        script_config_content = {
            "script_file_name": "v2_with_controllers.py",
            "candles_config": [],
            "markets": {},
            "controllers_config": controllers_with_extension,
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