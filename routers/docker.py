import logging
import os
import time
from typing import Dict

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks

from models import DockerImage
from utils.bot_archiver import BotArchiver
from services.docker_service import DockerService
from deps import get_docker_service, get_bot_archiver

router = APIRouter(tags=["Docker"], prefix="/docker")

# Global state to track image pulls (in production, consider using Redis or database)
_pull_status: Dict[str, Dict] = {}

# Configuration for cleanup
PULL_STATUS_MAX_AGE_SECONDS = 3600  # Keep status for 1 hour
PULL_STATUS_MAX_ENTRIES = 100  # Maximum number of entries to keep


def _cleanup_old_pull_status():
    """Remove old entries to prevent memory growth"""
    current_time = time.time()
    to_remove = []
    
    # Find entries older than max age
    for image_name, status_info in _pull_status.items():
        # Skip ongoing pulls
        if status_info["status"] == "pulling":
            continue
            
        # Check age of completed/failed operations
        end_time = status_info.get("completed_at") or status_info.get("failed_at")
        if end_time and (current_time - end_time > PULL_STATUS_MAX_AGE_SECONDS):
            to_remove.append(image_name)
    
    # Remove old entries
    for image_name in to_remove:
        del _pull_status[image_name]
        logging.info(f"Cleaned up old pull status for {image_name}")
    
    # If still over limit, remove oldest completed/failed entries
    if len(_pull_status) > PULL_STATUS_MAX_ENTRIES:
        completed_entries = [
            (name, info) for name, info in _pull_status.items() 
            if info["status"] in ["completed", "failed"]
        ]
        # Sort by end time (oldest first)
        completed_entries.sort(
            key=lambda x: x[1].get("completed_at") or x[1].get("failed_at") or 0
        )
        
        # Remove oldest entries to get under limit
        excess_count = len(_pull_status) - PULL_STATUS_MAX_ENTRIES
        for i in range(min(excess_count, len(completed_entries))):
            del _pull_status[completed_entries[i][0]]
            logging.info(f"Cleaned up excess pull status for {completed_entries[i][0]}")


def _background_pull_image(image_name: str, docker_manager: DockerService):
    """Background task to pull Docker image"""
    try:
        _pull_status[image_name] = {
            "status": "pulling", 
            "started_at": time.time(),
            "progress": "Starting pull..."
        }
        
        # Use the synchronous pull method in background
        result = docker_manager.pull_image_sync(image_name)
        
        if result.get("success"):
            _pull_status[image_name] = {
                "status": "completed", 
                "started_at": _pull_status[image_name]["started_at"],
                "completed_at": time.time(),
                "result": result
            }
        else:
            _pull_status[image_name] = {
                "status": "failed", 
                "started_at": _pull_status[image_name]["started_at"],
                "failed_at": time.time(),
                "error": result.get("error", "Unknown error")
            }
    except Exception as e:
        _pull_status[image_name] = {
            "status": "failed", 
            "started_at": _pull_status[image_name].get("started_at", time.time()),
            "failed_at": time.time(),
            "error": str(e)
        }


@router.get("/running")
async def is_docker_running(docker_manager: DockerService = Depends(get_docker_service)):
    """
    Check if Docker daemon is running.
    
    Args:
        docker_manager: Docker service dependency
        
    Returns:
        Dictionary indicating if Docker is running
    """
    return {"is_docker_running": docker_manager.is_docker_running()}


@router.get("/available-images/{image_name}")
async def available_images(image_name: str, docker_manager: DockerService = Depends(get_docker_service)):
    """
    Get available Docker images matching the specified name.
    
    Args:
        image_name: Name pattern to search for in image tags
        docker_manager: Docker service dependency
        
    Returns:
        Dictionary with list of available image tags
    """
    available_images = docker_manager.get_available_images()
    image_tags = [tag for image in available_images["images"] for tag in image.tags if image_name in tag]
    return {"available_images": image_tags}


@router.get("/active-containers")
async def active_containers(docker_manager: DockerService = Depends(get_docker_service)):
    """
    Get all currently active (running) Docker containers.
    
    Args:
        docker_manager: Docker service dependency
        
    Returns:
        List of active container information
    """
    return docker_manager.get_active_containers()


@router.get("/exited-containers")
async def exited_containers(docker_manager: DockerService = Depends(get_docker_service)):
    """
    Get all exited (stopped) Docker containers.
    
    Args:
        docker_manager: Docker service dependency
        
    Returns:
        List of exited container information
    """
    return docker_manager.get_exited_containers()


@router.post("/clean-exited-containers")
async def clean_exited_containers(docker_manager: DockerService = Depends(get_docker_service)):
    """
    Remove all exited Docker containers to free up space.
    
    Args:
        docker_manager: Docker service dependency
        
    Returns:
        Response from cleanup operation
    """
    return docker_manager.clean_exited_containers()


@router.post("/remove-container/{container_name}")
async def remove_container(container_name: str, archive_locally: bool = True, s3_bucket: str = None, docker_manager: DockerService = Depends(get_docker_service), bot_archiver: BotArchiver = Depends(get_bot_archiver)):
    """
    Remove a Docker container and optionally archive its data.
    
    Args:
        container_name: Name of the container to remove
        archive_locally: Whether to archive data locally (default: True)
        s3_bucket: S3 bucket name for cloud archiving (optional)
        docker_manager: Docker service dependency
        bot_archiver: Bot archiver service dependency
        
    Returns:
        Response from container removal operation
        
    Raises:
        HTTPException: 500 if archiving fails
    """
    # Remove the container
    response = docker_manager.remove_container(container_name)
    # Form the instance directory path correctly
    instance_dir = os.path.join('bots', 'instances', container_name)
    try:
        # Archive the data
        if archive_locally:
            bot_archiver.archive_locally(container_name, instance_dir)
        else:
            bot_archiver.archive_and_upload(container_name, instance_dir, bucket_name=s3_bucket)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return response


@router.post("/stop-container/{container_name}")
async def stop_container(container_name: str, docker_manager: DockerService = Depends(get_docker_service)):
    """
    Stop a running Docker container.
    
    Args:
        container_name: Name of the container to stop
        docker_manager: Docker service dependency
        
    Returns:
        Response from container stop operation
    """
    return docker_manager.stop_container(container_name)


@router.post("/start-container/{container_name}")
async def start_container(container_name: str, docker_manager: DockerService = Depends(get_docker_service)):
    """
    Start a stopped Docker container.
    
    Args:
        container_name: Name of the container to start
        docker_manager: Docker service dependency
        
    Returns:
        Response from container start operation
    """
    return docker_manager.start_container(container_name)


@router.post("/pull-image/")
async def pull_image(image: DockerImage, background_tasks: BackgroundTasks, 
                     docker_manager: DockerService = Depends(get_docker_service)):
    """
    Initiate Docker image pull as background task.
    Returns immediately with task status for monitoring.
    
    Args:
        image: DockerImage object containing the image name to pull
        background_tasks: FastAPI background tasks
        docker_manager: Docker service dependency
        
    Returns:
        Status of the pull operation initiation
    """
    image_name = image.image_name
    
    # Run cleanup before starting new pull
    _cleanup_old_pull_status()
    
    # Check if pull is already in progress
    if image_name in _pull_status:
        current_status = _pull_status[image_name]
        if current_status["status"] == "pulling":
            return {
                "message": f"Pull already in progress for {image_name}",
                "status": "in_progress",
                "started_at": current_status["started_at"],
                "image_name": image_name
            }
    
    # Start background pull
    background_tasks.add_task(_background_pull_image, image_name, docker_manager)
    
    return {
        "message": f"Pull started for {image_name}",
        "status": "started",
        "image_name": image_name,
        "note": "Use GET /docker/pull-status/{image_name} to check progress"
    }


@router.get("/pull-status/{image_name}")
async def get_pull_status(image_name: str):
    """
    Get status of image pull operation.
    
    Args:
        image_name: Name of the image to check pull status for
        
    Returns:
        Dictionary with pull status, timing, and result information
        
    Raises:
        HTTPException: 404 if no pull operation found for this image
    """
    if image_name not in _pull_status:
        raise HTTPException(status_code=404, detail=f"No pull operation found for image '{image_name}'")
    
    status_info = _pull_status[image_name].copy()
    
    # Add duration information
    start_time = status_info.get("started_at")
    if start_time:
        if status_info["status"] == "pulling":
            status_info["duration_seconds"] = round(time.time() - start_time, 2)
        elif "completed_at" in status_info:
            status_info["duration_seconds"] = round(status_info["completed_at"] - start_time, 2)
        elif "failed_at" in status_info:
            status_info["duration_seconds"] = round(status_info["failed_at"] - start_time, 2)
    
    return {
        "image_name": image_name,
        **status_info
    }


@router.get("/pull-status/")
async def list_pull_operations():
    """
    List all current and recent pull operations.
    
    Returns:
        Dictionary with all pull operations and their statuses
    """
    operations = {}
    for image_name, status_info in _pull_status.items():
        status_copy = status_info.copy()
        
        # Add duration for each operation
        start_time = status_copy.get("started_at")
        if start_time:
            if status_copy["status"] == "pulling":
                status_copy["duration_seconds"] = round(time.time() - start_time, 2)
            elif "completed_at" in status_copy:
                status_copy["duration_seconds"] = round(status_copy["completed_at"] - start_time, 2)
            elif "failed_at" in status_copy:
                status_copy["duration_seconds"] = round(status_copy["failed_at"] - start_time, 2)
        
        operations[image_name] = status_copy
    
    return {
        "pull_operations": operations,
        "total_operations": len(operations)
    }


@router.delete("/pull-status/{image_name}")
async def clear_pull_status(image_name: str):
    """
    Clear pull status for completed or failed operations.
    
    Args:
        image_name: Name of the image to clear status for
        
    Returns:
        Success message when status is cleared
        
    Raises:
        HTTPException: 400 if trying to clear ongoing operation, 404 if operation not found
    """
    if image_name not in _pull_status:
        raise HTTPException(status_code=404, detail=f"Pull operation for '{image_name}' not found")
    
    status = _pull_status[image_name]["status"]
    if status == "pulling":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot clear status for ongoing pull operation. Current status: {status}"
        )
    
    del _pull_status[image_name]
    return {"message": f"Cleared pull status for '{image_name}'"}


@router.delete("/pull-status/")
async def clear_all_completed_pull_status():
    """
    Clear all completed and failed pull operations from status tracking.
    
    Returns:
        Summary of cleared operations
    """
    cleared_count = 0
    cleared_images = []
    
    # Create a list of items to remove to avoid modifying dict during iteration
    to_remove = []
    for image_name, status_info in _pull_status.items():
        if status_info["status"] in ["completed", "failed"]:
            to_remove.append(image_name)
    
    # Remove the completed/failed operations
    for image_name in to_remove:
        del _pull_status[image_name]
        cleared_images.append(image_name)
        cleared_count += 1
    
    return {
        "message": f"Cleared {cleared_count} completed/failed pull operations",
        "cleared_images": cleared_images,
        "remaining_operations": len(_pull_status)
    }
