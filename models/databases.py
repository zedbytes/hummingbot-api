from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class DatabaseInfo(BaseModel):
    """Information about a database"""
    db_name: str = Field(description="Database name")
    db_path: str = Field(description="Database file path")
    healthy: bool = Field(description="Whether the database is healthy")
    status: Dict[str, Any] = Field(description="Database status information")
    tables: Dict[str, str] = Field(description="Database tables data (JSON strings)")


class DatabaseListResponse(BaseModel):
    """Response for listing databases"""
    databases: List[str] = Field(description="List of database file paths")


class DatabaseReadRequest(BaseModel):
    """Request for reading databases"""
    db_paths: List[str] = Field(description="List of database paths to read")


class DatabaseReadResponse(BaseModel):
    """Response for reading databases"""
    databases: List[DatabaseInfo] = Field(description="List of database information")


class CheckpointRequest(BaseModel):
    """Request for creating a checkpoint"""
    db_paths: List[str] = Field(description="List of database paths to include in checkpoint")


class CheckpointResponse(BaseModel):
    """Response for checkpoint operations"""
    message: str = Field(description="Operation result message")
    success: bool = Field(default=True, description="Whether the operation was successful")


class CheckpointListResponse(BaseModel):
    """Response for listing checkpoints"""
    checkpoints: List[str] = Field(description="List of checkpoint file paths")


class CheckpointData(BaseModel):
    """Data loaded from a checkpoint"""
    executors: str = Field(description="Executors data (JSON string)")
    orders: str = Field(description="Orders data (JSON string)")
    trade_fill: str = Field(description="Trade fill data (JSON string)")
    controllers: str = Field(description="Controllers data (JSON string)")


class CheckpointLoadRequest(BaseModel):
    """Request for loading a checkpoint"""
    checkpoint_path: str = Field(description="Path to the checkpoint file to load")