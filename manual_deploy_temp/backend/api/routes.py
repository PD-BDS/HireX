from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from backend.services.storage_service import storage_service
from backend.services.chat_service import chat_service

router = APIRouter()

class ChatMessageRequest(BaseModel):
    session_id: Optional[str] = None
    message: str

class ChatMessageResponse(BaseModel):
    session_id: str
    messages: List[Dict[str, Any]]
    status: str
    error: Optional[str] = None

@router.post("/chat", response_model=ChatMessageResponse)
async def chat_endpoint(request: ChatMessageRequest):
    if not request.message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # If no session_id provided, one will be created by the service
    # But we need to pass something to get_session if we want a specific one
    # logic in service handles None -> new session
    
    print(f"DEBUG: Received chat request. Message: {request.message[:50]}")
    import asyncio
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, chat_service.process_message, request.session_id, request.message)
    print("DEBUG: Chat processing complete.")
    
    if result["status"] == "error":
        # We return 200 even on error to show the error message in UI gracefully, 
        # or we could raise 500. Let's return the error object.
        pass
        
    return result

@router.get("/sessions")
async def list_sessions():
    # Read from the actual index file
    from resume_screening_rag_automation.paths import CONVERSATION_INDEX_PATH
    import json
    
    if not CONVERSATION_INDEX_PATH.exists():
        return {"sessions": []}
        
    try:
        content = CONVERSATION_INDEX_PATH.read_text(encoding="utf-8")
        data = json.loads(content)
        # Sort by updated_at desc
        sessions = data.get("sessions", [])
        sessions.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        return {"sessions": sessions}
    except Exception:
        return {"sessions": []}

@router.post("/sessions")
async def create_session():
    return chat_service.create_session()

@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    state = chat_service.get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return state

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    success = chat_service.delete_session(session_id)
    return {"success": success}

class SessionConfigRequest(BaseModel):
    top_k: Optional[int] = None
    scoring_weights: Optional[Dict[str, float]] = None
    feature_weights: Optional[Dict[str, float]] = None

@router.put("/sessions/{session_id}/config")
async def update_session_config(session_id: str, config: SessionConfigRequest):
    return chat_service.update_session_config(
        session_id,
        top_k=config.top_k,
        scoring_weights=config.scoring_weights,
        feature_weights=config.feature_weights
    )

@router.get("/files")
async def list_files(prefix: str = ""):
    files = storage_service.list_files(prefix)
    return {"files": files}
