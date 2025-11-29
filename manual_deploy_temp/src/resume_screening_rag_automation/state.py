"""Session and knowledge state helpers for the resume screening assistant."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple
from uuid import uuid4

from crewai.flow.flow import FlowState
from pydantic import BaseModel, Field, ConfigDict

from resume_screening_rag_automation.core.constants import (
    DEFAULT_FEATURE_WEIGHTS,
    DEFAULT_SCORING_WEIGHTS,
)
from resume_screening_rag_automation.models import (
    CandidateAnalysisOutput,
    CandidateScreeningOutput,
    ChatMessage,
    ConversationPhase,
    DiscussionOutput,
    JobDescription,
    JobDescriptionOutput,
    QueryControls,
    QueryRoutingOutput,
    format_outstanding_questions_md,
)
from resume_screening_rag_automation.paths import (
    CONVERSATION_INDEX_PATH,
    CONVERSATION_SESSIONS_DIR,
    KNOWLEDGE_SESSIONS_DIR,
    SCREENING_INSIGHTS_DIR,
    STRUCTURED_RESUMES_PATH,
    ensure_data_directories,
)
from resume_screening_rag_automation.storage_sync import knowledge_store_sync

LOGGER = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def _default_session_id() -> str:
    return uuid4().hex


class KnowledgeSessionState(BaseModel):
    """Tracks knowledge artefacts and metadata for a chat session."""

    knowledge_session_id: str = Field(default_factory=_default_session_id)
    structured_resumes_path: str = Field(
        default_factory=lambda: str(STRUCTURED_RESUMES_PATH.resolve())
    )
    generated_insights_path: Optional[str] = None
    vector_collection: str = "resume_screening"
    last_vector_sync: Optional[str] = None
    active_candidate_ids: List[str] = Field(default_factory=list)


class ChatSessionState(BaseModel):
    """Conversation-specific state shared between the Flow, crews, and UI."""

    session_id: str = Field(default_factory=_default_session_id)
    knowledge_session_id: Optional[str] = None
    messages: List[ChatMessage] = Field(default_factory=list)
    job_snapshot: JobDescription = Field(default_factory=JobDescription)
    latest_job_output: Optional[JobDescriptionOutput] = None
    latest_screening_output: Optional[CandidateScreeningOutput] = None
    latest_analysis_output: Optional[CandidateAnalysisOutput] = None
    latest_discussion_output: Optional[DiscussionOutput] = None
    latest_routing: Optional[QueryRoutingOutput] = None
    query_controls: QueryControls = Field(default_factory=QueryControls)
    pending_phases: List[ConversationPhase] = Field(default_factory=list)
    last_completed_phase: Optional[ConversationPhase] = None
    top_k: int = 5
    scoring_weights: Dict[str, float] = Field(
        default_factory=lambda: DEFAULT_SCORING_WEIGHTS.copy()
    )
    feature_weights: Dict[str, float] = Field(
        default_factory=lambda: DEFAULT_FEATURE_WEIGHTS.copy()
    )
    last_user_message: Optional[str] = None
    last_updated_at: Optional[str] = None

    def requirement_questions_md(self) -> str:
        return format_outstanding_questions_md(self.job_snapshot.outstanding_questions)


class ResumeAssistantFlowState(FlowState):
    """Typed Flow state backing the CrewAI Flow orchestration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chat_state: ChatSessionState = Field(default_factory=ChatSessionState)
    knowledge_state: KnowledgeSessionState = Field(default_factory=KnowledgeSessionState)
    latest_user_message: str = ""
    routing_decision: Optional[QueryRoutingOutput] = None
    job_description_output: Optional[JobDescriptionOutput] = None
    screening_output: Optional[CandidateScreeningOutput] = None
    analysis_output: Optional[CandidateAnalysisOutput] = None
    discussion_output: Optional[DiscussionOutput] = None
    turn_responses: List[ChatMessage] = Field(default_factory=list)
    turn_finalised: bool = False
    errors: List[str] = Field(default_factory=list)
    execution_plan: List[ConversationPhase] = Field(default_factory=list)
    completed_phases: List[ConversationPhase] = Field(default_factory=list)


def _ensure_directories() -> None:
    ensure_data_directories()


def _session_path(session_id: str) -> Path:
    return CONVERSATION_SESSIONS_DIR / f"{session_id}.json"


def _knowledge_path(knowledge_session_id: str) -> Path:
    return KNOWLEDGE_SESSIONS_DIR / f"{knowledge_session_id}.json"


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("Invalid JSON payload at %s; ignoring", path)
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSON files persist ISO-8601 timestamps for cross-component compatibility.
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def get_or_create_session(
    *,
    session_id: Optional[str] = None,
    knowledge_session_id: Optional[str] = None,
) -> Tuple[ChatSessionState, KnowledgeSessionState]:
    """Load or initialise chat/knowledge state for a session."""

    _ensure_directories()

    chat_state: ChatSessionState
    knowledge_state: KnowledgeSessionState

    if session_id:
        existing = _read_json(_session_path(session_id))
        if existing:
            chat_state = ChatSessionState.model_validate(existing)
        else:
            chat_state = ChatSessionState(session_id=session_id)
    else:
        chat_state = ChatSessionState()
        session_id = chat_state.session_id

    legacy_knowledge_id = knowledge_session_id or chat_state.knowledge_session_id
    if legacy_knowledge_id and legacy_knowledge_id != session_id:
        LOGGER.info(
            "Aligning knowledge_session_id=%s with session_id=%s",
            legacy_knowledge_id,
            session_id,
        )

    resolved_knowledge_id = session_id
    knowledge_payload = {}
    if legacy_knowledge_id and legacy_knowledge_id != resolved_knowledge_id:
        knowledge_payload = _read_json(_knowledge_path(legacy_knowledge_id))
    if not knowledge_payload:
        knowledge_payload = _read_json(_knowledge_path(resolved_knowledge_id))
    if knowledge_payload:
        knowledge_state = KnowledgeSessionState.model_validate(knowledge_payload)
    else:
        knowledge_state = KnowledgeSessionState(knowledge_session_id=resolved_knowledge_id)

    knowledge_state.knowledge_session_id = resolved_knowledge_id
    knowledge_state.structured_resumes_path = str(STRUCTURED_RESUMES_PATH.resolve())
    knowledge_state.generated_insights_path = str(
        (SCREENING_INSIGHTS_DIR / f"{resolved_knowledge_id}.json").resolve()
    )
    chat_state.knowledge_session_id = resolved_knowledge_id

    return chat_state, knowledge_state


def persist_session(
    chat_state: ChatSessionState,
    knowledge_state: KnowledgeSessionState,
    *,
    touched_at: Optional[datetime] = None,
) -> None:
    """Persist session and knowledge state to disk with an updated index."""

    _ensure_directories()

    timestamp = touched_at or datetime.now(timezone.utc)
    timestamp_iso = timestamp.replace(microsecond=0).isoformat()

    chat_state.last_updated_at = timestamp_iso

    chat_payload = chat_state.model_dump(mode="json")
    knowledge_payload = knowledge_state.model_dump(mode="json")

    _write_json(_session_path(chat_state.session_id), chat_payload)
    _write_json(_knowledge_path(knowledge_state.knowledge_session_id), knowledge_payload)

    index_payload = _read_json(CONVERSATION_INDEX_PATH) or {"sessions": []}
    sessions: List[Dict[str, Any]] = index_payload.get("sessions", [])

    existing_entry = next(
        (entry for entry in sessions if entry.get("id") == chat_state.session_id),
        None,
    )

    label = _derive_label(chat_state.messages)
    last_message = chat_state.messages[-1].content_md if chat_state.messages else ""
    job_title = chat_state.job_snapshot.job_title or ""

    if existing_entry:
        existing_entry.update(
            {
                "label": label,
                "updated_at": timestamp_iso,
                "job_title": job_title,
                "last_message": last_message,
            }
        )
    else:
        sessions.append(
            {
                "id": chat_state.session_id,
                "label": label,
                "created_at": timestamp_iso,
                "updated_at": timestamp_iso,
                "job_title": job_title,
                "last_message": last_message,
            }
        )

    index_payload["sessions"] = sessions
    index_payload.setdefault("active_session", chat_state.session_id)
    _write_json(CONVERSATION_INDEX_PATH, index_payload)
    knowledge_store_sync.mark_dirty()
    knowledge_store_sync.flush_if_needed()


def _derive_label(messages: List[ChatMessage]) -> str:
    if not messages:
        return "Untitled session"
    first_user = next((msg for msg in messages if msg.role == "user" and msg.content_md), None)
    if not first_user:
        first_user = messages[0]
    content = first_user.content_md.strip().splitlines()[0]
    return content[:80] or "Untitled session"


def bind_session_to_streamlit(
    store: MutableMapping[str, Any],
    *,
    chat_state: ChatSessionState,
    knowledge_state: KnowledgeSessionState,
    prefix: str = "resume_assistant",
) -> None:
    """Store state snapshots in Streamlit session storage."""

    store[f"{prefix}_chat_state"] = chat_state
    store[f"{prefix}_knowledge_state"] = knowledge_state


__all__ = [
    "ChatSessionState",
    "KnowledgeSessionState",
    "ResumeAssistantFlowState",
    "bind_session_to_streamlit",
    "get_or_create_session",
    "persist_session",
]
