"""Resume screening automation package."""

from __future__ import annotations

import os
import typing


# Ensure CrewAI persists memory and flow state under a stable project namespace.
os.environ.setdefault("CREWAI_STORAGE_DIR", "resume_screening_rag_automation")


def _ensure_typing_self() -> None:
	if hasattr(typing, "Self"):
		return
	try:  # Prefer typing_extensions if available
		from typing_extensions import Self as _Self  # type: ignore
	except Exception:  # pragma: no cover - fallback when typing_extensions missing
		class _Self:  # type: ignore
			pass

		_Self.__name__ = "Self"  # keep readable repr
	setattr(typing, "Self", _Self)


_ensure_typing_self()

from resume_screening_rag_automation.app import (
	FlowExecutionError,
	initialise_session,
	process_user_message,
)
from resume_screening_rag_automation.main import build_flow, ResumeAssistantFlow
from resume_screening_rag_automation.state import (
	ChatSessionState,
	KnowledgeSessionState,
	ResumeAssistantFlowState,
	bind_session_to_streamlit,
	get_or_create_session,
	persist_session,
)

__all__ = [
	"build_flow",
	"ResumeAssistantFlow",
	 "FlowExecutionError",
	"ChatSessionState",
	"KnowledgeSessionState",
	"ResumeAssistantFlowState",
	 "initialise_session",
	 "process_user_message",
	"bind_session_to_streamlit",
	"get_or_create_session",
	"persist_session",
]
