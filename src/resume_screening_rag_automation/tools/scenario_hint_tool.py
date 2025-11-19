"""CrewAI tool that returns similarity hints for query-manager scenarios."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field, field_validator

from crewai.tools import BaseTool

from resume_screening_rag_automation.paths import (
    QUERY_MANAGER_SCENARIO_FILE,
    ensure_data_directories,
)
from resume_screening_rag_automation.tools.vectorstore_utils import (
    CHROMADB_AVAILABLE,
    DEFAULT_EMBEDDING_MODEL,
    get_embedding_function,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ScenarioEntry:
    """Representation of a canonical routing scenario."""

    name: str
    inputs: Dict[str, Any]
    expectations: Dict[str, Any]
    text: str


class ScenarioHintIndex:
    """Index that embeds scenarios and surfaces the closest matches."""

    def __init__(self, entries: Sequence[ScenarioEntry], model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self._entries = list(entries)
        self._model_name = model_name
        self._embedder: Optional[Any] = None
        self._embeddings: Optional[List[np.ndarray]] = None
        self._disabled = not CHROMADB_AVAILABLE

    def _ensure_embedder(self) -> Optional[Any]:
        if self._disabled:
            return None
        if self._embedder is None:
            try:
                self._embedder = get_embedding_function(self._model_name)
            except Exception as exc:  # pragma: no cover - depends on environment
                LOGGER.warning("Scenario hints disabled: %s", exc)
                self._disabled = True
                return None
        return self._embedder

    @staticmethod
    def _normalise(vector: Iterable[float]) -> np.ndarray:
        array = np.asarray(list(vector), dtype=np.float32)
        norm = float(np.linalg.norm(array))
        if norm == 0.0:
            return array
        return array / norm

    def _ensure_embeddings(self) -> None:
        if self._embeddings is not None or self._disabled:
            return
        embedder = self._ensure_embedder()
        if embedder is None:
            return
        texts = [entry.text for entry in self._entries]
        try:
            raw_vectors = embedder(texts)
        except Exception as exc:  # pragma: no cover - depends on backend
            LOGGER.warning("Failed to embed scenario corpus: %s", exc)
            self._disabled = True
            return
        self._embeddings = [self._normalise(vector) for vector in raw_vectors]

    def query(self, text: str, *, top_k: int = 2, min_score: float = 0.25) -> List[Tuple[ScenarioEntry, float]]:
        if not text.strip():
            return []
        if self._disabled:
            return []
        self._ensure_embeddings()
        if self._embeddings is None or not self._embeddings:
            return []
        embedder = self._ensure_embedder()
        if embedder is None:
            return []
        try:
            query_vector = embedder([text])[0]
        except Exception as exc:  # pragma: no cover - depends on backend
            LOGGER.debug("Scenario hint query embedding failed: %s", exc)
            return []
        query_norm = self._normalise(query_vector)
        results: List[Tuple[ScenarioEntry, float]] = []
        for entry, vector in zip(self._entries, self._embeddings):
            if vector.shape != query_norm.shape:
                continue
            score = float(np.dot(vector, query_norm))
            if score >= min_score:
                results.append((entry, score))
        results.sort(key=lambda item: item[1], reverse=True)
        return results[:top_k]


class ScenarioHintToolInput(BaseModel):
    """Input schema for the scenario hint tool."""

    user_query: str = Field(..., description="Latest recruiter request to analyse.")
    last_phase: Optional[str] = Field(None, description="Previously completed conversation phase.")
    query_control: Dict[str, Any] = Field(
        default_factory=dict,
        description="Serialized query control dictionary for the current turn.",
    )
    state: Dict[str, Any] = Field(
        default_factory=dict,
        description="Serialized AppState payload for the routing context.",
    )
    conversation_history: Sequence[Dict[str, Any]] = Field(
        default_factory=list,
        description="Ordered history entries (role, phase, timestamp, content).",
    )
    top_k: int = Field(2, description="Number of similar scenarios to surface.")

    @field_validator("user_query", mode="before")
    @classmethod
    def _coerce_user_query(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("description", "value", "text"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
        return str(value or "")

    @field_validator("last_phase", mode="before")
    @classmethod
    def _coerce_last_phase(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("description", "value", "text"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
        return str(value)

    @staticmethod
    def _decode_json(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
                if isinstance(decoded, dict):
                    return decoded
            except json.JSONDecodeError:
                LOGGER.debug("Unable to parse JSON payload for scenario hint context", exc_info=True)
        return {}

    @field_validator("query_control", mode="before")
    @classmethod
    def _coerce_query_control(cls, value: Any) -> Dict[str, Any]:
        return cls._decode_json(value)

    @field_validator("state", mode="before")
    @classmethod
    def _coerce_state(cls, value: Any) -> Dict[str, Any]:
        return cls._decode_json(value)

    @field_validator("conversation_history", mode="before")
    @classmethod
    def _coerce_history(cls, value: Any) -> Sequence[Dict[str, Any]]:
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
                if isinstance(decoded, list):
                    return decoded
            except json.JSONDecodeError:
                LOGGER.debug("Unable to parse history payload for scenario hint context", exc_info=True)
        return []

    @field_validator("top_k", mode="before")
    @classmethod
    def _ensure_positive_top_k(cls, value: Any) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return 2
        return max(1, numeric)


def _scenario_text(inputs: Dict[str, Any], expectations: Dict[str, Any]) -> str:
    parts: List[str] = []
    user_query = inputs.get("user_query", "").strip()
    if user_query:
        parts.append(f"User query: {user_query}")
    last_phase = inputs.get("last_phase") or ""
    if last_phase:
        parts.append(f"Last phase: {last_phase}")
    previous_plan = inputs.get("previous_plan") or ""
    if previous_plan:
        parts.append(f"Previous plan: {previous_plan}")
    query_control = inputs.get("query_control") or {}
    phase_sequence = query_control.get("phase_sequence") or []
    if phase_sequence:
        parts.append("Control phases: " + " -> ".join(map(str, phase_sequence)))
    flags = {
        key: value
        for key, value in query_control.items()
        if key not in {"phase_sequence", "last_completed_phase"} and value
    }
    if flags:
        flag_pairs = ", ".join(f"{key}={value}" for key, value in sorted(flags.items()))
        parts.append(f"Control flags: {flag_pairs}")
    expected_phases = expectations.get("phase_sequence") or []
    if expected_phases:
        parts.append("Expected phases: " + " -> ".join(map(str, expected_phases)))
    expected_flags = expectations.get("flags") or {}
    if expected_flags:
        flag_pairs = ", ".join(f"{key}={value}" for key, value in sorted(expected_flags.items()))
        parts.append(f"Expected flags: {flag_pairs}")
    top_k_hint = expectations.get("top_k_hint")
    if top_k_hint is not None:
        parts.append(f"Expected top_k_hint: {top_k_hint}")
    forbidden_flags = expectations.get("forbidden_flags") or {}
    if forbidden_flags:
        forbid_pairs = ", ".join(f"{key}={value}" for key, value in sorted(forbidden_flags.items()))
        parts.append(f"Forbidden flags: {forbid_pairs}")
    conversation_history = inputs.get("conversation_history") or []
    if conversation_history:
        history_snippets = []
        for message in conversation_history[-3:]:
            role = message.get("role", "")
            phase = message.get("phase") or ""
            content = (message.get("content") or "").strip()
            snippet = role or ""
            if phase:
                snippet += f"[{phase}]"
            if content:
                snippet += f": {content}"
            history_snippets.append(snippet)
        if history_snippets:
            parts.append("Recent history: " + " | ".join(history_snippets))
    return "\n".join(parts)


def _query_text(
    user_query: str,
    *,
    last_phase: Optional[str],
    query_control: Dict[str, Any],
    state: Dict[str, Any],
    conversation_history: Sequence[Dict[str, Any]],
) -> str:
    parts = [f"User query: {user_query.strip()}" or "User query: (empty)"]
    if last_phase:
        parts.append(f"Last phase: {last_phase}")
    phase_sequence = query_control.get("phase_sequence") or []
    if phase_sequence:
        parts.append("Control phases: " + " -> ".join(map(str, phase_sequence)))
    flags = {
        key: value
        for key, value in query_control.items()
        if key not in {"phase_sequence", "last_completed_phase"} and value
    }
    if flags:
        flag_pairs = ", ".join(f"{key}={value}" for key, value in sorted(flags.items()))
        parts.append(f"Control flags: {flag_pairs}")
    state_last = state.get("last_completed_phase")
    if state_last:
        parts.append(f"State last phase: {state_last}")
    pending = state.get("pending_phases") or []
    if pending:
        parts.append("Pending phases: " + " -> ".join(map(str, pending)))
    conversation_tail = list(conversation_history)[-3:]
    if conversation_tail:
        snippets = []
        for message in conversation_tail:
            role = message.get("role", "")
            phase = message.get("phase") or ""
            content = (message.get("content") or "").strip()
            snippet = role or ""
            if phase:
                snippet += f"[{phase}]"
            if content:
                snippet += f": {content}"
            snippets.append(snippet)
        if snippets:
            parts.append("Recent history: " + " | ".join(snippets))
    return "\n".join(parts)


@lru_cache(maxsize=1)
def _load_index() -> ScenarioHintIndex:
    ensure_data_directories()
    scenarios_path: Path = QUERY_MANAGER_SCENARIO_FILE
    entries: List[ScenarioEntry] = []
    if not scenarios_path.exists():
        LOGGER.debug("Scenario hint dataset missing at %s", scenarios_path)
        return ScenarioHintIndex(entries)
    with scenarios_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:  # pragma: no cover - defensive fallback
                continue
            inputs = payload.get("inputs") or {}
            expectations = payload.get("expectations") or {}
            text = _scenario_text(inputs, expectations)
            entries.append(
                ScenarioEntry(
                    payload.get("name", "Unnamed Scenario"),
                    inputs,
                    expectations,
                    text,
                )
            )
    return ScenarioHintIndex(entries)


def scenario_hints_for_context(
    user_query: str,
    *,
    last_phase: Optional[str],
    query_control: Dict[str, Any],
    state: Dict[str, Any],
    conversation_history: Sequence[Dict[str, Any]],
    top_k: int = 2,
) -> str:
    """Return a human-readable hint describing the closest matching scenarios."""

    if top_k <= 0:
        top_k = 2

    index = _load_index()
    query_text = _query_text(
        user_query,
        last_phase=last_phase,
        query_control=query_control,
        state=state,
        conversation_history=conversation_history,
    )
    matches = index.query(query_text, top_k=top_k)
    if not matches:
        return "No close scenario match available."

    lines: List[str] = []
    for idx, (entry, score) in enumerate(matches, start=1):
        expectations = entry.expectations
        phases = expectations.get("phase_sequence") or []
        flags = expectations.get("flags") or {}
        forbidden = expectations.get("forbidden_flags") or {}
        details: List[str] = []
        if phases:
            details.append("phases=" + " -> ".join(map(str, phases)))
        if flags:
            details.append(", ".join(f"{key}={value}" for key, value in sorted(flags.items())))
        top_k_hint = expectations.get("top_k_hint")
        if top_k_hint is not None:
            details.append(f"top_k_hint={top_k_hint}")
        if forbidden:
            details.append(
                "avoid " + ", ".join(f"{key}={value}" for key, value in sorted(forbidden.items()))
            )
        detail_text = "; ".join(details) if details else "review dataset expectations"
        lines.append(f"{idx}. {entry.name} (score {score:.2f}) -> {detail_text}")
    return "\n".join(lines)


class ScenarioHintTool(BaseTool):
    """CrewAI tool that surfaces similar query-manager scenarios."""

    name: str = "scenario_hint_lookup"
    description: str = (
        "Use this tool to compare the current recruiter request, controls, and state against the "
        "canonical scenario corpus. It returns the closest matching scenarios with their expected "
        "phase sequences and flags so you can avoid routing mistakes."
    )
    args_schema: type[ScenarioHintToolInput] = ScenarioHintToolInput

    def _run(  # type: ignore[override]
        self,
        user_query: str,
        last_phase: Optional[str] = None,
        query_control: Optional[Dict[str, Any]] = None,
        state: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[Sequence[Dict[str, Any]]] = None,
        top_k: int = 2,
    ) -> str:
        query_control = query_control or {}
        state = state or {}
        conversation_history = conversation_history or []
        try:
            return scenario_hints_for_context(
                user_query,
                last_phase=last_phase,
                query_control=query_control,
                state=state,
                conversation_history=conversation_history,
                top_k=top_k,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.debug("Scenario hint tool failed: %s", exc)
            return "No close scenario match available."


__all__ = [
    "ScenarioHintTool",
    "scenario_hints_for_context",
]
