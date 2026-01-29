from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union
import pandas as pd
import uvicorn
from datetime import datetime, timezone
import logging
import traceback
import inspect
import httpx
import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# --- New Imports for Scheduling and Database ---
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from supabase import create_client, Client

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
# Uses the shared URL from your frontend config
SUPABASE_URL = os.getenv("VITE_SUPABASE_URL") 
SUMTYME_KEY = os.getenv("SUMTYME_API_KEY")
# Uses the SECURE key (Recommended: SUPABASE_SERVICE_ROLE_KEY)
# Falls back to VITE_ keys if necessary, but warns about it.
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY") or 
    os.getenv("VITE_SUPABASE_ROLE_KEY") or 
    os.getenv("VITE_SUPABASE_ANON_KEY")
)

if not SUPABASE_URL:
    print("⚠️ WARNING: VITE_SUPABASE_URL not found in environment variables.")

if not SUPABASE_KEY:
    print("⚠️ WARNING: SUPABASE_SERVICE_ROLE_KEY not found. Database updates will fail.")

# Defined intervals
ALL_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"]

# Symbols and intervals to auto-forecast
# MODIFIED: Restricted to only BTCUSDT to match database schema constraints
WATCHLIST = [
    {"symbol": "BTCUSDT", "intervals": ALL_INTERVALS},
]

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sumtyme_server")

# --- Import Sumtyme ---
try:
    from sumtyme import EIPClient
    SUMTYME_AVAILABLE = True
    logger.info("Sumtyme package loaded successfully")
except ImportError as e:
    logger.warning(f"Sumtyme package not found: {e}")
    SUMTYME_AVAILABLE = False

# --- Initialize Clients ---
eip_client = None
supabase: Optional[Client] = None
scheduler = AsyncIOScheduler()

def initialize_clients():
    global eip_client, supabase
    
    # 1. Sumtyme Client
    if SUMTYME_AVAILABLE and eip_client is None:
        try:
            # Initialize client with API key
            eip_client = EIPClient(apikey=SUMTYME_KEY)
            logger.info("✅ EIP Client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize EIP Client: {e}")

    # 2. Supabase Client
    if supabase is None:
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("✅ Supabase Client initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Supabase: {e}")
        else:
            logger.warning("⚠️ Supabase credentials missing. Database saves will be skipped.")

# --- Helper: Robust Binance Fetcher (Server-Side Pagination) ---

async def fetch_binance_data(
    symbol: str, 
    interval: str, 
    limit: Optional[int] = None, 
    start_time: Optional[int] = None, 
    end_time: Optional[int] = None
) -> List[Any]:
    """
    Fetches kline data from Binance. 
    Handles pagination for large limits (>1000) or date ranges.
    """
    base_url = "https://api.binance.com/api/v3/klines"
    max_per_request = 1000
    all_data = []

    async with httpx.AsyncClient() as client:
        
        # MODE A: Date Range (Forward Fetch)
        if start_time is not None and end_time is not None:
            logger.info(f"🔄 Fetching range for {symbol} {interval}: {start_time} to {end_time}")
            current_start = start_time
            
            while current_start < end_time:
                params = {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": current_start,
                    "endTime": end_time,
                    "limit": max_per_request
                }
                
                try:
                    response = await client.get(base_url, params=params, timeout=10.0)
                    response.raise_for_status()
                    data = response.json()
                    
                    if not data:
                        break
                        
                    all_data.extend(data)
                    
                    # Setup next batch: start from last candle close time + 1ms
                    last_close_time = data[-1][6]
                    current_start = last_close_time + 1
                    
                    if len(data) < max_per_request:
                        break # No more data available
                    
                    await asyncio.sleep(0.05) # Gentle rate limiting
                    
                except Exception as e:
                    logger.error(f"Error fetching range batch: {e}")
                    raise HTTPException(status_code=502, detail=f"Binance API error: {e}")

        # MODE B: Limit / Recent History (Backward Fetch)
        else:
            req_limit = limit if limit else 500
            logger.info(f"🔄 Fetching last {req_limit} candles for {symbol} {interval}")
            
            remaining = req_limit
            current_end = end_time # Can be None (defaults to Now)
            
            while remaining > 0:
                batch_size = min(remaining, max_per_request)
                params = {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": batch_size
                }
                if current_end:
                    params["endTime"] = current_end
                
                try:
                    response = await client.get(base_url, params=params, timeout=10.0)
                    response.raise_for_status()
                    data = response.json()
                    
                    if not data:
                        break
                    
                    # Prepend data (since we are fetching backwards)
                    all_data = data + all_data
                    
                    # Setup next batch: end at first candle open time - 1ms
                    first_open_time = data[0][0]
                    current_end = first_open_time - 1
                    
                    remaining -= len(data)
                    
                    if len(data) < batch_size:
                        break # No more history available
                        
                    await asyncio.sleep(0.05)
                    
                except Exception as e:
                    logger.error(f"Error fetching limit batch: {e}")
                    raise HTTPException(status_code=502, detail=f"Binance API error: {e}")

    return all_data

# --- Core Task: Run Forecast & Save ---
async def run_prediction_task(symbol: str, interval: str):
    """
    Background task: Fetch data -> Forecast -> Save to DB
    """
    task_id = f"{symbol}-{interval}"
    logger.info(f"🚀 Starting scheduled prediction for {task_id}")
    
    if not SUMTYME_AVAILABLE or not eip_client:
        logger.error("Sumtyme client not available, skipping task.")
        return

    try:
        # 1. Fetch Data (uses the new robust fetcher)
        # We need ~5000 candles for the model
        raw_data = await fetch_binance_data(symbol, interval, limit=5001)
        
        # Convert to DataFrame
        df = pd.DataFrame(raw_data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
        df['datetime'] = pd.to_datetime(df['open_time'], unit='ms').dt.strftime('%Y-%m-%d %H:%M:%S')
        df_model = df[['datetime', 'open', 'high', 'low', 'close']]
        
        # 2. Prepare Data for Sumtyme API
        unit_char = interval[-1]
        val = int(interval[:-1])
        
        final_unit = 'minutes'
        final_val = val
        
        if unit_char == 'm':
            final_unit = 'minutes'
        elif unit_char == 'h':
            final_unit = 'minutes'
            final_val = val * 60
        elif unit_char == 'd':
            final_unit = 'days'
            
        final_mode = 'proactive'

        result = eip_client.ohlc_forecast(
            data_input=df_model,
            interval=final_val,
            interval_unit=final_unit,
            reasoning_mode=final_mode
        )
        
        # 3. Save to Supabase
        if isinstance(result, dict) and len(result) == 1:
            timestamp_str, causal_chain = next(iter(result.items()))
            causal_chain = int(causal_chain)
            
            logger.info(f"✅ Forecast result for {task_id}: {causal_chain} at {timestamp_str}")
            
            if supabase:
                # Find the open price for the prediction timestamp
                match = df[df['datetime'] == timestamp_str]
                open_price = None
                if not match.empty:
                    open_price = float(match.iloc[0]['open'])

                payload = {
                    "timeframe": interval,
                    "datetime": timestamp_str,
                    "value": causal_chain,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "open_price": open_price,
                    "ticker": symbol
                }
                
                # Using upsert based on composite key constraint (timeframe, datetime, ticker)
                # Note: Ensure your DB schema has this unique constraint
                res = supabase.table("predictions").upsert(payload, on_conflict="timeframe,datetime,ticker").execute()
                logger.info(f"💾 Saved to DB: {res.data}")
            else:
                logger.warning("Supabase not configured, skipping save.")
                
    except Exception as e:
        logger.error(f"❌ Prediction task failed for {task_id}: {e}")
        logger.error(traceback.format_exc())

# --- Lifecycle Manager (Replaces Deprecated on_event) ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Initializing services...")
    initialize_clients()
    
    # Schedule tasks
    if not scheduler.running:
        logger.info("Scheduling background tasks...")
        
        for item in WATCHLIST:
            sym = item["symbol"]
            for interval in item["intervals"]:
                # Logic to determine cron schedule based on interval string
                cron_args = {}
                
                if interval.endswith('m'):
                    minutes = int(interval[:-1])
                    cron_args = {"minute": f"*/{minutes}"}
                elif interval.endswith('h'):
                    hours = int(interval[:-1])
                    cron_args = {"minute": "2", "hour": f"*/{hours}"}
                elif interval.endswith('d'):
                    cron_args = {"minute": "5", "hour": "0"}
                
                if cron_args:
                    scheduler.add_job(
                        run_prediction_task, 
                        CronTrigger(**cron_args), 
                        args=[sym, interval],
                        id=f"{sym}_{interval}",
                        replace_existing=True
                    )
                    logger.info(f"Scheduled {sym} {interval} with args {cron_args}")
        
        scheduler.start()
        logger.info("Scheduler started.")
    
    yield
    
    # Shutdown logic
    logger.info("Shutting down scheduler...")
    scheduler.shutdown()

# --- FastAPI App Definition ---

app = FastAPI(
    title="Sumtyme API Wrapper & Scheduler", 
    version="2.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan  # Use the new lifespan handler
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routes ---

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy", 
        "scheduler_running": scheduler.running,
        "supabase_connected": supabase is not None,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/binance/klines")
async def get_binance_klines(
    symbol: str, 
    interval: str, 
    limit: Optional[int] = 500, 
    startTime: Optional[int] = None, 
    endTime: Optional[int] = None
):
    """
    Smart endpoint for frontend charts.
    Handles large datasets and date ranges on the server side.
    """
    try:
        data = await fetch_binance_data(symbol, interval, limit, startTime, endTime)
        return data
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Internal error in get_binance_klines: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/trigger-forecast")
async def trigger_manual_forecast(symbol: str, interval: str):
    """Manually trigger a background forecast (for testing)"""
    asyncio.create_task(run_prediction_task(symbol, interval))
    return {"status": "Task started", "symbol": symbol, "interval": interval}

# --- New Helper: Merge DB Predictions with Binance Prices ---

async def get_predictions_with_prices(symbol: str, interval: str, limit: int = 100):
    """
    Fetches predictions from Supabase and merges them with Open prices from Binance.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database connection not available")

    # 1. Fetch recent predictions from Supabase
    # We order by datetime desc to get the latest ones
    try:
        response = supabase.table("predictions")\
            .select("*")\
            .eq("timeframe", interval)\
            .eq("ticker", symbol)\
            .order("datetime", desc=True)\
            .limit(limit)\
            .execute()
        
        db_predictions = response.data
        if not db_predictions:
            return []
            
        # Reverse to chronological order (Oldest -> Newest) for processing
        db_predictions.reverse()
        
    except Exception as e:
        logger.error(f"Supabase fetch error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # 2. Determine Time Range for Binance Data
    # Parse the first and last timestamps from the DB records
    # DB format example: "2024-01-01 12:00:00"
    try:
        first_time_str = db_predictions[0]['datetime']
        last_time_str = db_predictions[-1]['datetime']
        
        # Convert to milliseconds for Binance API
        fmt = "%Y-%m-%d %H:%M:%S"
        start_ts = int(datetime.strptime(first_time_str, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        end_ts = int(datetime.strptime(last_time_str, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        
        # Add a buffer to end_ts to ensure we cover the last candle
        # (Binance fetches by open time)
        end_ts += 60000 * 60 * 24 # Add adequate buffer or handle logic in fetcher
        
    except ValueError as e:
        logger.error(f"Date parsing error: {e}")
        # Fallback: Just return DB data without prices if parsing fails
        return db_predictions

    # 3. Identify missing prices and fetch range if needed
    missing_prices = any(p.get('open_price') is None for p in db_predictions)
    
    if missing_prices:
        logger.info(f"Filling missing prices for {symbol} {interval}...")
        # 3a. Fetch Binance Data (Open Prices)
        klines = await fetch_binance_data(symbol, interval, start_time=start_ts, end_time=end_ts)
        
        # 3b. Create a lookup dictionary: { timestamp_ms: open_price }
        price_map = {item[0]: float(item[1]) for item in klines}

        # 3c. Merge Data
        for pred in db_predictions:
            if pred.get('open_price') is None:
                try:
                    p_ts = int(datetime.strptime(pred['datetime'], fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
                    if p_ts in price_map:
                        pred['open_price'] = price_map[p_ts]
                except Exception:
                    pass
    
    return db_predictions

# --- New Endpoint ---

@app.get("/api/predictions/with-price")
async def get_enriched_predictions(
    symbol: str = "BTCUSDT",
    interval: str = Query(..., regex="^(1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d)$"),
    limit: int = 5000
):
    """
    Returns predictions enriched with the Open price from Binance.
    Useful for plotting historical indicators on the chart.
    """
    data = await get_predictions_with_prices(symbol, interval, limit)
    return {
        "symbol": symbol,
        "interval": interval,
        "count": len(data),
        "data": data
    }
    
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
