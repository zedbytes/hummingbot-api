from pydantic import BaseModel


class DockerImage(BaseModel):
    image_name: str