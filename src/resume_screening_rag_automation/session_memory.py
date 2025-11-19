"""Session-scoped memory helpers leveraging CrewAI's memory primitives."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from crewai.memory.entity.entity_memory import EntityMemory
from crewai.memory.entity.entity_memory_item import EntityMemoryItem
from crewai.memory.long_term.long_term_memory import LongTermMemory
from crewai.memory.long_term.long_term_memory_item import LongTermMemoryItem
from crewai.memory.short_term.short_term_memory import ShortTermMemory

from resume_screening_rag_automation.models import CandidateInsight, ChatMessage, JobDescription, Metadata
from resume_screening_rag_automation.paths import DATA_ROOT
from resume_screening_rag_automation.storage_sync import knowledge_store_sync
from resume_screening_rag_automation.tools.vectorstore_utils import DEFAULT_EMBEDDER_SPEC

LOGGER = logging.getLogger(__name__)

MEMORY_ROOT = (DATA_ROOT / "crew_memory").resolve()


def _clone_embedder_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(spec))


def _normalise_timestamp(timestamp: Optional[datetime]) -> Optional[str]:
    if timestamp is None:
        return None
    try:
        return timestamp.isoformat()
    except Exception:  # pragma: no cover - defensive fallback
        return str(timestamp)


def _summarise_job(job: JobDescription) -> str:
    parts: List[str] = []
    if job.location:
        parts.append(f"Location: {job.location}")
    if job.experience_level_years is not None:
        parts.append(f"Experience: {job.experience_level_years} years")
    if job.required_skills:
        skills = ", ".join(job.required_skills[:8])
        parts.append(f"Key skills: {skills}")
    if job.job_responsibilities:
        responsibilities = ", ".join(job.job_responsibilities[:5])
        parts.append(f"Responsibilities: {responsibilities}")
    if job.education_requirements:
        education = ", ".join(job.education_requirements[:3])
        parts.append(f"Education: {education}")
    return " | ".join(parts) or "No structured job summary available"


@dataclass
class SessionMemoryBundle:
    """Container for CrewAI memory objects bound to a conversation session."""

    session_id: str
    storage_dir: Path
    short_term: ShortTermMemory
    long_term: LongTermMemory
    entity: EntityMemory

    def crew_kwargs(self) -> Dict[str, Any]:
        return {
            "short_term_memory": self.short_term,
            "long_term_memory": self.long_term,
            "entity_memory": self.entity,
        }

    def activate(self) -> None:
        os.environ["CREWAI_STORAGE_DIR"] = str(self.storage_dir)

    def record_message(self, message: ChatMessage) -> None:
        if not message or not message.content_md:
            return
        metadata = {
            "session_id": self.session_id,
            "role": message.role,
            "phase": message.phase.value if message.phase else None,
            "timestamp": _normalise_timestamp(message.timestamp),
        }
        try:
            self.short_term.save(message.content_md, metadata=metadata)
        except Exception:  # pragma: no cover - non-critical telemetry
            LOGGER.debug("Failed to capture message in short-term memory", exc_info=True)

        if message.role == "assistant":
            try:
                item = LongTermMemoryItem(
                    agent="assistant",
                    task=f"Assistant response during {metadata['phase'] or 'conversation'}",
                    expected_output=message.content_md[:300],
                    datetime=metadata.get("timestamp") or datetime.utcnow().isoformat(),
                    quality=None,
                    metadata={
                        "session_id": self.session_id,
                        "quality": None,
                    },
                )
                self.long_term.save(item)
            except Exception:  # pragma: no cover - non-critical telemetry
                LOGGER.debug("Failed to capture message in long-term memory", exc_info=True)

    def record_candidates(self, insights: Iterable[CandidateInsight]) -> None:
        items: List[EntityMemoryItem] = []
        for insight in insights or []:
            metadata = insight.metadata or Metadata()
            candidate_name = (
                (metadata.candidate_name or "").strip()
                or (metadata.file_name or "").strip()
                or (metadata.current_title or "").strip()
                or (metadata.candidate_id or "").strip()
                or "Candidate"
            )
            description = (insight.summary_md or "").strip()
            if not description:
                description = "No summary available."
            reasoning = insight.fit_reasoning or []
            relationships = ", ".join(reasoning[:6]) or "No reasoning captured"
            try:
                items.append(
                    EntityMemoryItem(
                        name=candidate_name,
                        type="candidate",
                        description=description,
                        relationships=relationships,
                    )
                )
            except Exception:  # pragma: no cover - defensive guard
                LOGGER.debug("Failed to prepare entity item for %s", candidate_name, exc_info=True)
        if not items:
            return
        try:
            self.entity.save(items)
        except Exception:  # pragma: no cover - non-critical telemetry
            LOGGER.debug("Failed to persist candidate entities", exc_info=True)

    def record_job_snapshot(self, job_snapshot: JobDescription) -> None:
        if not job_snapshot or not job_snapshot.job_title:
            return
        relationships = ", ".join(job_snapshot.required_skills[:10]) or "No skills captured"
        description = _summarise_job(job_snapshot)
        try:
            item = EntityMemoryItem(
                name=job_snapshot.job_title,
                type="job",
                description=description,
                relationships=relationships,
            )
            self.entity.save(item)
        except Exception:  # pragma: no cover - non-critical telemetry
            LOGGER.debug("Failed to persist job snapshot entity", exc_info=True)


def _ensure_storage_dir(session_id: str) -> Path:
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    path = MEMORY_ROOT / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def create_session_memory_bundle(session_id: str, *, use_mem0: bool = False) -> SessionMemoryBundle:
    storage_dir = _ensure_storage_dir(session_id)
    if use_mem0:
        embedder_spec: Dict[str, Any] = {
            "provider": "mem0",
            "config": {"user_id": session_id},
        }
    else:
        embedder_spec = _clone_embedder_spec(DEFAULT_EMBEDDER_SPEC)
    os.environ["CREWAI_STORAGE_DIR"] = str(storage_dir)

    short_term = ShortTermMemory(embedder_config=embedder_spec)
    entity = EntityMemory(embedder_config=embedder_spec)
    long_term = LongTermMemory()

    return SessionMemoryBundle(
        session_id=session_id,
        storage_dir=storage_dir,
        short_term=short_term,
        long_term=long_term,
        entity=entity,
    )


def delete_session_memory_storage(session_id: str) -> None:
    target = MEMORY_ROOT / session_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        knowledge_store_sync.mark_dirty()
        knowledge_store_sync.flush_if_needed()


__all__ = [
    "SessionMemoryBundle",
    "create_session_memory_bundle",
    "delete_session_memory_storage",
]
