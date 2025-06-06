from fastapi import APIRouter, HTTPException

from config import BROKER_HOST, BROKER_PASSWORD, BROKER_PORT, BROKER_USERNAME
from models import StartBotAction, StopBotAction
from services.bots_orchestrator import BotsOrchestrator

# Initialize the scheduler
router = APIRouter(tags=["Broker"])

# Log the broker configuration
import logging
logger = logging.getLogger(__name__)
logger.info(f"Broker config - Host: {BROKER_HOST}, Port: {BROKER_PORT}, Username: '{BROKER_USERNAME}', Has Password: {bool(BROKER_PASSWORD)}")

bots_manager = BotsOrchestrator(broker_host=BROKER_HOST, broker_port=BROKER_PORT, broker_username=BROKER_USERNAME,
                                broker_password=BROKER_PASSWORD)


# Startup and shutdown will be handled by lifespan context
_startup_task_created = False

@router.on_event("startup")
async def startup_event():
    global _startup_task_created
    if not _startup_task_created:
        bots_manager.start_update_active_bots_loop()
        _startup_task_created = True


@router.on_event("shutdown")
async def shutdown_event():
    # Shutdown the scheduler on application exit
    bots_manager.stop_update_active_bots_loop()


@router.get("/get-active-bots-status")
def get_active_bots_status():
    """Returns the cached status of all active bots."""
    return {"status": "success", "data": bots_manager.get_all_bots_status()}


@router.get("/mqtt-status")
def get_mqtt_status():
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

@router.get("/get-bot-status/{bot_name}")
def get_bot_status(bot_name: str):
    response = bots_manager.get_bot_status(bot_name)
    if not response:
        raise HTTPException(status_code=404, detail="Bot not found")
    return {
        "status": "success",
        "data": response
    }


@router.get("/get-bot-history/{bot_name}")
async def get_bot_history(
    bot_name: str, 
    days: int = 0, 
    verbose: bool = False, 
    precision: int = None, 
    timeout: float = 30.0
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
async def start_bot(action: StartBotAction):
    response = await bots_manager.start_bot(action.bot_name, log_level=action.log_level, script=action.script,
                                      conf=action.conf, async_backend=action.async_backend)
    return {"status": "success", "response": response}


@router.post("/stop-bot")
async def stop_bot(action: StopBotAction):
    response = await bots_manager.stop_bot(action.bot_name, skip_order_cancellation=action.skip_order_cancellation,
                                     async_backend=action.async_backend)
    return {"status": "success", "response": response}





