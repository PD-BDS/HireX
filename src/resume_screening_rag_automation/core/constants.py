"""Shared constant values used across services."""

from __future__ import annotations

from typing import Dict, Tuple

# === Crew LLM Configuration ===
JOB_DESCRIPTION_CREW_MODEL = "gpt-4o-mini"
JOB_DESCRIPTION_CREW_TEMPERATURE = 0.5

SCREENING_CREW_MODEL = "gpt-4o-mini"
SCREENING_CREW_TEMPERATURE = 0.5

QUERY_MANAGER_CREW_MODEL = "gpt-4o-mini"
QUERY_MANAGER_CREW_TEMPERATURE = 0.5

DISCUSSION_CREW_MODEL = "gpt-4o-mini"
DISCUSSION_CREW_TEMPERATURE = 0.5

RESUME_PARSING_CREW_MODEL = "gpt-4o-mini"
RESUME_PARSING_CREW_TEMPERATURE = 0.0

# === Embedding Configuration ===
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
MAX_EMBED_CHARS = 18_000  # safeguard for char-based truncation before token trim
MAX_EMBED_TOKENS = 7_000  # stay below OpenAI's 8k token ceiling with buffer

# === Job Field Metadata ===
CORE_JOB_FIELDS: Tuple[str, ...] = (
    "job_title",
    "required_skills",
    "job_responsibilities",
    "experience_level_years",
    "location",
    "education_requirements",
)

OPTIONAL_JOB_FIELDS: Tuple[str, ...] = (
    "job_type",
    "language_requirements",
    "certification_requirements",
    "extra_requirements",
)

JOB_FIELD_LABELS: Dict[str, str] = {
    "job_title": "Job title",
    "location": "Location",
    "experience_level_years": "Experience (years)",
    "required_skills": "Required skills",
    "job_responsibilities": "Responsibilities",
    "education_requirements": "Education",
    "extra_requirements": "Additional notes",
    "job_type": "Job type",
    "language_requirements": "Language requirements",
    "certification_requirements": "Certification requirements",
}

JOB_FIELD_PROMPTS: Dict[str, str] = {
    "job_title": "What is the job title for this role?",
    "required_skills": "Which core skills should candidates have?",
    "job_responsibilities": "What are the primary responsibilities for this role?",
    "experience_level_years": "How many years of experience are required?",
    "location": "Where will the candidate be based (or is the role remote)?",
    "education_requirements": "Are there any education requirements?",
    "extra_requirements": "Any additional preferences or nice-to-haves?",
    "job_type": "What is the job type (e.g., full-time, contract)?",
    "language_requirements": "Should candidates speak specific languages?",
    "certification_requirements": "Any certifications required or preferred?",
}

# === Screening Scoring Defaults ===
DEFAULT_SCORING_WEIGHTS: Dict[str, float] = {
    "semantic": 0.7,
    "feature": 0.3,
}

DEFAULT_FEATURE_WEIGHTS: Dict[str, float] = {
    "skills": 0.35,
    "experience": 0.3,
    "education": 0.1,
    "title": 0.15,
    "other": 0.1,
}

__all__ = [
    # Crew LLM configuration
    "JOB_DESCRIPTION_CREW_MODEL",
    "JOB_DESCRIPTION_CREW_TEMPERATURE",
    "SCREENING_CREW_MODEL",
    "SCREENING_CREW_TEMPERATURE",
    "QUERY_MANAGER_CREW_MODEL",
    "QUERY_MANAGER_CREW_TEMPERATURE",
    "DISCUSSION_CREW_MODEL",
    "DISCUSSION_CREW_TEMPERATURE",
    "RESUME_PARSING_CREW_MODEL",
    "RESUME_PARSING_CREW_TEMPERATURE",
    # Embedding configuration
    "DEFAULT_EMBEDDING_MODEL",
    "MAX_EMBED_CHARS",
    "MAX_EMBED_TOKENS",
    # Job field metadata
    "CORE_JOB_FIELDS",
    "OPTIONAL_JOB_FIELDS",
    "JOB_FIELD_LABELS",
    "JOB_FIELD_PROMPTS",
    # Screening defaults
    "DEFAULT_SCORING_WEIGHTS",
    "DEFAULT_FEATURE_WEIGHTS",
]
