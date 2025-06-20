import json
import time

from typing import List, Dict, Any

import pandas as pd

from utils.etl_databases import HummingbotDatabase, ETLPerformance
from fastapi import APIRouter

from utils.file_system import fs_util

router = APIRouter(tags=["Databases"], prefix="/databases")


@router.get("/", response_model=List[str])
async def list_databases():
    """
    List all available database files in the system.
    
    Returns:
        List of database file paths
    """
    return fs_util.list_databases()


@router.post("/read", response_model=List[Dict[str, Any]])
async def read_databases(db_paths: List[str] = None):
    """
    Read and extract data from multiple database files.
    
    Args:
        db_paths: List of database file paths to read
        
    Returns:
        List of database contents with tables and status information
    """
    dbs = []
    for db_path in db_paths:
        db = HummingbotDatabase(db_path)
        try:
            db_content = {
                "db_name": db.db_name,
                "db_path": db.db_path,
                "healthy": db.status["general_status"],
                "status": db.status,
                "tables": {
                    "orders": json.dumps(db.get_orders().to_dict()),
                    "trade_fill": json.dumps(db.get_trade_fills().to_dict()),
                    "executors": json.dumps(db.get_executors_data().to_dict()),
                    "order_status": json.dumps(db.get_order_status().to_dict()),
                    "controllers": json.dumps(db.get_controllers_data().to_dict())
                }
            }
        except Exception as e:
            print(f"Error reading database {db_path}: {str(e)}")
            db_content = {
                "db_name": "",
                "db_path": db_path,
                "healthy": False,
                "status": db.status,
                "tables": {}
            }
        dbs.append(db_content)
    return dbs


@router.post("/checkpoint", response_model=Dict[str, Any])
async def create_checkpoint(db_paths: List[str]):
    """
    Create a checkpoint by consolidating data from multiple databases.
    
    Args:
        db_paths: List of database paths to include in checkpoint
        
    Returns:
        Dictionary with checkpoint creation status
    """
    try:
        dbs = await read_databases(db_paths)

        healthy_dbs = [db for db in dbs if db["healthy"]]

        table_names = ["trade_fill", "orders", "order_status", "executors", "controllers"]
        tables_dict = {name: pd.DataFrame() for name in table_names}

        for db in healthy_dbs:
            for table_name in table_names:
                new_data = pd.DataFrame(json.loads(db["tables"][table_name]))
                new_data["db_path"] = db["db_path"]
                new_data["db_name"] = db["db_name"]
                tables_dict[table_name] = pd.concat([tables_dict[table_name], new_data])

        etl = ETLPerformance(db_path=f"bots/data/checkpoint_{str(int(time.time()))}.sqlite")
        etl.create_tables()
        etl.insert_data(tables_dict)
        return {"message": "Checkpoint created successfully."}
    except Exception as e:
        return {"message": f"Error: {str(e)}"}


@router.get("/checkpoints", response_model=List[str])
async def list_checkpoints(full_path: bool):
    """
    List all available checkpoint files.
    
    Args:
        full_path: Whether to return full file paths or just filenames
        
    Returns:
        List of checkpoint file paths or names
    """
    return fs_util.list_checkpoints(full_path)


@router.post("/checkpoints/load")
async def load_checkpoint(checkpoint_path: str):
    """
    Load data from a checkpoint file.
    
    Args:
        checkpoint_path: Path to the checkpoint file to load
        
    Returns:
        Dictionary with checkpoint data including executors, orders, trades, and controllers
    """
    try:
        etl = ETLPerformance(checkpoint_path)
        executor = etl.load_executors()
        order = etl.load_orders()
        trade_fill = etl.load_trade_fill()
        controllers = etl.load_controllers()
        checkpoint_data = {
            "executors": json.dumps(executor.to_dict()),
            "orders": json.dumps(order.to_dict()),
            "trade_fill": json.dumps(trade_fill.to_dict()),
            "controllers": json.dumps(controllers.to_dict())
        }
        return checkpoint_data
    except Exception as e:
        return {"message": f"Error: {str(e)}"}