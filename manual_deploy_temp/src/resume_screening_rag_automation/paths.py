"""Centralised filesystem paths for persistent data and knowledge artefacts."""

from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

# Unified data root for all persisted knowledge artefacts and session state.
import os
DATA_ROOT = Path(os.getenv("KNOWLEDGE_STORE_PATH", PROJECT_ROOT / "knowledge_store")).resolve()

# Directory containing raw resume text files ingested by the pipeline.
RAW_RESUME_DIR = DATA_ROOT / "cv_txt"

# Canonical query manager scenario corpus.
QUERY_MANAGER_SCENARIO_DIR = DATA_ROOT / "query_manager"
QUERY_MANAGER_SCENARIO_FILE = QUERY_MANAGER_SCENARIO_DIR / "scenarios.jsonl"

# Conversation transcripts and indices per recruiter session.
CONVERSATIONS_DIR = DATA_ROOT / "conversations"
CONVERSATION_SESSIONS_DIR = CONVERSATIONS_DIR / "sessions"
CONVERSATION_INDEX_PATH = CONVERSATIONS_DIR / "sessions_index.json"

# Session-specific knowledge state snapshots.
KNOWLEDGE_SESSIONS_DIR = DATA_ROOT / "knowledge_sessions"

# Generated screening insights scoped per session.
SCREENING_INSIGHTS_DIR = DATA_ROOT / "screening_insights"

# Canonical structured resumes knowledge artefact.
STRUCTURED_RESUMES_PATH = DATA_ROOT / "structured_resumes.json"

# Persistent Chroma vector store used for resume embeddings.
CHROMA_VECTOR_DIR = DATA_ROOT / "chroma_vectorstore"


def ensure_data_directories() -> None:
    """Create the standard directory layout if it does not already exist."""

    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATION_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENING_INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    QUERY_MANAGER_SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    STRUCTURED_RESUMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_RESUME_DIR.mkdir(parents=True, exist_ok=True)

    legacy_structured = PACKAGE_ROOT / "knowledge" / "structured_resumes.json"
    if not STRUCTURED_RESUMES_PATH.exists() and legacy_structured.exists():
        STRUCTURED_RESUMES_PATH.write_text(
            legacy_structured.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    legacy_scenarios = (
        PROJECT_ROOT.parent
        / "knowledge_store"
        / "query_manager"
        / "scenarios.jsonl"
    )
    if not QUERY_MANAGER_SCENARIO_FILE.exists() and legacy_scenarios.exists():
        QUERY_MANAGER_SCENARIO_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUERY_MANAGER_SCENARIO_FILE.write_text(
            legacy_scenarios.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    placeholder = SCREENING_INSIGHTS_DIR / "_placeholder.json"
    if not placeholder.exists():
        placeholder.write_text("{\n  \"records\": []\n}\n", encoding="utf-8")


__all__ = [
    "PACKAGE_ROOT",
    "PROJECT_ROOT",
    "DATA_ROOT",
    "RAW_RESUME_DIR",
    "CONVERSATIONS_DIR",
    "CONVERSATION_SESSIONS_DIR",
    "CONVERSATION_INDEX_PATH",
    "KNOWLEDGE_SESSIONS_DIR",
    "SCREENING_INSIGHTS_DIR",
    "STRUCTURED_RESUMES_PATH",
    "CHROMA_VECTOR_DIR",
    "QUERY_MANAGER_SCENARIO_DIR",
    "QUERY_MANAGER_SCENARIO_FILE",
    "ensure_data_directories",
]
