from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query

from utils.file_system import fs_util
from utils.hummingbot_database_reader import HummingbotDatabase, PerformanceDataSource
from hummingbot.strategy_v2.backtesting.backtesting_engine_base import BacktestingEngineBase

router = APIRouter(tags=["Archived Bots"], prefix="/archived-bots")


@router.get("/", response_model=List[str])
async def list_databases():
    """
    List all available database files in the system.
    
    Returns:
        List of database file paths
    """
    return fs_util.list_databases()


@router.get("/{db_path:path}/status")
async def get_database_status(db_path: str):
    """
    Get status information for a specific database.
    
    Args:
        db_path: Path to the database file
        
    Returns:
        Database status including table health
    """
    try:
        db = HummingbotDatabase(db_path)
        return {
            "db_path": db_path,
            "status": db.status,
            "healthy": db.status["general_status"]
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Database not found or error: {str(e)}")


@router.get("/{db_path:path}/summary")
async def get_database_summary(db_path: str):
    """
    Get a summary of database contents including basic statistics.
    
    Args:
        db_path: Full path to the database file
        
    Returns:
        Summary statistics of the database contents
    """
    try:
        db = HummingbotDatabase(db_path)
        
        # Get basic counts
        orders = db.get_orders()
        trades = db.get_trade_fills()
        executors = db.get_executors_data()
        
        return {
            "db_path": db_path,
            "total_orders": len(orders),
            "total_trades": len(trades),
            "total_executors": len(executors),
            "trading_pairs": orders["symbol"].unique().tolist() if len(orders) > 0 else [],
            "exchanges": orders["market"].unique().tolist() if len(orders) > 0 else [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing database: {str(e)}")


@router.get("/{db_path:path}/performance")
async def get_database_performance(db_path: str):
    """
    Get detailed performance analysis for a bot database.
    
    Args:
        db_path: Full path to the database file
        
    Returns:
        Detailed performance metrics including PnL, sharpe ratio, etc.
    """
    try:
        db = HummingbotDatabase(db_path)
        
        # Get executors data
        executors = db.get_executors_data()
        
        if len(executors) == 0:
            return {
                "db_path": db_path,
                "error": "No executors found in database",
                "results": {}
            }
        
        # Convert to performance data source
        executors_dict = executors.to_dict('records')
        data_source = PerformanceDataSource(executors_dict)
        
        # Calculate performance
        backtesting_engine = BacktestingEngineBase()
        executor_info_list = data_source.executor_info_list
        results = backtesting_engine.summarize_results(executor_info_list)
        
        # Clean up results
        results["sharpe_ratio"] = results["sharpe_ratio"] if results["sharpe_ratio"] is not None else 0
        
        return {
            "db_path": db_path,
            "results": results,
            "executor_count": len(executor_info_list)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating performance: {str(e)}")


@router.get("/{db_path:path}/trades")
async def get_database_trades(
    db_path: str,
    limit: int = Query(default=100, description="Limit number of trades returned"),
    offset: int = Query(default=0, description="Offset for pagination")
):
    """
    Get trade history from a database.
    
    Args:
        db_path: Full path to the database file
        limit: Maximum number of trades to return
        offset: Offset for pagination
        
    Returns:
        List of trades with pagination info
    """
    try:
        db = HummingbotDatabase(db_path)
        trades = db.get_trade_fills()
        
        # Apply pagination
        total_trades = len(trades)
        trades_page = trades.iloc[offset:offset + limit]
        
        return {
            "db_path": db_path,
            "trades": trades_page.to_dict('records'),
            "pagination": {
                "total": total_trades,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_trades
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching trades: {str(e)}")


@router.get("/{db_path:path}/orders")
async def get_database_orders(
    db_path: str,
    limit: int = Query(default=100, description="Limit number of orders returned"),
    offset: int = Query(default=0, description="Offset for pagination"),
    status: Optional[str] = Query(default=None, description="Filter by order status")
):
    """
    Get order history from a database.
    
    Args:
        db_path: Full path to the database file
        limit: Maximum number of orders to return
        offset: Offset for pagination
        status: Optional status filter
        
    Returns:
        List of orders with pagination info
    """
    try:
        db = HummingbotDatabase(db_path)
        orders = db.get_orders()
        
        # Apply status filter if provided
        if status:
            orders = orders[orders["last_status"] == status]
        
        # Apply pagination
        total_orders = len(orders)
        orders_page = orders.iloc[offset:offset + limit]
        
        return {
            "db_path": db_path,
            "orders": orders_page.to_dict('records'),
            "pagination": {
                "total": total_orders,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_orders
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")


@router.get("/{db_path:path}/executors")
async def get_database_executors(db_path: str):
    """
    Get executor data from a database.
    
    Args:
        db_path: Full path to the database file
        
    Returns:
        List of executors with their configurations and results
    """
    try:
        db = HummingbotDatabase(db_path)
        executors = db.get_executors_data()
        
        return {
            "db_path": db_path,
            "executors": executors.to_dict('records'),
            "total": len(executors)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching executors: {str(e)}")


@router.post("/read", response_model=List[Dict[str, Any]])
async def read_databases(db_paths: List[str]):
    """
    Read and extract basic information from multiple database files.
    
    Args:
        db_paths: List of database file paths to read
        
    Returns:
        List of database status information
    """
    results = []
    for db_path in db_paths:
        try:
            db = HummingbotDatabase(db_path)
            db_info = {
                "db_name": db.db_name,
                "db_path": db.db_path,
                "healthy": db.status["general_status"],
                "status": db.status,
            }
        except Exception as e:
            db_info = {
                "db_name": "",
                "db_path": db_path,
                "healthy": False,
                "error": str(e)
            }
        results.append(db_info)
    return results