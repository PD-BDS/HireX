"""Tool for retrieving resume evidence chunks for shortlisted candidates."""

from __future__ import annotations

import logging
import json
from typing import Any, Dict, List, Sequence, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, field_validator

from resume_screening_rag_automation.core.py_models import JobDescription, normalize_job_description_dict
from resume_screening_rag_automation.tools.constants import RESUME_COLLECTION_NAME
from resume_screening_rag_automation.tools.vectorstore_utils import ensure_chroma_client, get_embedding_function

LOGGER = logging.getLogger(__name__)


def _build_job_query(job: JobDescription) -> str:
    parts: List[str] = []
    if job.job_title:
        parts.append(f"Role: {job.job_title}")
    if job.location:
        parts.append(f"Location: {job.location}")
    if job.experience_level_years:
        parts.append(f"Experience: {job.experience_level_years} years")
    if job.required_skills:
        parts.append("Skills: " + ", ".join(job.required_skills[:12]))
    if job.job_responsibilities:
        joined = "; ".join(job.job_responsibilities[:6])
        parts.append(f"Responsibilities: {joined}")
    if job.education_requirements:
        parts.append("Education: " + ", ".join(job.education_requirements[:4]))
    if job.certification_requirements:
        parts.append("Certifications: " + ", ".join(job.certification_requirements[:4]))
    if job.extra_requirements:
        parts.append(f"Extras: {job.extra_requirements}")
    if job.language_requirements:
        parts.append("Languages: " + ", ".join(job.language_requirements[:4]))
    return " | ".join(part.strip() for part in parts if part.strip())


def _distance_to_similarity(distance: Any) -> float:
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.0
    if value < 0:
        value = 0.0
    if value <= 1:
        return round(max(0.0, 1.0 - value), 4)
    return round(1.0 / (1.0 + value), 4)


class CandidateEvidenceInput(BaseModel):
    job_description: Dict[str, Any] = Field(default_factory=dict, description="Structured job description payload")
    candidates: Sequence[str] = Field(..., description="Candidate identifiers (candidate_id or resume file names)")
    top_k: int = Field(3, description="Number of supporting chunks to retrieve per candidate")
    collection_name: str = Field(RESUME_COLLECTION_NAME, description="Chroma collection name to query")

    @field_validator("job_description", mode="before")
    @classmethod
    def _coerce_job_description(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @field_validator("candidates", mode="before")
    @classmethod
    def _coerce_candidates(cls, value: Any) -> Sequence[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            return cleaned
        text = str(value).strip()
        return [text] if text else []

    @field_validator("top_k", mode="before")
    @classmethod
    def _ensure_positive_top_k(cls, value: Any) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = 3
        return max(1, numeric)


class CandidateEvidenceTool(BaseTool):
    name: str = "Fetch Candidate Evidence"
    description: str = "Retrieve the most relevant resume chunks for shortlisted candidates"
    args_schema: Type[BaseModel] = CandidateEvidenceInput

    def _run(
        self,
        job_description: Dict[str, Any],
        candidates: Sequence[str],
        top_k: int = 3,
        collection_name: str = RESUME_COLLECTION_NAME,
    ) -> Dict[str, Any]:
        job_payload = normalize_job_description_dict(job_description)
        job = JobDescription.model_validate(job_payload)
        query = _build_job_query(job)
        if not query:
            query = "Resume evidence summarisation"

        if not candidates:
            return {
                "query": query,
                "collection": collection_name or RESUME_COLLECTION_NAME,
                "evidence": [],
            }

        client = ensure_chroma_client()
        collection = client.get_or_create_collection(
            collection_name or RESUME_COLLECTION_NAME,
            embedding_function=get_embedding_function(),
        )

        evidence: List[Dict[str, Any]] = []
        for candidate in candidates:
            candidate_id = str(candidate).strip()
            if not candidate_id:
                continue
            chunks: List[Dict[str, Any]] = []
            seen_chunk_ids: set[str] = set()
            for where in ({"candidate_id": candidate_id}, {"file_name": candidate_id}):
                try:
                    result = collection.query(
                        query_texts=[query],
                        n_results=top_k,
                        where=where,
                        include=["documents", "metadatas", "distances"],
                    )
                except Exception:
                    LOGGER.debug("Candidate evidence query failed for %s", candidate_id, exc_info=True)
                    continue

                docs = result.get("documents", [[]])[0]
                metas = result.get("metadatas", [[]])[0]
                distances = result.get("distances", [[]])[0]
                ids = result.get("ids", [[]])[0]
                for idx, doc in enumerate(docs):
                    chunk_id = ids[idx] if idx < len(ids) else ""
                    if chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(chunk_id)
                    metadata = metas[idx] if idx < len(metas) else {}
                    distance = distances[idx] if idx < len(distances) else None
                    chunks.append(
                        {
                            "id": chunk_id,
                            "text": doc,
                            "similarity": _distance_to_similarity(distance),
                            "metadata": metadata,
                        }
                    )
                if len(chunks) >= top_k:
                    break

            evidence.append(
                {
                    "candidate_id": candidate_id,
                    "chunks": chunks[:top_k],
                }
            )

        return {
            "query": query,
            "collection": collection_name or RESUME_COLLECTION_NAME,
            "evidence": evidence,
        }

