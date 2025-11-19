"""Resume screening assistant application utilities and Streamlit UI."""

from __future__ import annotations

import json
import os
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import streamlit as st

# Ensure absolute imports work even when the project is not installed as a package.
SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
	sys.path.insert(0, str(SRC_ROOT))

SRC_PACKAGE_ROOT = SRC_ROOT / "src"
if SRC_PACKAGE_ROOT.exists() and str(SRC_PACKAGE_ROOT) not in sys.path:
	sys.path.insert(0, str(SRC_PACKAGE_ROOT))

from resume_screening_rag_automation.core.constants import (
	DEFAULT_FEATURE_WEIGHTS,
	DEFAULT_SCORING_WEIGHTS,
	JOB_FIELD_LABELS,
)
from resume_screening_rag_automation.main import build_flow
from resume_screening_rag_automation.models import (
	ChatMessage,
	JobDescription,
	normalise_feature_weights,
	normalise_scoring_weights,
)
from resume_screening_rag_automation.paths import (
	CONVERSATION_INDEX_PATH,
	CONVERSATION_SESSIONS_DIR,
	KNOWLEDGE_SESSIONS_DIR,
	SCREENING_INSIGHTS_DIR,
	ensure_data_directories,
)
from resume_screening_rag_automation.services.ingestion import bootstrap_resume_pipeline
from resume_screening_rag_automation.state import (
	ChatSessionState,
	KnowledgeSessionState,
	ResumeAssistantFlowState,
	bind_session_to_streamlit,
	get_or_create_session,
	persist_session,
)
from resume_screening_rag_automation.session_memory import (
	SessionMemoryBundle,
	create_session_memory_bundle,
	delete_session_memory_storage,
)
from resume_screening_rag_automation.storage_sync import knowledge_store_sync


def _apply_streamlit_secrets() -> None:
	try:
		secrets = st.secrets
	except Exception:
		return

	def _as_dict(candidate):
		if candidate is None:
			return {}
		if isinstance(candidate, dict):
			return candidate
		try:
			return dict(candidate)
		except Exception:
			return {}

	sections = [_as_dict(secrets)]
	for key in ("general", "remote_storage", "app"):
		section = _as_dict(secrets.get(key))
		if section:
			sections.append(section)

	for section in sections:
		for key, value in section.items():
			if isinstance(value, (str, int, float, bool)) and key:
				os.environ.setdefault(str(key), str(value))


_apply_streamlit_secrets()

LOGGER = logging.getLogger(__name__)

SESSION_STATE_CHAT_KEY = "resume_chat_state"
SESSION_STATE_KNOWLEDGE_KEY = "resume_knowledge_state"
SESSION_STATE_ACTIVE_ID_KEY = "resume_active_session_id"
SESSION_STATE_MANIFEST_KEY = "resume_session_manifest"
SESSION_STATE_LAST_ERRORS_KEY = "resume_last_flow_errors"
SESSION_STATE_INGESTION_KEY = "resume_ingestion_state"
SESSION_STATE_MEMORY_KEY = "resume_memory_bundles"
SESSION_STATE_ACTIVE_MEMORY_KEY = "resume_active_memory_bundle"
USE_MEM0_MEMORY = os.getenv("RESUME_ASSISTANT_USE_MEM0", "").strip().lower() in {"1", "true", "yes"}


class FlowExecutionError(RuntimeError):
	"""Raised when the underlying CrewAI flow fails to complete."""

	def __init__(self, message: str, *, state: ResumeAssistantFlowState) -> None:
		super().__init__(message)
		self.state = state


def initialise_session(
	*,
	session_id: Optional[str] = None,
	knowledge_session_id: Optional[str] = None,
) -> Tuple[ChatSessionState, KnowledgeSessionState]:
	"""Return chat and knowledge state, creating new sessions when needed."""

	return get_or_create_session(
		session_id=session_id,
		knowledge_session_id=knowledge_session_id,
	)


def process_user_message(
	user_input: str,
	*,
	chat_state: ChatSessionState,
	knowledge_state: KnowledgeSessionState,
	persist: bool = True,
) -> Tuple[List[ChatMessage], ChatSessionState, KnowledgeSessionState, ResumeAssistantFlowState]:
	"""Run a recruiter turn through the Flow and persist updated session state."""

	memory_bundle = _ensure_session_memory_bundle(chat_state.session_id)
	flow = build_flow(
		chat_state=chat_state,
		knowledge_state=knowledge_state,
		memory_bundle=memory_bundle,
	)
	flow.state.latest_user_message = user_input

	try:
		responses = flow.kickoff()
	except Exception as exc:  # pragma: no cover - flow errors surface to caller
		if persist:
			persist_session(flow.state.chat_state, flow.state.knowledge_state)
		raise FlowExecutionError(str(exc), state=flow.state) from exc

	updated_chat_state = flow.state.chat_state
	updated_knowledge_state = flow.state.knowledge_state

	if persist:
		persist_session(updated_chat_state, updated_knowledge_state)

	messages = responses or list(flow.state.turn_responses)
	return messages, updated_chat_state, updated_knowledge_state, flow.state


def _load_session_manifest() -> Dict[str, any]:
	ensure_data_directories()
	if not CONVERSATION_INDEX_PATH.exists():
		return {"sessions": []}
	try:
		payload = json.loads(CONVERSATION_INDEX_PATH.read_text(encoding="utf-8"))
	except json.JSONDecodeError:
		LOGGER.warning("Invalid conversation index at %s; resetting manifest", CONVERSATION_INDEX_PATH)
		return {"sessions": []}
	if not isinstance(payload, dict):
		return {"sessions": []}
	payload.setdefault("sessions", [])
	return payload


def _save_session_manifest(manifest: Dict[str, any]) -> None:
	manifest = dict(manifest)
	manifest.setdefault("sessions", [])
	CONVERSATION_INDEX_PATH.write_text(
		json.dumps(manifest, indent=2, ensure_ascii=False),
		encoding="utf-8",
	)
	knowledge_store_sync.mark_dirty()
	knowledge_store_sync.flush_if_needed()


def _memory_bundle_store() -> Dict[str, SessionMemoryBundle]:
	store = st.session_state.get(SESSION_STATE_MEMORY_KEY)
	if not isinstance(store, dict):
		store = {}
		st.session_state[SESSION_STATE_MEMORY_KEY] = store
	return store


def _ensure_session_memory_bundle(session_id: str) -> SessionMemoryBundle:
	store = _memory_bundle_store()
	bundle = store.get(session_id)
	if bundle is None:
		bundle = create_session_memory_bundle(session_id, use_mem0=USE_MEM0_MEMORY)
		store[session_id] = bundle
		st.session_state[SESSION_STATE_MEMORY_KEY] = store
	bundle.activate()
	st.session_state[SESSION_STATE_ACTIVE_MEMORY_KEY] = bundle
	return bundle


def _remove_session_memory_bundle(session_id: Optional[str]) -> None:
	if not session_id:
		return
	store = _memory_bundle_store()
	bundle = store.pop(session_id, None)
	st.session_state[SESSION_STATE_MEMORY_KEY] = store
	if st.session_state.get(SESSION_STATE_ACTIVE_MEMORY_KEY) is bundle:
		st.session_state.pop(SESSION_STATE_ACTIVE_MEMORY_KEY, None)
	delete_session_memory_storage(session_id)


def _set_active_session(chat_state: ChatSessionState, knowledge_state: KnowledgeSessionState) -> None:
	st.session_state[SESSION_STATE_CHAT_KEY] = chat_state
	st.session_state[SESSION_STATE_KNOWLEDGE_KEY] = knowledge_state
	st.session_state[SESSION_STATE_ACTIVE_ID_KEY] = chat_state.session_id
	bind_session_to_streamlit(
		st.session_state,
		chat_state=chat_state,
		knowledge_state=knowledge_state,
	)
	_ensure_session_memory_bundle(chat_state.session_id)


def _ensure_active_session() -> Tuple[ChatSessionState, KnowledgeSessionState]:
	if SESSION_STATE_CHAT_KEY in st.session_state and SESSION_STATE_KNOWLEDGE_KEY in st.session_state:
		chat_state = st.session_state[SESSION_STATE_CHAT_KEY]
		knowledge_state = st.session_state[SESSION_STATE_KNOWLEDGE_KEY]
		_ensure_session_memory_bundle(chat_state.session_id)
		return (chat_state, knowledge_state)

	manifest = _load_session_manifest()
	st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest

	active_id = st.session_state.get(SESSION_STATE_ACTIVE_ID_KEY) or manifest.get("active_session")
	if not active_id and manifest.get("sessions"):
		sorted_sessions = sorted(
			manifest["sessions"],
			key=lambda item: item.get("updated_at") or item.get("created_at") or "",
			reverse=True,
		)
		if sorted_sessions:
			active_id = sorted_sessions[0].get("id")

	if active_id:
		chat_state, knowledge_state = initialise_session(session_id=active_id)
	else:
		chat_state, knowledge_state = initialise_session()
		persist_session(chat_state, knowledge_state)
		manifest = _load_session_manifest()
		st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest

	_set_active_session(chat_state, knowledge_state)
	manifest = st.session_state.get(SESSION_STATE_MANIFEST_KEY, {})
	if isinstance(manifest, dict):
		manifest["active_session"] = chat_state.session_id
		_save_session_manifest(manifest)
		st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest
	return chat_state, knowledge_state


def _create_new_session() -> Tuple[ChatSessionState, KnowledgeSessionState]:
	chat_state, knowledge_state = initialise_session()
	persist_session(chat_state, knowledge_state)
	_set_active_session(chat_state, knowledge_state)
	manifest = _load_session_manifest()
	manifest["active_session"] = chat_state.session_id
	_save_session_manifest(manifest)
	st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest
	return chat_state, knowledge_state


def _delete_session(session_id: Optional[str]) -> Optional[str]:
	if not session_id:
		return None

	for path in (
		CONVERSATION_SESSIONS_DIR / f"{session_id}.json",
		KNOWLEDGE_SESSIONS_DIR / f"{session_id}.json",
		SCREENING_INSIGHTS_DIR / f"{session_id}.json",
	):
		try:
			path.unlink(missing_ok=True)
		except FileNotFoundError:
			continue

	manifest = _load_session_manifest()
	remaining = [entry for entry in manifest.get("sessions", []) if entry.get("id") != session_id]
	manifest["sessions"] = remaining
	if manifest.get("active_session") == session_id:
		manifest["active_session"] = remaining[0].get("id") if remaining else None
	_save_session_manifest(manifest)
	st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest
	_remove_session_memory_bundle(session_id)
	knowledge_store_sync.mark_dirty()
	knowledge_store_sync.flush_if_needed()
	return manifest.get("active_session")


def _format_session_label(session: Dict[str, any]) -> str:
	label = session.get("label") or session.get("job_title") or session.get("id") or "Session"
	updated = session.get("updated_at") or session.get("created_at")
	if updated:
		return f"{label} · {updated}"
	return label


def _session_history_line(session: Dict[str, any]) -> str:
	label = session.get("label") or "Untitled session"
	job_title = session.get("job_title") or "No job title"
	updated = session.get("updated_at") or session.get("created_at") or ""
	last_message = (session.get("last_message") or "").strip()
	snippet = last_message.splitlines()[0][:80] if last_message else ""

	meta_parts: List[str] = []
	if job_title:
		meta_parts.append(job_title)
	if updated:
		meta_parts.append(updated)

	line = f"- **{label}**"
	if meta_parts:
		line += f" · {' · '.join(meta_parts)}"
	if snippet:
		line += f"\n  \n  _{snippet}_"
	return line


def _render_sessions_tab(container: st.delta_generator.DeltaGenerator) -> None:
	manifest = st.session_state.get(SESSION_STATE_MANIFEST_KEY) or _load_session_manifest()
	st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest
	sessions = manifest.get("sessions", [])
	sessions_sorted = sorted(
		sessions,
		key=lambda item: item.get("updated_at") or item.get("created_at") or "",
		reverse=True,
	)

	controls = container.columns(2)
	if controls[0].button("New chat", use_container_width=True):
		_create_new_session()
		st.rerun()

	active_id = st.session_state.get(SESSION_STATE_ACTIVE_ID_KEY)
	delete_disabled = not sessions_sorted or active_id is None
	if controls[1].button("Delete chat", disabled=delete_disabled, use_container_width=True):
		next_active = _delete_session(active_id)
		if next_active:
			chat_state, knowledge_state = initialise_session(session_id=next_active)
		else:
			chat_state, knowledge_state = _create_new_session()
		_set_active_session(chat_state, knowledge_state)
		st.session_state[SESSION_STATE_ACTIVE_ID_KEY] = chat_state.session_id
		st.rerun()

	container.markdown("### Saved chats")
	if sessions_sorted:
		for session in sessions_sorted:
			session_id = session.get("id")
			if not session_id:
				continue
			label = _format_session_label(session)
			is_active = session_id == active_id
			button_label = f"➡️ {label}" if is_active else label
			if container.button(button_label, key=f"session_{session_id}", use_container_width=True):
				if session_id != active_id:
					chat_state, knowledge_state = initialise_session(session_id=session_id)
					_set_active_session(chat_state, knowledge_state)
					st.session_state[SESSION_STATE_ACTIVE_ID_KEY] = session_id
					manifest["active_session"] = session_id
					_save_session_manifest(manifest)
					st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest
					st.rerun()
	else:
		container.info("No previous chats yet. Start a new conversation to begin.")


def _weights_differ(current: Dict[str, float], updated: Dict[str, float]) -> bool:
	keys = set(current.keys()) | set(updated.keys())
	for key in keys:
		if abs(float(current.get(key, 0.0)) - float(updated.get(key, 0.0))) > 1e-6:
			return True
	return False


def _weights_as_percentages(
	weights: Dict[str, float],
	defaults: Dict[str, float],
) -> Dict[str, float]:
	base: Dict[str, float] = {}
	total = 0.0
	for key in defaults:
		value = max(float(weights.get(key, 0.0)), 0.0)
		base[key] = value
		total += value
	if total <= 0.0:
		return {key: defaults[key] * 100.0 for key in defaults}
	return {key: (base[key] / total) * 100.0 for key in defaults}


def _percentages_to_weights(
	percentages: Dict[str, float],
	defaults: Dict[str, float],
) -> Dict[str, float]:
	cleaned: Dict[str, float] = {}
	total = 0.0
	for key in defaults:
		value = max(float(percentages.get(key, 0.0)), 0.0)
		cleaned[key] = value
		total += value
	if total <= 0.0:
		return defaults.copy()
	return {key: cleaned[key] / total for key in defaults}


def _job_snapshot_markdown(job: JobDescription) -> str:
	if not job:
		return "No job description captured yet."

	payload = job.model_dump()
	lines: List[str] = []

	for field, label in JOB_FIELD_LABELS.items():
		value = payload.get(field)
		if not value:
			continue
		if isinstance(value, list):
			items = [item for item in value if item]
			if not items:
				continue
			bullet = "\n".join(f"  - {item}" for item in items)
			lines.append(f"**{label}:**\n{bullet}")
		else:
			text = str(value)
			if field == "job_type":
				text = text.replace("_", " ").title()
			lines.append(f"**{label}:** {text}")

	if job.outstanding_questions:
		questions = [q for q in job.outstanding_questions if q]
		if questions:
			lines.append(
				"**Outstanding questions:**\n" + "\n".join(f"  - {question}" for question in questions)
			)

	return "\n\n".join(lines) if lines else "Job description details have not been captured yet."


def _render_search_controls_tab(
	container: st.delta_generator.DeltaGenerator,
	chat_state: ChatSessionState,
	knowledge_state: KnowledgeSessionState,
) -> None:
	container.subheader("Search controls")
	container.caption(
		"Choose how many candidates to display and how much weight to give each signal. "
		"Feature importance are treated as percentages that add up to 100%."
	)

	top_k = container.number_input(
		"How many profiles to list",
		min_value=1,
		max_value=50,
		value=int(chat_state.top_k),
		step=1,
		help="Choose how many candidates you want to see in each screening run.",
	)
	if int(top_k) != chat_state.top_k:
		chat_state.top_k = int(top_k)
		persist_session(chat_state, knowledge_state)
		_set_active_session(chat_state, knowledge_state)
		st.session_state[SESSION_STATE_MANIFEST_KEY] = _load_session_manifest()
		container.success("Candidate retrieval limit updated.")

	container.markdown("##### Balance the ranking signals")
	scoring_explanations = {
		"semantic": "Overall similarity between the role and each resume.",
		"feature": "Resume fields wise similarity in such as skills, experience, and titles.",
	}
	current_scoring_percent = _weights_as_percentages(
		chat_state.scoring_weights,
		DEFAULT_SCORING_WEIGHTS,
	)
	scoring_updates: Dict[str, float] = {}
	for key in DEFAULT_SCORING_WEIGHTS.keys():
		label = {
			"semantic": "% focus on overall relevance",
			"feature": "% focus on each feature of the profile",
		}.get(key, f"{key.capitalize()} emphasis (%)")
		scoring_updates[key] = container.slider(
			label,
			min_value=0,
			max_value=100,
			value=int(round(current_scoring_percent.get(key, DEFAULT_SCORING_WEIGHTS[key] * 100))),
			step=5,
			help=scoring_explanations.get(key),
		)
	normalised_scoring = normalise_scoring_weights(
		_percentages_to_weights(scoring_updates, DEFAULT_SCORING_WEIGHTS)
	)
	if _weights_differ(chat_state.scoring_weights, normalised_scoring):
		chat_state.scoring_weights = normalised_scoring
		persist_session(chat_state, knowledge_state)
		_set_active_session(chat_state, knowledge_state)
		st.session_state[SESSION_STATE_MANIFEST_KEY] = _load_session_manifest()
		container.success("Scoring weights updated.")

	container.markdown("##### Highlight what matters in a profile")
	feature_explanations = {
		"skills": "Specific skills mentioned in the resume.",
		"experience": "Depth and relevance of past roles.",
		"education": "Degrees, certifications, and schooling.",
		"title": "Match between past job titles and the role.",
		"other": "Extra signals (summaries, languages, awards, etc.).",
	}
	current_feature_percent = _weights_as_percentages(
		chat_state.feature_weights,
		DEFAULT_FEATURE_WEIGHTS,
	)
	feature_updates: Dict[str, float] = {}
	for key in DEFAULT_FEATURE_WEIGHTS.keys():
		label = {
			"skills": "% matching with skills",
			"experience": "% matching with relevant experience",
			"education": "% matching with education",
			"title": "% matching with job titles",
			"other": "% matching with other highlights",
		}.get(key, f"{key.capitalize()} emphasis (%)")
		feature_updates[key] = container.slider(
			label,
			min_value=0,
			max_value=100,
			value=int(round(current_feature_percent.get(key, DEFAULT_FEATURE_WEIGHTS[key] * 100))),
			step=5,
			help=feature_explanations.get(key),
		)
	normalised_feature = normalise_feature_weights(
		_percentages_to_weights(feature_updates, DEFAULT_FEATURE_WEIGHTS)
	)
	if _weights_differ(chat_state.feature_weights, normalised_feature):
		chat_state.feature_weights = normalised_feature
		persist_session(chat_state, knowledge_state)
		_set_active_session(chat_state, knowledge_state)
		st.session_state[SESSION_STATE_MANIFEST_KEY] = _load_session_manifest()
		container.success("Profile weighting updated.")

	container.markdown("##### Job snapshot")
	container.markdown(_job_snapshot_markdown(chat_state.job_snapshot))


def _render_chat_messages(chat_state: ChatSessionState) -> None:
	if not chat_state.messages:
		st.info("No messages yet. Start the conversation with a question about the role or candidates.")
		return

	for message in chat_state.messages:
		role = message.role if message.role in {"assistant", "user"} else "assistant"
		with st.chat_message(role):
			content = message.content_md or ""
			st.markdown(content)
			if message.timestamp:
				try:
					timestamp_display = message.timestamp.strftime("%Y-%m-%d %H:%M")
				except Exception:  # pragma: no cover - defensive fallback
					timestamp_display = str(message.timestamp)
				st.caption(timestamp_display)


def _build_ingestion_message(monitor, ingestion) -> Tuple[str, List[str]]:
	if ingestion:
		warnings = list(ingestion.warnings or [])
		return "Application updated and loaded successfully.", warnings

	return "Application loaded successfully.", []


def _render_ingestion_banner() -> None:
	status = st.session_state.get(SESSION_STATE_INGESTION_KEY)
	if status is None:
		monitor, ingestion = bootstrap_resume_pipeline(auto_ingest=True, rebuild_embeddings=True)
		status = {"monitor": monitor, "ingestion": ingestion}
		st.session_state[SESSION_STATE_INGESTION_KEY] = status
	else:
		monitor = status.get("monitor")
		ingestion = status.get("ingestion")

	message, warnings = _build_ingestion_message(monitor, ingestion)
	st.success(message)
	if warnings:
		st.warning("\n".join(f"- {warning}" for warning in warnings))


def _render_sidebar(chat_state: ChatSessionState, knowledge_state: KnowledgeSessionState) -> None:
	session_tab, control_tab = st.sidebar.tabs(["Chat sessions", "Search controls"])
	_render_sessions_tab(session_tab)
	_render_search_controls_tab(control_tab, chat_state, knowledge_state)


def run_streamlit_app() -> None:
	st.set_page_config(page_title="Resume Screening Assistant", layout="wide")
	knowledge_store_sync.ensure_local_copy()
	ensure_data_directories()

	chat_state, knowledge_state = _ensure_active_session()
	_render_sidebar(chat_state, knowledge_state)

	st.title("Resume Screening Assistant")
	_render_ingestion_banner()

	st.subheader("Conversation")

	user_message = st.chat_input("Ask about the job or candidates…")
	active_chat = st.session_state.get(SESSION_STATE_CHAT_KEY, chat_state)
	_render_chat_messages(active_chat)
	if user_message:
		loader_placeholder = st.empty()
		try:
			with loader_placeholder.container():
				with st.chat_message("user"):
					st.markdown(user_message)
				with st.chat_message("assistant"):
					with st.spinner("Processing…"):
						_, chat_state, knowledge_state, flow_state = process_user_message(
							user_message,
							chat_state=chat_state,
							knowledge_state=knowledge_state,
							persist=True,
						)
		except FlowExecutionError as exc:
			loader_placeholder.empty()
			LOGGER.exception("Flow execution failed: %s", exc, exc_info=True)
			_set_active_session(exc.state.chat_state, exc.state.knowledge_state)
			manifest = _load_session_manifest()
			manifest["active_session"] = exc.state.chat_state.session_id
			_save_session_manifest(manifest)
			st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest
			st.session_state[SESSION_STATE_LAST_ERRORS_KEY] = exc.state.errors
			st.error("I ran into an error processing that turn. Please try again.")
		else:
			loader_placeholder.empty()
			_set_active_session(chat_state, knowledge_state)
			manifest = _load_session_manifest()
			manifest["active_session"] = chat_state.session_id
			_save_session_manifest(manifest)
			st.session_state[SESSION_STATE_MANIFEST_KEY] = manifest
			if flow_state.errors:
				st.session_state[SESSION_STATE_LAST_ERRORS_KEY] = list(flow_state.errors)
			else:
				st.session_state.pop(SESSION_STATE_LAST_ERRORS_KEY, None)
			st.rerun()

	errors = st.session_state.pop(SESSION_STATE_LAST_ERRORS_KEY, None)
	if errors:
		for error in errors:
			st.warning(error)


__all__ = [
	"FlowExecutionError",
	"initialise_session",
	"process_user_message",
	"run_streamlit_app",
]


if __name__ == "__main__":
	run_streamlit_app()
