import logging
import os

from fastapi import APIRouter, HTTPException, Depends

from models import ImageName
from utils.bot_archiver import BotArchiver
from services.docker_service import DockerService
from deps import get_docker_service, get_bot_archiver

router = APIRouter(tags=["Docker"], prefix="/docker")


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
async def pull_image(image: ImageName, docker_manager: DockerService = Depends(get_docker_service)):
    """
    Pull a Docker image from a registry.
    
    Args:
        image: ImageName object containing the image name to pull
        docker_manager: Docker service dependency
        
    Returns:
        Result of the image pull operation
        
    Raises:
        HTTPException: 400 if pull operation fails
    """
    try:
        result = docker_manager.pull_image(image.image_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
