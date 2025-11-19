"""Persistence helpers for generated screening insights."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from resume_screening_rag_automation.core.py_models import CandidateScreeningOutput
from resume_screening_rag_automation.paths import (
    SCREENING_INSIGHTS_DIR,
    ensure_data_directories,
)
from resume_screening_rag_automation.storage_sync import knowledge_store_sync

LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insight_path_for_session(session_id: str) -> Path:
    ensure_data_directories()
    return SCREENING_INSIGHTS_DIR / f"{session_id}.json"


def _record_identifier(job_title: Optional[str], timestamp: str) -> str:
    base = (job_title or "untitled").strip().lower() or "untitled"
    safe_base = "_".join(base.split())
    return f"{safe_base}:{timestamp}"


def _load_records(path: Path, *, session_id: str) -> Dict[str, Any]:
    if not path.exists():
        return {"session_id": session_id, "records": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover - defensive fallback
        LOGGER.warning("Failed to read screening insights for session=%s; recreating", session_id, exc_info=True)
        return {"session_id": session_id, "records": []}
    if "session_id" not in payload:
        payload["session_id"] = session_id
    payload.setdefault("records", [])
    if not isinstance(payload["records"], list):
        payload["records"] = []
    for entry in payload["records"]:
        timestamp = entry.get("timestamp")
        if not timestamp:
            timestamp = _utc_now()
            entry["timestamp"] = timestamp
        if "record_id" not in entry:
            job_title = entry.get("job_title")
            entry["record_id"] = _record_identifier(job_title, timestamp)
    return payload


def _write_records(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_screening_insights(
    *,
    session_id: Optional[str],
    job_title: Optional[str],
    output: CandidateScreeningOutput,
) -> None:
    """Append the latest screening insights to the shared knowledge store."""

    if not output.candidate_insights:
        LOGGER.debug("No candidate insights to persist for session=%s", session_id)
        return

    if not session_id:
        LOGGER.warning("Skipping screening insight persistence: missing session identifier")
        return

    path = _insight_path_for_session(session_id)
    payload = _load_records(path, session_id=session_id)
    entries: List[Dict[str, Any]] = list(payload.get("records") or [])

    timestamp = _utc_now()

    record_id = _record_identifier(job_title, timestamp)

    entry = {
        "session_id": session_id,
        "job_title": job_title,
        "timestamp": timestamp,
        "record_id": record_id,
        "message_md": output.message_md,
        "database_summary_md": output.database_summary_md,
        "candidate_insights": [insight.model_dump() for insight in output.candidate_insights],
        "knowledge_records": list(output.knowledge_records or []),
    }
    entries.append(entry)

    payload["session_id"] = session_id
    payload["records"] = entries
    payload["job_titles"] = sorted(
        {
            (item.get("job_title") or "").strip()
            for item in entries
            if item.get("job_title")
        }
    )
    payload["last_updated"] = _utc_now()

    _write_records(path, payload)
    knowledge_store_sync.mark_dirty()
    knowledge_store_sync.flush_if_needed()
    LOGGER.info(
        "Persisted %s candidate insights to knowledge for session=%s",
        len(output.candidate_insights),
        session_id,
    )
