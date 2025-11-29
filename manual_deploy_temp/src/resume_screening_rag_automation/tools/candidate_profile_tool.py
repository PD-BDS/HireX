"""Tool for fetching structured resume details for shortlisted candidates."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Set, Type

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from crewai.tools import BaseTool

from resume_screening_rag_automation.tools.extract_candidates import (
    _build_resume_content,
    _index_resumes_by_id,
    _load_structured_resumes,
)

load_dotenv()
LOGGER = logging.getLogger(__name__)


class CandidateProfileInput(BaseModel):
    candidates: List[str] = Field(
        ..., description="List of candidate identifiers or resume file names to retrieve"
    )

    @field_validator("candidates", mode="before")
    @classmethod
    def _coerce_candidates(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    value = parsed
                else:
                    value = [value]
            except json.JSONDecodeError:
                value = [value]
        if isinstance(value, list):
            cleaned: List[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    cleaned.append(text)
            return cleaned
        return [str(value).strip()]

    @field_validator("candidates")
    @classmethod
    def _require_candidate(cls, value: List[str]) -> List[str]:
        if not value:
            LOGGER.debug("CandidateProfileTool received an empty candidate list; returning no profiles")
            return []
        return value


class CandidateProfileTool(BaseTool):
    name: str = "Fetch Candidate Profiles"
    description: str = "Load structured resume details for specific candidate identifiers"
    args_schema: Type[BaseModel] = CandidateProfileInput

    def _run(self, candidates: List[str]) -> Dict[str, Any]:
        requested: Set[str] = {item.strip() for item in candidates if item.strip()}
        if not requested:
            LOGGER.info("CandidateProfileTool invoked with no candidates; skipping lookup")
            return {"profiles": []}
        LOGGER.info("CandidateProfileTool retrieving profiles for %s candidates", len(requested))
        resumes = _load_structured_resumes()
        indexed = _index_resumes_by_id(resumes)
        profiles: List[Dict[str, Any]] = []
        for key in requested:
            record = indexed.get(key)
            if not record:
                LOGGER.debug("CandidateProfileTool missing candidate for key=%s", key)
                continue
            metadata = record.get("metadata", {}) or {}
            content = record.get("content") or {}
            resume_content = _build_resume_content(content)
            profiles.append(
                {
                    "candidate_id": metadata.get("candidate_id") or metadata.get("id"),
                    "candidate_name": metadata.get("candidate_name") or metadata.get("name"),
                    "resume_path": metadata.get("file_name"),
                    "metadata": metadata,
                    "content": resume_content.model_dump(),
                    "resume_text": record.get("raw_text"),
                }
            )
        return {"profiles": profiles}
