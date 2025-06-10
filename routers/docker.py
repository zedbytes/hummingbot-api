import logging
import os

from fastapi import APIRouter, HTTPException, Depends

from models import ImageName
from utils.bot_archiver import BotArchiver
from services.docker_service import DockerService
from deps import get_docker_service, get_bot_archiver

router = APIRouter(tags=["Docker"])


@router.get("/is-docker-running")
async def is_docker_running(docker_manager: DockerService = Depends(get_docker_service)):
    return {"is_docker_running": docker_manager.is_docker_running()}


@router.get("/available-images/{image_name}")
async def available_images(image_name: str, docker_manager: DockerService = Depends(get_docker_service)):
    available_images = docker_manager.get_available_images()
    image_tags = [tag for image in available_images["images"] for tag in image.tags if image_name in tag]
    return {"available_images": image_tags}


@router.get("/active-containers")
async def active_containers(docker_manager: DockerService = Depends(get_docker_service)):
    return docker_manager.get_active_containers()


@router.get("/exited-containers")
async def exited_containers(docker_manager: DockerService = Depends(get_docker_service)):
    return docker_manager.get_exited_containers()


@router.post("/clean-exited-containers")
async def clean_exited_containers(docker_manager: DockerService = Depends(get_docker_service)):
    return docker_manager.clean_exited_containers()


@router.post("/remove-container/{container_name}")
async def remove_container(container_name: str, archive_locally: bool = True, s3_bucket: str = None, docker_manager: DockerService = Depends(get_docker_service), bot_archiver: BotArchiver = Depends(get_bot_archiver)):
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
    return docker_manager.stop_container(container_name)


@router.post("/start-container/{container_name}")
async def start_container(container_name: str, docker_manager: DockerService = Depends(get_docker_service)):
    return docker_manager.start_container(container_name)


@router.post("/pull-image/")
async def pull_image(image: ImageName, docker_manager: DockerService = Depends(get_docker_service)):
    try:
        result = docker_manager.pull_image(image.image_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
