"""Resume screening automation package."""

from __future__ import annotations

import importlib
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

_LAZY_EXPORTS = {
	"FlowExecutionError": (".app", "FlowExecutionError"),
	"initialise_session": (".app", "initialise_session"),
	"process_user_message": (".app", "process_user_message"),
	"build_flow": (".main", "build_flow"),
	"ResumeAssistantFlow": (".main", "ResumeAssistantFlow"),
	"ChatSessionState": (".state", "ChatSessionState"),
	"KnowledgeSessionState": (".state", "KnowledgeSessionState"),
	"ResumeAssistantFlowState": (".state", "ResumeAssistantFlowState"),
	"bind_session_to_streamlit": (".state", "bind_session_to_streamlit"),
	"get_or_create_session": (".state", "get_or_create_session"),
	"persist_session": (".state", "persist_session"),
}


def __getattr__(name: str):
	module_info = _LAZY_EXPORTS.get(name)
	if not module_info:
		raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
	module_path, attr_name = module_info
	module = importlib.import_module(module_path, __name__)
	value = getattr(module, attr_name)
	globals()[name] = value
	return value


__all__ = sorted(_LAZY_EXPORTS.keys())
