"""Domain models used throughout the resume screening assistant."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from resume_screening_rag_automation.core.constants import (
    DEFAULT_FEATURE_WEIGHTS,
    DEFAULT_SCORING_WEIGHTS,
)


class ConversationPhase(str, Enum):
    job_description = "job_description"
    screening = "screening"
    discussion = "discussion"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content_md: str = ""
    phase: Optional[ConversationPhase] = None
    timestamp: Optional[datetime] = None


class ExperienceItem(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    period: Optional[str] = None
    location: Optional[str] = None
    roles: List[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    degree: Optional[str] = None
    institution: Optional[str] = None
    period: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class SkillsSection(BaseModel):
    technical: List[str] = Field(default_factory=list)
    soft: List[str] = Field(default_factory=list)

    @field_validator("technical", "soft", mode="before")
    @classmethod
    def _ensure_list(cls, value: Optional[Any]) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            result: List[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    result.append(text)
            return result
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        raise ValueError("skills entries must be a list of strings")

    @model_validator(mode="after")
    def _dedupe(self) -> "SkillsSection":
        def _unique(values: List[str]) -> List[str]:
            seen = set()
            ordered: List[str] = []
            for item in values:
                lower = item.lower()
                if lower not in seen:
                    seen.add(lower)
                    ordered.append(item)
            return ordered

        self.technical = _unique(self.technical)
        self.soft = _unique(self.soft)
        return self


class ResumeContent(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    experience: List[ExperienceItem] = Field(default_factory=list)
    skills: SkillsSection = Field(default_factory=SkillsSection)
    education: List[EducationItem] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    other: Dict[str, Any] = Field(default_factory=dict)


class Metadata(BaseModel):
    file_name: Optional[str] = None
    candidate_name: Optional[str] = None
    candidate_id: Optional[str] = None
    current_title: Optional[str] = None
    content_hash: Optional[str] = None


class Resume(BaseModel):
    metadata: Metadata
    content: ResumeContent


class ResumeFileInfo(BaseModel):
    file_name: str
    path: str
    size_bytes: int
    modified_at: str
    candidate_id: Optional[str] = None
    content_hash: Optional[str] = None

    @field_validator("file_name", mode="before")
    @classmethod
    def _validate_file_name(cls, value: Optional[str]) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("file_name is required")
        return text

    @field_validator("path", mode="before")
    @classmethod
    def _validate_path(cls, value: Optional[str]) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("path is required")
        return text


class JobType(str, Enum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    temporary = "temporary"
    remote = "remote"
    on_site = "on_site"
    hybrid = "hybrid"
    internship = "internship"
    freelance = "freelance"
    other = "other"


class JobDescription(BaseModel):
    job_title: Optional[str] = None
    location: Optional[str] = None
    experience_level_years: Optional[int] = None
    required_skills: List[str] = Field(default_factory=list)
    job_responsibilities: List[str] = Field(default_factory=list)
    education_requirements: List[str] = Field(default_factory=list)
    extra_requirements: Optional[str] = None
    job_type: Optional[JobType] = None
    language_requirements: Optional[List[str]] = Field(default_factory=list)
    certification_requirements: Optional[List[str]] = Field(default_factory=list)
    outstanding_questions: Optional[List[str]] = Field(default_factory=list)

    @field_validator("required_skills", "job_responsibilities", "education_requirements", "language_requirements", "certification_requirements", "outstanding_questions", mode="before")
    @classmethod
    def _ensure_list_fields(cls, value: Optional[Any]) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            result: List[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    result.append(text)
            return result
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        return []

    @field_validator("experience_level_years", mode="before")
    @classmethod
    def _ensure_experience_years(cls, value: Optional[Any]) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @field_validator("job_type", mode="before")
    @classmethod
    def _coerce_job_type(cls, value: Optional[Union[str, JobType]]) -> Optional[JobType]:
        if value is None or value == "":
            return None
        if isinstance(value, JobType):
            return value
        lowered = str(value).strip().lower().replace(" ", "_")
        mapping = {
            "full-time": JobType.full_time,
            "fulltime": JobType.full_time,
            "part-time": JobType.part_time,
            "parttime": JobType.part_time,
            "contractual": JobType.contract,
            "contract": JobType.contract,
            "temp": JobType.temporary,
            "temporary": JobType.temporary,
            "onsite": JobType.on_site,
            "on_site": JobType.on_site,
        }
        if lowered in mapping:
            return mapping[lowered]
        try:
            return JobType(lowered)
        except ValueError:
            return JobType.other


class JobDescriptionMessage(BaseModel):
    acknowledgement: str
    summary_sentence: str
    updates: List[str] = Field(default_factory=list)
    guidance: str
    recommended: List[str] = Field(default_factory=list)
    closing: str

    @field_validator("acknowledgement", "summary_sentence", "guidance", "closing", mode="before")
    @classmethod
    def _strip_and_validate(cls, value: Optional[str]) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("Message fields cannot be blank")
        return text

    @field_validator("updates", "recommended", mode="before")
    @classmethod
    def _ensure_list(cls, value: Optional[Union[str, List[str]]]) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            trimmed = value.strip()
            return [trimmed] if trimmed else []
        if isinstance(value, list):
            cleaned: List[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    cleaned.append(text)
            return cleaned
        raise ValueError("Expected a list of strings")

    def render_markdown(self) -> str:
        parts: List[str] = []
        lead = f"{self.acknowledgement} {self.summary_sentence}".strip()
        parts.append(lead)
        if self.updates:
            updates_body = "\n".join(f"- {item}" for item in self.updates if item)
            parts.append("**Updates captured**\n" + updates_body)
        parts.append(self.guidance)
        if self.recommended:
            recommended_body = "\n".join(
                f"{idx}. {item}" for idx, item in enumerate(self.recommended, start=1)
            )
            parts.append("**Recommended information**\n" + recommended_body)
        parts.append(self.closing)
        return "\n\n".join(section.strip() for section in parts if section.strip())


class JobDescriptionOutput(BaseModel):
    """Structured output from JobDescriptionCrew."""

    message: Optional[JobDescriptionMessage] = None
    message_md: str = ""
    jd: JobDescription = Field(default_factory=JobDescription)
    next_steps: Optional[str] = None
    phase: ConversationPhase = ConversationPhase.job_description

    @model_validator(mode="after")
    def _sync_message_markdown(self) -> "JobDescriptionOutput":
        if self.message and not self.message_md:
            self.message_md = self.message.render_markdown()
        return self


def format_outstanding_questions_md(questions: Sequence[str]) -> str:
    """Render outstanding requirement prompts as an ordered markdown list."""
    cleaned: List[str] = []
    seen = set()
    for item in questions:
        text = str(item).strip()
        if not text:
            continue
        lower = text.lower()
        if lower in seen:
            continue
        seen.add(lower)
        cleaned.append(text)
    if not cleaned:
        return ""
    return "\n".join(f"{idx}. {text}" for idx, text in enumerate(cleaned, start=1))


class JobDescriptionInput(BaseModel):
    """Structured payload sent to JobDescriptionCrew."""

    user_query: str = ""
    job_description: Optional[JobDescription] = None
    requirement_questions_md: Optional[str] = None
    phase: ConversationPhase = ConversationPhase.job_description

    @model_validator(mode="after")
    def _default_requirement_questions_md(self) -> "JobDescriptionInput":
        if not self.requirement_questions_md and self.job_description:
            self.requirement_questions_md = format_outstanding_questions_md(
                self.job_description.outstanding_questions
            )
        return self

class Scores(BaseModel):
    semantic_score: float = 0.0
    weighted_feature_score: float = 0.0
    feature_scores: Dict[str, float] = Field(default_factory=dict)
    job_fit_score: float
    similarity: Optional[float] = Field(default=None, ge=0.0)

class CandidateMatch(BaseModel):
    metadata: Metadata
    scores: Scores
    reasoning: Optional[str] = None


class CandidateRetrievalOutput(BaseModel):
    """Output of the retrieval agent containing scored candidates."""

    retrieval_md: str = ""
    candidates: List[CandidateMatch] = Field(default_factory=list)
    phase: ConversationPhase = ConversationPhase.screening


class MatchedFeature(BaseModel):
    matching_skills: List[str] = Field(default_factory=list)
    matching_education: List[str] = Field(default_factory=list)
    matching_experience: List[str] = Field(default_factory=list)
    matching_titles: List[str] = Field(default_factory=list)
    matching_other: List[str] = Field(default_factory=list)

class CandidateInsight(BaseModel):
    """Structured reasoning about an individual candidate."""
    metadata: Metadata
    scores: Scores
    summary_md: str
    fit_reasoning: List[str] = Field(default_factory=list)
    matched_features: MatchedFeature = Field(default_factory=MatchedFeature)
    knowledge_references: Dict[str, Any] = Field(default_factory=dict)


class CandidateAnalysisOutput(BaseModel):
    """Insights compiled from structured resume knowledge."""

    candidate_insights: List[CandidateInsight] = Field(default_factory=list)
    phase: ConversationPhase = ConversationPhase.screening


class CandidateScreeningOutput(BaseModel):
    """Output of ScreeningCrew."""

    message_md: str
    candidate_insights: List[CandidateInsight] = Field(default_factory=list)
    reasoning: Optional[str] = None
    database_summary_md: Optional[str] = None
    knowledge_records: List[Dict[str, Any]] = Field(default_factory=list)
    phase: ConversationPhase = ConversationPhase.screening



class ScreeningInput(BaseModel):
    """Structured payload sent to the ScreeningCrew."""

    user_query: str = ""
    job_snapshot: Optional[JobDescription] = None
    top_k: int = 5
    phase: ConversationPhase = ConversationPhase.screening
    session_id: Optional[str] = None
    scoring_weights: Dict[str, float] = Field(
        default_factory=lambda: DEFAULT_SCORING_WEIGHTS.copy()
    )
    feature_weights: Dict[str, float] = Field(
        default_factory=lambda: DEFAULT_FEATURE_WEIGHTS.copy()
    )

class DiscussionInput(BaseModel):
    """Structured payload sent to DiscussionCrew."""

    user_query: str = ""
    screened_candidates: Optional[CandidateAnalysisOutput] = None
    job_snapshot: Optional[JobDescription] = None
    phase: ConversationPhase = ConversationPhase.discussion

class DiscussionAnalysisOutput(BaseModel):
    """Analysis output from the discussion phase."""
    findings: str
    reasoning: str
    recommended_actions: List[str] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)

class DiscussionContent(BaseModel):
    """Content related to the discussion phase."""
    acknowledgement: str = ""
    query_answers: str = ""
    reasoning: str = ""
    follow_ups: str = ""
    closing: str = ""

class DiscussionOutput(BaseModel):
    """Structured output from DiscussionCrew."""
    message_md: DiscussionContent
    phase: ConversationPhase = ConversationPhase.discussion

class QueryControls(BaseModel):
    """Controls influencing query routing and crew behavior."""
    phase_sequence: List[Literal["job_description", "screening", "discussion"]] = Field(
        default_factory=list
    )
    last_completed_phase: Optional[Literal["job_description", "screening", "discussion"]] = None
    jd_complete: Optional[bool] = None
    allow_jd_incomplete: Optional[bool] = None
    update_jd: Optional[bool] = None
    screen_again: Optional[bool] = None
    new_job_search: Optional[bool] = None
    candidates_ready: Optional[bool] = None


class QueryRoutingOutput(BaseModel):
    """Defines the routing decision produced by QueryManagerCrew."""
    query_controls: QueryControls = Field(default_factory=QueryControls)
    cleaned_user_query: Optional[str] = None
    top_k_hint: Optional[int] = Field(default=None, ge=1)
    reasoning: Optional[str] = None

    @field_validator("query_controls", mode="before")
    @classmethod
    def _validate_query_controls(cls, value: Optional[Any]) -> QueryControls:
        if isinstance(value, dict):
            return QueryControls(**value)
        return QueryControls()

    @field_validator("cleaned_user_query", mode="before")
    @classmethod
    def _validate_cleaned_user_query(cls, value: Optional[Any]) -> Optional[str]:
        if isinstance(value, str):
            return value.strip() or None
        return None

    @field_validator("top_k_hint", mode="before")
    @classmethod
    def _validate_top_k_hint(cls, value: Optional[Any]) -> Optional[int]:
        if value is None:
            return None
        try:
            v = int(value)
            return v if v >= 1 else None
        except (ValueError, TypeError):
            return None

    @field_validator("reasoning", mode="before")
    @classmethod
    def _validate_reasoning(cls, value: Optional[Any]) -> Optional[str]:
        if isinstance(value, str):
            return value.strip() or None
        return None

class AppState(BaseModel):
    """Encapsulates the current state of the application relevant to query routing."""

    job_description: Optional[JobDescription] = None
    candidate_insights: List[CandidateInsight] = Field(default_factory=list)
    last_completed_phase: Optional[ConversationPhase] = None
    pending_phases: List[ConversationPhase] = Field(default_factory=list)
    query_controls: QueryControls = Field(default_factory=QueryControls)


class QueryRoutingInput(BaseModel):
    """Structured payload sent to QueryManagerCrew."""

    user_query: str = ""
    state: AppState = Field(default_factory=AppState)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None


def normalize_job_description_dict(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    jd = JobDescription()
    payload = jd.model_dump()
    for key in payload:
        if key in value and value[key] is not None:
            payload[key] = value[key]
    return payload


def normalise_scoring_weights(weights: Optional[Dict[str, Any]]) -> Dict[str, float]:
    allowed_keys = set(DEFAULT_SCORING_WEIGHTS.keys())
    result: Dict[str, float] = {}
    if isinstance(weights, dict) and "description" in weights and isinstance(weights.get("description"), dict):
        weights = weights["description"]
    if isinstance(weights, dict):
        for key, value in weights.items():
            key_str = str(key)
            if key_str not in allowed_keys:
                continue
            try:
                result[key_str] = float(value)
            except (TypeError, ValueError):
                continue
    return result or DEFAULT_SCORING_WEIGHTS.copy()


def normalise_feature_weights(weights: Optional[Dict[str, Any]]) -> Dict[str, float]:
    allowed_keys = set(DEFAULT_FEATURE_WEIGHTS.keys())
    result: Dict[str, float] = {}
    if isinstance(weights, dict) and "description" in weights and isinstance(weights.get("description"), dict):
        weights = weights["description"]
    if isinstance(weights, dict):
        for key, value in weights.items():
            key_str = str(key)
            if key_str not in allowed_keys:
                continue
            try:
                result[key_str] = float(value)
            except (TypeError, ValueError):
                continue
    return result or DEFAULT_FEATURE_WEIGHTS.copy()


__all__ = [
    "ConversationPhase",
    "ExperienceItem",
    "EducationItem",
    "SkillsSection",
    "ResumeContent",
    "Metadata",
    "Resume",
    "ResumeFileInfo",
    "JobType",
    "JobDescription",
    "JobDescriptionMessage",
    "JobDescriptionOutput",
    "JobDescriptionInput",
    "CandidateMatch",
    "CandidateRetrievalOutput",
    "CandidateInsight",
    "CandidateAnalysisOutput",
    "CandidateScreeningOutput",
    "ScreeningInput",
    "QueryControls",
    "QueryRoutingInput",
    "QueryRoutingOutput",
    "AppState",
    "DiscussionInput",
    "DiscussionAnalysisOutput",
    "DiscussionContent",
    "DiscussionOutput",
    "ChatMessage",
    "normalize_job_description_dict",
    "normalise_feature_weights",
    "normalise_scoring_weights",
]
