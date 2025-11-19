"""Legacy ingestion-related models maintained for pipeline compatibility."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from resume_screening_rag_automation.core.py_models import Resume, ResumeFileInfo


class ResumeMonitorOutput(BaseModel):
    new_files: List[ResumeFileInfo] = Field(default_factory=list)
    removed_files: List[ResumeFileInfo] = Field(default_factory=list)
    duplicate_files: List[ResumeFileInfo] = Field(default_factory=list)
    inspected_at: Optional[str] = None
    knowledge_count: int = 0


class ResumeParsingInput(BaseModel):
    """Payload sent to the AI parsing crew."""

    files: List[ResumeFileInfo] = Field(default_factory=list)
    resume_texts: Dict[str, str] = Field(default_factory=dict)
    existing_records: List[Dict[str, Any]] = Field(default_factory=list)


class ResumeParsingOutput(BaseModel):
    """Structured response from the AI parsing crew."""

    parsed_resumes: List[Resume] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ResumeIngestionOutput(BaseModel):
    """Outcome of applying resume ingestion updates."""

    resumes: List[Resume] = Field(default_factory=list)
    new_resumes: List[Resume] = Field(default_factory=list)
    removed_files: List[ResumeFileInfo] = Field(default_factory=list)
    embedded_candidate_ids: List[str] = Field(default_factory=list)
    removed_candidate_ids: List[str] = Field(default_factory=list)
    knowledge_path: Optional[str] = None
    collection_name: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    elapsed_seconds: float = 0.0


__all__ = [
    "ResumeMonitorOutput",
    "ResumeParsingInput",
    "ResumeParsingOutput",
    "ResumeIngestionOutput",
]
