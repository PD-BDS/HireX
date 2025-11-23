from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router as api_router
from backend.core.config import settings
from resume_screening_rag_automation.storage_sync import knowledge_store_sync
import logging
import os
import sys
from contextlib import asynccontextmanager


# Enable CrewAI verbose logging
os.environ["CREW_VERBOSE"] = "1"
os.environ["CREWAI_LOG_LEVEL"] = "DEBUG"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Ensure CrewAI and app logs are visible
logging.getLogger("crewai").setLevel(logging.DEBUG)
logging.getLogger("resume_screening_rag_automation").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Syncing knowledge store from remote...")
    try:
        knowledge_store_sync.ensure_local_copy()
        logger.info("Knowledge store synced.")
    except Exception as e:
        logger.error(f"Failed to sync knowledge store: {e}")
    yield
    # Shutdown
    logger.info("Flushing knowledge store to remote...")
    knowledge_store_sync.flush()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
