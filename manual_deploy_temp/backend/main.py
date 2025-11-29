from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.api.routes import router as api_router
from backend.core.config import settings
from resume_screening_rag_automation.storage_sync import knowledge_store_sync
import logging
import os
import sys
import asyncio
import concurrent.futures
from contextlib import asynccontextmanager


# Enable CrewAI verbose logging
os.environ["CREW_VERBOSE"] = "1"
os.environ["CREWAI_LOG_LEVEL"] = "DEBUG"
os.environ["PYTHONUNBUFFERED"] = "1"  # Force unbuffered output

# Configure logging with explicit flush
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True  # Override any existing config
)
logger = logging.getLogger(__name__)

# Ensure CrewAI and app logs are visible
logging.getLogger("crewai").setLevel(logging.DEBUG)
logging.getLogger("resume_screening_rag_automation").setLevel(logging.DEBUG)

# Force flush after every log
for handler in logging.root.handlers:
    handler.flush = lambda: sys.stdout.flush()


# Thread pool for R2 operations
executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="r2-sync")

# Background task for R2 sync
async def background_r2_sync():
    """Background task that syncs to R2 every 30 seconds."""
    logger.info("⏰ Background sync task starting in 5 seconds...")
    await asyncio.sleep(5)
    logger.info("⏰ Background sync task now active, will run every 30 seconds")
    
    while True:
        try:
            # Run sync in thread pool to avoid blocking
            logger.info("🔍 Checking for changes to sync...")
            start_time = asyncio.get_event_loop().time()
            
            try:
                # Run sync in thread pool (non-blocking)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    executor,
                    knowledge_store_sync.flush_if_needed
                )
                
                elapsed = asyncio.get_event_loop().time() - start_time
                logger.info(f"✅ Sync check complete ({elapsed:.2f}s)")
                
            except Exception as sync_error:
                elapsed = asyncio.get_event_loop().time() - start_time
                logger.error(f"❌ Sync failed after {elapsed:.2f}s: {sync_error}", exc_info=True)
            
            await asyncio.sleep(30)
            
        except asyncio.CancelledError:
            logger.info("🛑 Background sync task cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ Background sync loop error: {e}", exc_info=True)
            await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("=" * 60)
    logger.info("🚀 HireX Backend Starting...")
    logger.info("=" * 60)
    
    # Check R2 configuration
    r2_configured = all([
        os.getenv("R2_ACCESS_KEY_ID"),
        os.getenv("R2_SECRET_ACCESS_KEY"),
        os.getenv("R2_BUCKET_NAME"),
        os.getenv("R2_ENDPOINT_URL")
    ])
    
    # Ensure data directories exist
    from resume_screening_rag_automation.paths import ensure_data_directories
    ensure_data_directories()
    
    if r2_configured:
        logger.info("✅ R2 configuration detected - enabling remote sync")
        try:
            logger.info("📥 Syncing knowledge store from R2...")
            # Run initial sync in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                executor,
                knowledge_store_sync.ensure_local_copy
            )
            logger.info("✅ Knowledge store synced from R2.")
        except Exception as e:
            logger.error(f"❌ Failed to sync from R2: {e}", exc_info=True)
            logger.warning("⚠️  Continuing with local data only")
    elif os.getenv("KNOWLEDGE_STORE_PATH"):
        logger.info(f"✅ Azure Storage Mount detected at: {os.getenv('KNOWLEDGE_STORE_PATH')}")
        logger.info("💾 Data WILL persist to Azure Files.")
    else:
        logger.warning("⚠️  R2 not configured AND no external storage mount detected")
        logger.warning("⚠️  Data will NOT persist across restarts (ephemeral mode)!")
    
    # Start background R2 sync task only if R2 is configured
    sync_task = None
    if r2_configured:
        sync_task = asyncio.create_task(background_r2_sync())
        logger.info("🔄 Background R2 sync task started.")
    else:
        logger.warning("⏭️  Background R2 sync disabled (not configured)")
    
    logger.info("=" * 60)
    logger.info("✅ HireX Backend Ready!")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("=" * 60)
    logger.info("🛑 HireX Backend Shutting Down...")
    logger.info("=" * 60)
    
    if sync_task:
        logger.info("Cancelling background sync task...")
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
    
    if r2_configured:
        logger.info("📤 Final flush to R2...")
        try:
            # Run final flush in thread pool with timeout
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(executor, knowledge_store_sync.flush),
                timeout=30.0
            )
            logger.info("✅ Final R2 sync complete.")
        except asyncio.TimeoutError:
            logger.error("❌ Final R2 sync timed out after 30s")
        except Exception as e:
            logger.error(f"❌ Final R2 sync failed: {e}")
    
    # Shutdown thread pool
    executor.shutdown(wait=True, cancel_futures=True)
    
    logger.info("=" * 60)
    logger.info("👋 Goodbye!")
    logger.info("=" * 60)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Set all CORS enabled origins
cors_origins = settings.BACKEND_CORS_ORIGINS if settings.BACKEND_CORS_ORIGINS else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

# Mount static files for frontend
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
