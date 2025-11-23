from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router as api_router
from backend.core.config import settings
from resume_screening_rag_automation.storage_sync import knowledge_store_sync
import logging
import os
import sys
import asyncio
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


# Background task for R2 sync
async def background_r2_sync():
    """Background task that syncs to R2 every 30 seconds."""
    # Do first sync after 5 seconds to allow app to stabilize
    await asyncio.sleep(5)
    
    while True:
        try:
            if knowledge_store_sync._dirty:
                logger.info("🔄 Background R2 sync starting (changes detected)...")
                knowledge_store_sync.flush_if_needed()
                logger.info("✅ Background R2 sync complete.")
            else:
                logger.debug("⏭️  Background R2 sync skipped (no changes).")
            await asyncio.sleep(30)  # Wait 30 seconds before next check
        except Exception as e:
            logger.error(f"❌ Background R2 sync failed: {e}")
            await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Syncing knowledge store from remote...")
    try:
        knowledge_store_sync.ensure_local_copy()
        logger.info("Knowledge store synced.")
    except Exception as e:
        logger.error(f"Failed to sync knowledge store: {e}")
    
    # Start background R2 sync task
    sync_task = asyncio.create_task(background_r2_sync())
    logger.info("Background R2 sync task started.")
    
    yield
    
    # Shutdown
    logger.info("Cancelling background sync task...")
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    
    logger.info("Flushing knowledge store to remote...")
    knowledge_store_sync.flush()

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

@app.get("/")
def root():
    return {"message": "HireX Backend API", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
