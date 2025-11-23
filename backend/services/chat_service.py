import logging
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


from resume_screening_rag_automation.state import (
    ChatSessionState,
    KnowledgeSessionState,
    ResumeAssistantFlowState,
    get_or_create_session,
    persist_session,
)
from resume_screening_rag_automation.main import build_flow
from resume_screening_rag_automation.session_memory import create_session_memory_bundle
from resume_screening_rag_automation.models import ChatMessage
from resume_screening_rag_automation.storage_sync import knowledge_store_sync
from backend.core.config import settings

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self):
        pass

    def get_session(self, session_id: Optional[str] = None) -> Tuple[ChatSessionState, KnowledgeSessionState]:
        """Get or create a session."""
        return get_or_create_session(session_id=session_id)

    def process_message(
        self,
        session_id: str,
        user_message: str
    ) -> Dict[str, Any]:
        """Process a user message through the CrewAI flow."""
        
        logger.info(f"Processing message for session: {session_id}")
        logger.info(f"User message: {user_message[:100]}...")
        
        # Load session state
        chat_state, knowledge_state = self.get_session(session_id)
        logger.info(f"Loaded session state. Session ID: {chat_state.session_id}")
        
        # Ensure we have a valid session_id (in case input was None)
        session_id = chat_state.session_id
        
        # Setup memory
        # TODO: Handle concurrency if multiple requests hit this at once
        memory_bundle = create_session_memory_bundle(session_id)
        memory_bundle.activate()
        logger.info(f"Memory bundle activated for session: {session_id}")
        
        # Build flow
        flow = build_flow(
            chat_state=chat_state,
            knowledge_state=knowledge_state,
            memory_bundle=memory_bundle,
        )
        flow.state.latest_user_message = user_message
        logger.info("Flow built, starting crew kickoff...")

        try:
            # Run flow
            logger.info("=" * 80)
            logger.info("CREW EXECUTION STARTING")
            logger.info("=" * 80)
            responses = flow.kickoff()
            logger.info("=" * 80)
            logger.info("CREW EXECUTION COMPLETED")
            logger.info("=" * 80)
            
            logger.info(f"Crew returned {len(responses) if responses else 0} responses")
            
            # Persist state
            logger.info("Persisting session state...")
            persist_session(flow.state.chat_state, flow.state.knowledge_state)
            logger.info(f"Session persisted. Message count: {len(flow.state.chat_state.messages)}")
            
            # Mark for background R2 sync
            knowledge_store_sync.mark_dirty()
            
            # Return response
            messages = responses or list(flow.state.turn_responses)
            
            # Format for API response
            formatted_messages = []
            for msg in messages:
                formatted_messages.append({
                    "role": msg.role,
                    "content": msg.content_md,
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None
                })
                
            logger.info(f"Returning {len(formatted_messages)} formatted messages")
            return {
                "session_id": flow.state.chat_state.session_id,
                "messages": formatted_messages,
                "status": "success"
            }
            
        except Exception as e:
            logger.exception("Error processing message")
            # Persist even on error to save partial state if needed
            persist_session(flow.state.chat_state, flow.state.knowledge_state)
            return {
                "session_id": session_id,
                "messages": [],
                "status": "error",
                "error": str(e)
            }

    def create_session(self) -> Dict[str, Any]:
        """Create a new session."""
        chat_state, knowledge_state = get_or_create_session()
        persist_session(chat_state, knowledge_state)
        knowledge_store_sync.mark_dirty()
        return {
            "session_id": chat_state.session_id,
            "created_at": chat_state.last_updated_at
        }

    def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get full session state."""
        try:
            chat_state, _ = self.get_session(session_id)
            return chat_state.model_dump(mode="json")
        except Exception:
            return None

    def update_session_config(
        self, 
        session_id: str, 
        top_k: Optional[int] = None,
        scoring_weights: Optional[Dict[str, float]] = None,
        feature_weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """Update session configuration."""
        chat_state, knowledge_state = self.get_session(session_id)
        
        if top_k is not None:
            chat_state.top_k = top_k
        if scoring_weights is not None:
            chat_state.scoring_weights = scoring_weights
        if feature_weights is not None:
            chat_state.feature_weights = feature_weights
            
        persist_session(chat_state, knowledge_state)
        knowledge_store_sync.mark_dirty()
        
        return chat_state.model_dump(mode="json")

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        # This logic mimics _delete_session in app.py
        from resume_screening_rag_automation.paths import (
            CONVERSATION_SESSIONS_DIR,
            KNOWLEDGE_SESSIONS_DIR,
            SCREENING_INSIGHTS_DIR,
            CONVERSATION_INDEX_PATH
        )
        from resume_screening_rag_automation.session_memory import delete_session_memory_storage
        
        # Delete files
        for path in (
            CONVERSATION_SESSIONS_DIR / f"{session_id}.json",
            KNOWLEDGE_SESSIONS_DIR / f"{session_id}.json",
            SCREENING_INSIGHTS_DIR / f"{session_id}.json",
        ):
            try:
                path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue

        # Update manifest
        # We need to read/write manifest manually here as it's not exposed nicely in state.py
        # But let's try to reuse the logic if possible or reimplement simply
        try:
            import json
            if CONVERSATION_INDEX_PATH.exists():
                payload = json.loads(CONVERSATION_INDEX_PATH.read_text(encoding="utf-8"))
                sessions = payload.get("sessions", [])
                remaining = [s for s in sessions if s.get("id") != session_id]
                payload["sessions"] = remaining
                if payload.get("active_session") == session_id:
                    payload["active_session"] = remaining[0].get("id") if remaining else None
                
                CONVERSATION_INDEX_PATH.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
        except Exception as e:
            logger.error(f"Failed to update manifest: {e}")

        delete_session_memory_storage(session_id)
        knowledge_store_sync.mark_dirty()
        return True

chat_service = ChatService()
