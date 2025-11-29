import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Type

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()
logger = logging.getLogger(__name__)

from crewai.tools import BaseTool

from resume_screening_rag_automation.models import (
    CandidateMatch,
    JobDescription,
    Metadata,
    ResumeContent,
    Scores,
    SkillsSection,
    normalise_feature_weights,
    normalise_scoring_weights,
    normalize_job_description_dict,
)
from resume_screening_rag_automation.paths import (
    PACKAGE_ROOT,
    PROJECT_ROOT,
    STRUCTURED_RESUMES_PATH,
)
from resume_screening_rag_automation.tools.search_resumes_tool import SearchResumesTool
from resume_screening_rag_automation.tools.constants import RESUME_COLLECTION_NAME
from resume_screening_rag_automation.core.constants import (
    DEFAULT_FEATURE_WEIGHTS,
    DEFAULT_SCORING_WEIGHTS,
)
from resume_screening_rag_automation.tools.vectorstore_utils import (
    ensure_chroma_client,
    get_embedding_function,
)

LEGACY_KNOWLEDGE_PATHS = (
    STRUCTURED_RESUMES_PATH,
    PACKAGE_ROOT / "knowledge" / "structured_resumes.json",
    PROJECT_ROOT / "structured_resumes.json",
)

FEATURE_WEIGHT_KEYS = ["skills", "experience", "education", "title", "other"]
SKILL_SIMILARITY_THRESHOLD = 0.45
EDUCATION_SIMILARITY_THRESHOLD = 0.4
EXPERIENCE_SIMILARITY_THRESHOLD = 0.4
TITLE_SIMILARITY_THRESHOLD = 0.35
OTHER_SIMILARITY_THRESHOLD = 0.4


def _resolve_knowledge_path() -> Optional[Path]:
    for candidate in LEGACY_KNOWLEDGE_PATHS:
        if candidate.exists():
            return candidate
    logger.warning(
        "Structured resumes file not found in any known location; expected one of: %s",
        ", ".join(str(path) for path in LEGACY_KNOWLEDGE_PATHS),
    )
    return None


def _load_structured_resumes() -> List[Dict[str, Any]]:
    path = _resolve_knowledge_path()
    if not path:
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read structured resumes: %s", exc)
        return []


def _index_resumes_by_id(resumes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for item in resumes:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata", {}) or {}
        candidate_id = str(meta.get("candidate_id") or "").strip()
        file_name = str(meta.get("file_name") or "").strip()
        if candidate_id:
            index[candidate_id] = item
        if file_name:
            index.setdefault(file_name, item)
    return index


def _remove_raw_text_field(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {
            key: _remove_raw_text_field(sub_value)
            for key, sub_value in value.items()
            if key.lower() != "raw_text"
        }
        return {key: sub_value for key, sub_value in cleaned.items() if sub_value not in (None, "", [], {}, ())}
    if isinstance(value, list):
        cleaned_list = [_remove_raw_text_field(item) for item in value]
        return [item for item in cleaned_list if item not in (None, "", [], {}, ())]
    if isinstance(value, tuple):
        cleaned_tuple = tuple(_remove_raw_text_field(item) for item in value)
        return tuple(item for item in cleaned_tuple if item not in (None, "", [], {}, ()))
    return value


def _build_metadata(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Metadata:
    merged = {**(fallback or {}), **(primary or {})}
    return Metadata.model_validate(merged)


def _normalize_resume_content_dict(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    normalized: Dict[str, Any] = {}

    summary = raw.get("summary")
    if isinstance(summary, str) and summary.strip():
        normalized["summary"] = summary.strip()

    raw_skills = raw.get("skills") or []
    if isinstance(raw_skills, list):
        skills = [str(skill).strip() for skill in raw_skills if str(skill).strip()]
        if skills:
            normalized["skills"] = skills

    experience_items: List[Dict[str, Any]] = []
    for exp in raw.get("experience") or []:
        if not isinstance(exp, dict):
            continue
        roles_src = exp.get("roles") or []
        roles = [str(role).strip() for role in roles_src if str(role).strip()]
        item = {
            "title": exp.get("title"),
            "company": exp.get("company"),
            "period": exp.get("period"),
            "location": exp.get("location"),
            "roles": roles,
        }
        if any(value for key, value in item.items() if key != "roles") or roles:
            experience_items.append(item)
    if experience_items:
        normalized["experience"] = experience_items

    education_items: List[Dict[str, Any]] = []
    for edu in raw.get("education") or []:
        if not isinstance(edu, dict):
            continue
        notes_src = edu.get("notes") or []
        notes = [str(note).strip() for note in notes_src if str(note).strip()]
        item = {
            "degree": edu.get("degree"),
            "institution": edu.get("institution"),
            "period": edu.get("period"),
            "notes": notes,
        }
        if any(value for key, value in item.items() if key != "notes") or notes:
            education_items.append(item)
    if education_items:
        normalized["education"] = education_items

    languages = raw.get("languages") or []
    if isinstance(languages, list):
        langs = [str(lang).strip() for lang in languages if str(lang).strip()]
        if langs:
            normalized["languages"] = langs

    other: Dict[str, Any] = {}
    for key, value in raw.items():
        lower_key = key.lower()
        if lower_key in {"summary", "experience", "skills", "education", "languages", "raw_text"}:
            continue
        cleaned_value = _remove_raw_text_field(value)
        if cleaned_value in (None, "", [], {}, ()):  # skip empty artifacts after cleaning
            continue
        other[key] = cleaned_value
    if other:
        normalized["other"] = other

    return normalized


def _build_resume_content(raw: Any) -> ResumeContent:
    if isinstance(raw, dict):
        try:
            normalized = _normalize_resume_content_dict(raw)
            if normalized:
                return ResumeContent.model_validate(normalized)
        except Exception:
            logger.debug("Resume content validation failed; falling back to empty content", exc_info=True)
    return ResumeContent()


def _normalise_term_key(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _compute_term_match(required: Iterable[str], available: Iterable[str]) -> tuple[float, List[str]]:
    req_map: Dict[str, str] = {}
    for item in required:
        if not isinstance(item, str):
            continue
        display = item.strip()
        key = _normalise_term_key(display)
        if key:
            req_map.setdefault(key, display)

    if not req_map:
        return 0.0, []

    avail_map: Dict[str, str] = {}
    for item in available:
        if not isinstance(item, str):
            continue
        display = item.strip()
        key = _normalise_term_key(display)
        if key:
            avail_map.setdefault(key, display)

    matched_keys: set[str] = set()
    for req_key in req_map.keys():
        for avail_key in avail_map.keys():
            if not avail_key:
                continue
            if req_key == avail_key or req_key in avail_key or avail_key in req_key:
                matched_keys.add(req_key)
                break

    matched_display = [req_map[key] for key in matched_keys]
    score = round(len(matched_keys) / len(req_map), 3)
    return score, matched_display


def _resume_text_corpus(content: ResumeContent) -> str:
    parts: List[str] = []

    def _add_text(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                parts.append(text)
            return
        if isinstance(value, (int, float, bool)):
            parts.append(str(value))
            return
        if isinstance(value, SkillsSection):
            _add_text(value.technical)
            _add_text(value.soft)
            return
        if isinstance(value, BaseModel):
            _add_text(value.model_dump())
            return
        if isinstance(value, dict):
            for item in value.values():
                _add_text(item)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _add_text(item)
            return
        text = str(value).strip()
        if text:
            parts.append(text)

    _add_text(content.title)
    _add_text(content.summary)
    _add_text(content.skills)
    for exp in content.experience:
        _add_text(exp.title)
        _add_text(exp.company)
        _add_text(exp.period)
        _add_text(exp.roles)
    for edu in content.education:
        _add_text(edu.degree)
        _add_text(edu.institution)
        _add_text(edu.period)
        _add_text(edu.notes)
    _add_text(content.languages)
    for key, value in (content.other or {}).items():
        _add_text(key)
        _add_text(value)

    return " ".join(parts).lower()


def _augment_skill_matches(required: Iterable[str], content: ResumeContent, matched: Iterable[str]) -> List[str]:
    corpus = _resume_text_corpus(content)
    if not corpus:
        return []
    corpus_lower = corpus.lower()
    corpus_compact = re.sub(r"[^a-z0-9]", "", corpus_lower)
    corpus_tokens = set(_tokenize(corpus_lower))
    already = {_normalise_term_key(skill) for skill in matched if isinstance(skill, str)}
    additional: List[str] = []
    for skill in required:
        if not isinstance(skill, str):
            continue
        normalized = skill.strip()
        if not normalized:
            continue
        key = _normalise_term_key(normalized)
        if not key or key in already:
            continue
        lowered = normalized.lower()
        skill_tokens = set(_tokenize(lowered))
        if (lowered and lowered in corpus_lower) or (key and key in corpus_compact):
            additional.append(normalized)
            already.add(key)
            continue
        if skill_tokens and skill_tokens.issubset(corpus_tokens):
            additional.append(normalized)
            already.add(key)
            continue
    return additional


def _collect_education_terms(content: ResumeContent) -> List[str]:
    terms: List[str] = []
    for edu in content.education:
        if edu.degree:
            text = str(edu.degree).strip()
            if text:
                terms.append(text)
        if edu.institution:
            text = str(edu.institution).strip()
            if text:
                terms.append(text)
        for note in getattr(edu, "notes", []) or []:
            text = str(note).strip()
            if text:
                terms.append(text)
    return terms


def _dedupe_terms(terms: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    deduped: List[str] = []
    for term in terms:
        if not isinstance(term, str):
            continue
        text = term.strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _collect_skill_terms(content: ResumeContent) -> List[str]:
    terms: List[str] = []
    skills = content.skills
    if isinstance(skills, SkillsSection):
        terms.extend(skills.technical)
        terms.extend(skills.soft)
    elif isinstance(skills, list):
        terms.extend(str(item) for item in skills)
    return _dedupe_terms(terms)


def _collect_experience_terms(content: ResumeContent) -> List[str]:
    terms: List[str] = []
    for exp in content.experience:
        if exp.title:
            terms.append(exp.title)
        if exp.company:
            terms.append(exp.company)
        if exp.period:
            terms.append(exp.period)
        terms.extend(exp.roles)
    return _dedupe_terms(terms)


def _collect_title_terms(metadata: Metadata, content: ResumeContent) -> List[str]:
    terms: List[str] = []
    if metadata.current_title:
        terms.append(metadata.current_title)
    if content.title:
        terms.append(content.title)
    for exp in content.experience:
        if exp.title:
            terms.append(exp.title)
    return _dedupe_terms(terms)


def _collect_other_terms(content: ResumeContent) -> List[str]:
    terms: List[str] = []
    if content.summary:
        terms.append(content.summary)
    terms.extend(content.languages)
    for key, value in (content.other or {}).items():
        if isinstance(key, str) and key.strip():
            terms.append(key)
        if isinstance(value, str):
            terms.append(value)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, str):
                    terms.append(item)
        elif isinstance(value, dict):
            for item in value.values():
                if isinstance(item, str):
                    terms.append(item)
    return _dedupe_terms(terms)


class FeatureEvaluation(NamedTuple):
    score: float
    matches: List[str]
    similarity_map: Dict[str, float]


def _evaluate_semantic_alignment(
    requirements: Iterable[str],
    candidate_terms: Iterable[str],
    metadata: Metadata,
    candidate_key: str,
    semantic_collection: Optional[Any],
    threshold: float,
    label: str,
) -> FeatureEvaluation:
    queries = [item.strip() for item in requirements if isinstance(item, str) and item.strip()]
    if not queries:
        return FeatureEvaluation(0.0, [], {})

    matched, similarity_map = _semantic_requirement_similarity(
        requirements=queries,
        metadata=metadata,
        candidate_key=candidate_key,
        collection=semantic_collection,
        threshold=threshold,
        label=label,
    )
    matched = list(dict.fromkeys(matched))

    if similarity_map:
        average_similarity = sum(similarity_map.get(query, 0.0) for query in queries) / len(queries)
        coverage_ratio = _term_coverage_ratio(queries, matched)
        score = max(average_similarity, coverage_ratio)
        score = round(min(max(score, 0.0), 1.0), 3)
        return FeatureEvaluation(score, matched, similarity_map)

    fallback_terms = [item.strip() for item in candidate_terms if isinstance(item, str) and item.strip()]
    fallback_score, fallback_matches = _compute_term_match(queries, fallback_terms)
    coverage_ratio = _term_coverage_ratio(queries, fallback_matches)
    score = max(fallback_score, coverage_ratio)
    score = round(min(max(score, 0.0), 1.0), 3)
    matched_terms = list(dict.fromkeys(fallback_matches))
    return FeatureEvaluation(score, matched_terms, {})


def _term_coverage_ratio(required: Iterable[str], matched: Iterable[str]) -> float:
    required_keys = {
        _normalise_term_key(item)
        for item in required
        if isinstance(item, str) and _normalise_term_key(item)
    }
    if not required_keys:
        return 0.0
    matched_keys = {
        _normalise_term_key(item)
        for item in matched
        if isinstance(item, str) and _normalise_term_key(item)
    }
    if not matched_keys:
        return 0.0
    covered = required_keys & matched_keys
    return round(len(covered) / len(required_keys), 3)


def _candidate_lookup_filters(metadata: Metadata, fallback_candidate_key: str) -> List[Dict[str, str]]:
    filters: List[Dict[str, str]] = []
    candidate_id = (metadata.candidate_id or "").strip()
    if candidate_id:
        filters.append({"candidate_id": candidate_id})
    file_name = (metadata.file_name or "").strip()
    if file_name and file_name != candidate_id:
        filters.append({"file_name": file_name})
    fallback = fallback_candidate_key.strip()
    if fallback:
        values = {value for item in filters for value in item.values()}
        if fallback not in values:
            filters.append({"candidate_id": fallback})
    if not filters:
        filters.append({})
    return filters


def _semantic_requirement_similarity(
    requirements: Iterable[str],
    metadata: Metadata,
    candidate_key: str,
    collection: Optional[Any],
    threshold: float,
    label: str,
) -> tuple[List[str], Dict[str, float]]:
    if collection is None:
        return [], {}
    queries = [item.strip() for item in requirements if isinstance(item, str) and item.strip()]
    if not queries:
        return [], {}

    filters = _candidate_lookup_filters(metadata, candidate_key)
    similarity_map: Dict[str, float] = {item: 0.0 for item in queries}

    for where in filters:
        try:
            result = collection.query(
                query_texts=queries,
                n_results=1,
                where=where,
                include=["distances"],
            )
        except Exception:  # pragma: no cover - defensive, fall back to lexical matching later
            logger.debug(
                "Semantic %s query failed for %s with filter %s",
                label,
                candidate_key,
                where,
                exc_info=True,
            )
            continue

        distances_matrix = result.get("distances") or []
        if not distances_matrix:
            continue

        for idx, query in enumerate(queries):
            distances = distances_matrix[idx] if idx < len(distances_matrix) else []
            if not distances:
                continue
            similarity = _compute_similarity_score(distances[0])
            if similarity > similarity_map.get(query, 0.0):
                similarity_map[query] = similarity

    matched = [query for query, score in similarity_map.items() if score >= threshold]
    return matched, similarity_map


def _semantic_skill_similarity(
    required: Iterable[str],
    metadata: Metadata,
    candidate_key: str,
    collection: Optional[Any],
) -> tuple[List[str], Dict[str, float]]:
    return _semantic_requirement_similarity(
        requirements=required,
        metadata=metadata,
        candidate_key=candidate_key,
        collection=collection,
        threshold=SKILL_SIMILARITY_THRESHOLD,
        label="skill",
    )


def _semantic_education_similarity(
    required: Iterable[str],
    metadata: Metadata,
    candidate_key: str,
    collection: Optional[Any],
) -> tuple[List[str], Dict[str, float]]:
    return _semantic_requirement_similarity(
        requirements=required,
        metadata=metadata,
        candidate_key=candidate_key,
        collection=collection,
        threshold=EDUCATION_SIMILARITY_THRESHOLD,
        label="education",
    )


def _compute_similarity_score(distance: Optional[float]) -> float:
    if distance is None:
        return 0.0
    try:
        dist = float(distance)
    except (TypeError, ValueError):
        return 0.0
    if dist < 0:
        dist = 0.0
    if dist <= 2:
        similarity = max(0.0, 1.0 - dist)
    else:
        similarity = 1.0 / (1.0 + dist)
    return round(min(1.0, similarity), 3)


def _tokenize(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _experience_corpus(content: ResumeContent) -> str:
    parts: List[str] = []
    for exp in content.experience:
        if exp.title:
            parts.append(exp.title)
        if exp.company:
            parts.append(exp.company)
        if exp.period:
            parts.append(exp.period)
        parts.extend(exp.roles)
    return " ".join(parts).lower()


def _education_corpus(content: ResumeContent) -> str:
    parts: List[str] = []
    for edu in content.education:
        if edu.degree:
            parts.append(edu.degree)
        if edu.institution:
            parts.append(edu.institution)
        if edu.period:
            parts.append(edu.period)
        parts.extend(edu.notes)
    return " ".join(parts).lower()


def _compute_experience_score(
    responsibilities: Iterable[str],
    content: ResumeContent,
    section_scores: Dict[str, float],
) -> float:
    responsibilities_list = [item for item in responsibilities if isinstance(item, str) and item.strip()]
    if not responsibilities_list:
        return 1.0 if content.experience else max(section_scores.get("EXPERIENCE", 0.0), 0.0)
    corpus = _experience_corpus(content)
    if not corpus:
        return round(section_scores.get("EXPERIENCE", 0.0), 3)
    matches = sum(1 for item in responsibilities_list if item.lower() in corpus)
    ratio = matches / len(responsibilities_list) if responsibilities_list else 0.0
    return round(min(1.0, max(ratio, section_scores.get("EXPERIENCE", 0.0))), 3)


def _compute_education_score(
    requirements: Iterable[str],
    content: ResumeContent,
    section_scores: Dict[str, float],
) -> float:
    requirements_list = [item for item in requirements if isinstance(item, str) and item.strip()]
    if not requirements_list:
        return 1.0 if content.education else round(section_scores.get("EDUCATION", 0.0), 3)
    corpus = _education_corpus(content)
    if not corpus:
        return round(section_scores.get("EDUCATION", 0.0), 3)
    matches = sum(1 for item in requirements_list if item.lower() in corpus)
    ratio = matches / len(requirements_list) if requirements_list else 0.0
    return round(min(1.0, max(ratio, section_scores.get("EDUCATION", 0.0))), 3)


def _compute_title_score(job_title: Optional[str], metadata: Metadata, content: ResumeContent) -> float:
    job_tokens = set(_tokenize(job_title))
    if not job_tokens:
        return 0.0
    candidate_tokens: set[str] = set()
    candidate_tokens.update(_tokenize(getattr(metadata, "current_title", None)))
    candidate_tokens.update(_tokenize(content.title))
    if not candidate_tokens:
        return 0.0
    overlap = job_tokens & candidate_tokens
    if not overlap:
        return 0.0
    return round(len(overlap) / len(job_tokens), 3)


def _compute_other_requirements_score(
    certifications: Iterable[str],
    extras: Optional[str],
    languages: Iterable[str],
    content: ResumeContent,
    section_scores: Dict[str, float],
    resume_text: Optional[str],
) -> float:
    summary_score = section_scores.get("SUMMARY", 0.0)
    other_sections = [
        "CERTIFICATIONS",
        "TRAINING",
        "COURSES",
        "PROJECTS",
        "ACHIEVEMENTS",
        "LANGUAGES",
    ]
    section_peek = max((section_scores.get(section, 0.0) for section in other_sections), default=0.0)

    requirements: List[str] = []
    for item in certifications:
        text = str(item).strip()
        if text:
            requirements.append(text)
    for item in languages:
        text = str(item).strip()
        if text:
            requirements.append(text)
    if extras:
        requirements.append(extras)

    if not requirements:
        base = max(summary_score, section_peek)
        return round(base, 3)

    corpus_parts = [_resume_text_corpus(content)]
    if resume_text:
        corpus_parts.append(resume_text.lower())
    corpus = " ".join(part for part in corpus_parts if part)
    if not corpus:
        return round(max(summary_score, section_peek), 3)

    requirement_tokens = [token for item in requirements for token in _tokenize(item)]
    requirement_tokens = [token for token in requirement_tokens if token]
    if not requirement_tokens:
        base = max(summary_score, section_peek)
        return round(base, 3)

    matches = sum(1 for token in requirement_tokens if token in corpus)
    ratio = matches / len(requirement_tokens) if requirement_tokens else 0.0
    base = max(summary_score, section_peek, ratio)
    if base == 0.0 and (content.summary or content.other):
        base = 0.2
    return round(min(1.0, base), 3)


def _summarise_alignment(values: Iterable[str], limit: int = 3) -> Optional[str]:
    cleaned = [str(item).strip() for item in values if isinstance(item, str) and str(item).strip()]
    if not cleaned:
        return None
    display = cleaned[:limit]
    summary = ", ".join(display)
    if len(cleaned) > limit:
        summary += ", ..."
    return summary


def _compose_reasoning(
    skill_alignment: float,
    matched_skills: Iterable[str],
    similarity: Optional[float] = None,
    matched_education: Optional[Iterable[str]] = None,
    matched_experience: Optional[Iterable[str]] = None,
    matched_titles: Optional[Iterable[str]] = None,
    matched_other: Optional[Iterable[str]] = None,
) -> Optional[str]:
    parts: List[str] = []
    skills_summary = _summarise_alignment(matched_skills)
    if skills_summary:
        parts.append(f"Skills: {skills_summary}")
    education_summary = _summarise_alignment(matched_education or [])
    if education_summary:
        parts.append(f"Education: {education_summary}")
    experience_summary = _summarise_alignment(matched_experience or [])
    if experience_summary:
        parts.append(f"Experience: {experience_summary}")
    title_summary = _summarise_alignment(matched_titles or [], limit=2)
    if title_summary:
        parts.append(f"Titles: {title_summary}")
    other_summary = _summarise_alignment(matched_other or [], limit=2)
    if other_summary:
        parts.append(f"Other: {other_summary}")
    if skill_alignment > 0:
        parts.append(f"Skill fit ≈ {skill_alignment:.0%}")
    if similarity is not None and similarity > 0:
        parts.append(f"Vector relevance ≈ {similarity:.0%}")
    return ". ".join(parts) if parts else None


def _resume_has_content(content: ResumeContent) -> bool:
    if not isinstance(content, ResumeContent):
        return False
    return any(
        (
            bool(content.summary and content.summary.strip()),
            bool(content.skills),
            bool(content.experience),
            bool(content.education),
            bool(content.languages),
            bool(content.other),
        )
    )


class ExtractCandidatesInput(BaseModel):
    job_description: Dict[str, Any] = Field(..., description="Job description dict")
    top_k: int = Field(5, description="Number of candidates to return")
    scoring_weights: Dict[str, float] = Field(default_factory=dict)
    feature_weights: Dict[str, float] = Field(default_factory=dict)

    @field_validator("top_k", mode="before")
    @classmethod
    def _ensure_positive_top_k(cls, value: Any) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = 5
        return max(1, numeric)

    @field_validator("scoring_weights", "feature_weights", mode="before")
    @classmethod
    def _coerce_mapping(cls, value: Any) -> Dict[str, float]:
        if value in (None, "", [], {}):
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {}
        if isinstance(value, dict):
            return value
        return {}


class ExtractCandidatesTool(BaseTool):
    name: str = "Extract Candidates"
    description: str = "Convert the job description into a query, search resumes, and return scored candidates"
    args_schema: Type[BaseModel] = ExtractCandidatesInput
    search_tool: SearchResumesTool = Field(
        default_factory=SearchResumesTool,
        exclude=True,
        description="Internal handle to the semantic search tool so we rely on a single implementation.",
    )

    def _run(
        self,
        job_description: Dict[str, Any],
        top_k: int = 5,
        collection_name: str = RESUME_COLLECTION_NAME,
        scoring_weights: Optional[Dict[str, float]] = None,
        feature_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        top_k = self._normalise_top_k(top_k)
        logger.info(
            "ExtractCandidatesTool running top_k=%s collection=%s", top_k, collection_name
        )
        job_description = self._unwrap_schema_wrapper(job_description)
        scoring_weights = self._unwrap_schema_wrapper(scoring_weights)
        feature_weights = self._unwrap_schema_wrapper(feature_weights)

        clean_jd = normalize_job_description_dict(job_description)
        jd = JobDescription.model_validate(clean_jd)
        scoring_weights = normalise_scoring_weights(scoring_weights or DEFAULT_SCORING_WEIGHTS)
        feature_weights = normalise_feature_weights(feature_weights or DEFAULT_FEATURE_WEIGHTS)
        required_skills = [
            skill.strip()
            for skill in (jd.required_skills or [])
            if isinstance(skill, str) and skill.strip()
        ]
        education_requirements = [
            requirement.strip()
            for requirement in (jd.education_requirements or [])
            if isinstance(requirement, str) and requirement.strip()
        ]
        responsibilities = [
            item.strip()
            for item in (jd.job_responsibilities or [])
            if isinstance(item, str) and item.strip()
        ]
        extras_text = str(jd.extra_requirements or "").strip()
        certification_requirements = [
            cert.strip()
            for cert in (jd.certification_requirements or [])
            if isinstance(cert, str) and cert.strip()
        ]
        language_requirements = [
            lang.strip()
            for lang in (jd.language_requirements or [])
            if isinstance(lang, str) and lang.strip()
        ]
        job_title_requirements = [
            jd.job_title.strip()
        ] if isinstance(jd.job_title, str) and jd.job_title.strip() else []
        other_requirements = certification_requirements + language_requirements
        if extras_text:
            other_requirements.append(extras_text)
        experience_years = jd.experience_level_years
        logger.debug(
            "ExtractCandidatesTool job_description keys=%s responsibilities_count=%s",
            list((job_description or {}).keys()),
            len(responsibilities),
        )
        education_text = "; ".join(education_requirements) if education_requirements else ""
        responsibilities_text = "; ".join(responsibilities) if responsibilities else "unspecified"
        skills_text = ", ".join(required_skills) if required_skills else "unspecified"
        query_text = (
            f"Job: {jd.job_title or ''}. "
            f"Skills: {skills_text}. "
            f"Location: {jd.location or ''}. "
            f"Responsibilities: {responsibilities_text}. "
            f"Education: {education_text or 'unspecified'}. "
            f"Experience: {experience_years or 'unspecified'} years. "
            f"Extras: {extras_text or 'unspecified'}."
        ).strip()
        logger.debug("ExtractCandidatesTool query_preview=%s", query_text[:200])

        search_top_k = max(top_k * 3, top_k + 2)
        search_out = self.search_tool.run(
            query=query_text,
            top_k=search_top_k,
            collection_name=collection_name,
        )
        if 'error' in search_out:
            logger.error("ExtractCandidatesTool search error: %s", search_out['error'])
            return search_out
        if search_out.get('warning'):
            logger.warning("ExtractCandidatesTool search warning: %s", search_out['warning'])

        hits = search_out.get('hits', [])
        resumes = _load_structured_resumes()
        resumes_by_id = _index_resumes_by_id(resumes)

        aggregated: Dict[str, CandidateMatch] = {}
        similarity_scores: Dict[str, float] = {}
        section_scores_by_candidate: Dict[str, Dict[str, float]] = defaultdict(dict)
        resume_by_candidate: Dict[str, ResumeContent] = {}
        resume_text_by_candidate: Dict[str, Optional[str]] = {}

        semantic_collection: Optional[Any] = None
        needs_semantic_collection = any(
            (
                required_skills,
                education_requirements,
                responsibilities,
                job_title_requirements,
                other_requirements,
            )
        )
        if needs_semantic_collection:
            try:
                chroma_client = ensure_chroma_client()
                embedding_function = get_embedding_function(self.search_tool.embedding_model)
                semantic_collection = chroma_client.get_or_create_collection(
                    collection_name,
                    embedding_function=embedding_function,
                )
            except Exception:  # pragma: no cover - fall back to lexical scoring if Chroma lookup fails
                logger.warning(
                    "Unable to initialise semantic collection for requirement scoring; falling back to lexical match",
                    exc_info=True,
                )
                semantic_collection = None

        for hit in hits:
            meta = hit.get('metadata', {}) or {}
            lookup_keys = [
                str(meta.get('candidate_id') or '').strip(),
                str(meta.get('file_name') or '').strip(),
                str(hit.get('id') or '').strip(),
            ]

            resume_obj: Optional[Dict[str, Any]] = None
            primary_meta: Dict[str, Any] = {}
            for key in lookup_keys:
                if not key:
                    continue
                resume_obj = resumes_by_id.get(key)
                if resume_obj:
                    primary_meta = resume_obj.get('metadata', {}) or {}
                    break

            metadata = _build_metadata(primary_meta, meta)
            content = _build_resume_content((resume_obj or {}).get('content'))
            resume_text = hit.get('document') or (resume_obj or {}).get('raw_text')

            candidate_key = (
                metadata.candidate_id
                or metadata.file_name
                or str(hit.get('id') or '').strip()
            )
            if not candidate_key:
                candidate_key = f"candidate_{len(aggregated)}"

            similarity = _compute_similarity_score(hit.get('distance'))

            existing = aggregated.get(candidate_key)
            if existing:
                existing_resume = resume_by_candidate.get(candidate_key)
                if _resume_has_content(content) and not _resume_has_content(existing_resume or ResumeContent()):
                    resume_by_candidate[candidate_key] = content
                stored_text = resume_text_by_candidate.get(candidate_key) or ""
                if resume_text and len(resume_text) > len(stored_text):
                    resume_text_by_candidate[candidate_key] = resume_text
                merged_meta = existing.metadata.model_dump(exclude_none=True)
                merged_meta.update({
                    key: value
                    for key, value in metadata.model_dump(exclude_none=True).items()
                    if value is not None
                })
                existing.metadata = Metadata.model_validate(merged_meta)
            else:
                aggregated[candidate_key] = CandidateMatch(
                    metadata=metadata,
                    scores=Scores(job_fit_score=0.0),
                    reasoning=None,
                )
                resume_by_candidate[candidate_key] = content
                resume_text_by_candidate[candidate_key] = resume_text

            similarity_scores[candidate_key] = max(similarity_scores.get(candidate_key, 0.0), similarity)

            section_name = str(meta.get('section') or '').upper()
            if section_name:
                current = section_scores_by_candidate[candidate_key].get(section_name, 0.0)
                section_scores_by_candidate[candidate_key][section_name] = max(current, similarity)

        ranked_candidates: List[CandidateMatch] = []
        for key, candidate in aggregated.items():
            similarity = similarity_scores.get(key, 0.0)
            section_scores = section_scores_by_candidate.setdefault(key, {})
            resume_content = resume_by_candidate.get(key) or ResumeContent()
            resume_text = resume_text_by_candidate.get(key) or ""

            skill_terms = _collect_skill_terms(resume_content)
            skills_eval = _evaluate_semantic_alignment(
                required_skills,
                skill_terms,
                candidate.metadata,
                key,
                semantic_collection,
                SKILL_SIMILARITY_THRESHOLD,
                "skill",
            )
            if skills_eval.similarity_map:
                section_scores["SKILLS"] = max(
                    section_scores.get("SKILLS", 0.0),
                    max(skills_eval.similarity_map.values()),
                )
            matched_skills = list(skills_eval.matches)
            if required_skills:
                matched_skills.extend(
                    _augment_skill_matches(required_skills, resume_content, matched_skills)
                )
            matched_skills = list(dict.fromkeys(matched_skills))
            skills_feature_score = max(skills_eval.score, section_scores.get("SKILLS", 0.0))
            if required_skills:
                augmented_coverage = _term_coverage_ratio(required_skills, matched_skills)
                skills_feature_score = max(skills_feature_score, augmented_coverage)
            skills_feature_score = round(min(max(skills_feature_score, 0.0), 1.0), 3)

            education_terms = _collect_education_terms(resume_content)
            education_eval = _evaluate_semantic_alignment(
                education_requirements,
                education_terms,
                candidate.metadata,
                key,
                semantic_collection,
                EDUCATION_SIMILARITY_THRESHOLD,
                "education",
            )
            if education_eval.similarity_map:
                section_scores["EDUCATION"] = max(
                    section_scores.get("EDUCATION", 0.0),
                    max(education_eval.similarity_map.values()),
                )
            matched_education = list(education_eval.matches)
            education_base = _compute_education_score(
                education_requirements,
                resume_content,
                section_scores,
            )
            education_feature_score = max(education_base, education_eval.score)
            education_feature_score = round(min(max(education_feature_score, 0.0), 1.0), 3)

            experience_terms = _collect_experience_terms(resume_content)
            experience_eval = _evaluate_semantic_alignment(
                responsibilities,
                experience_terms,
                candidate.metadata,
                key,
                semantic_collection,
                EXPERIENCE_SIMILARITY_THRESHOLD,
                "experience",
            )
            if experience_eval.similarity_map:
                section_scores["EXPERIENCE"] = max(
                    section_scores.get("EXPERIENCE", 0.0),
                    max(experience_eval.similarity_map.values()),
                )
            matched_experience = list(experience_eval.matches)
            if len(matched_experience) > 5:
                matched_experience = matched_experience[:5]
            experience_base = _compute_experience_score(
                responsibilities,
                resume_content,
                section_scores,
            )
            experience_feature_score = max(experience_base, experience_eval.score)
            experience_feature_score = round(min(max(experience_feature_score, 0.0), 1.0), 3)

            title_terms = _collect_title_terms(candidate.metadata, resume_content)
            title_eval = _evaluate_semantic_alignment(
                job_title_requirements,
                title_terms,
                candidate.metadata,
                key,
                semantic_collection,
                TITLE_SIMILARITY_THRESHOLD,
                "title",
            )
            if title_eval.similarity_map:
                section_scores["TITLE"] = max(
                    section_scores.get("TITLE", 0.0),
                    max(title_eval.similarity_map.values()),
                )
            matched_titles = list(title_eval.matches)
            title_base = _compute_title_score(jd.job_title, candidate.metadata, resume_content)
            title_feature_score = max(title_base, title_eval.score)
            title_feature_score = round(min(max(title_feature_score, 0.0), 1.0), 3)

            other_terms = _collect_other_terms(resume_content)
            other_eval = _evaluate_semantic_alignment(
                other_requirements,
                other_terms,
                candidate.metadata,
                key,
                semantic_collection,
                OTHER_SIMILARITY_THRESHOLD,
                "other",
            )
            if other_eval.similarity_map:
                section_scores["OTHER"] = max(
                    section_scores.get("OTHER", 0.0),
                    max(other_eval.similarity_map.values()),
                )
            matched_other = list(other_eval.matches)
            if len(matched_other) > 5:
                matched_other = matched_other[:5]
            other_base = _compute_other_requirements_score(
                certification_requirements,
                extras_text,
                language_requirements,
                resume_content,
                section_scores,
                resume_text,
            )
            other_feature_score = max(other_base, other_eval.score)
            other_feature_score = round(min(max(other_feature_score, 0.0), 1.0), 3)

            feature_scores = {
                "skills": skills_feature_score,
                "experience": experience_feature_score,
                "education": education_feature_score,
                "title": title_feature_score,
                "other": other_feature_score,
            }
            weighted_feature_score = sum(
                feature_weights.get(feature, 0.0) * feature_scores.get(feature, 0.0)
                for feature in FEATURE_WEIGHT_KEYS
            )
            combined_score = (
                scoring_weights.get("semantic", 0.0) * similarity
                + scoring_weights.get("feature", 0.0) * weighted_feature_score
            )
            combined_score = min(1.0, max(0.0, combined_score))

            candidate.scores = Scores(
                semantic_score=round(similarity, 3),
                weighted_feature_score=round(weighted_feature_score, 3),
                feature_scores={name: round(value, 3) for name, value in feature_scores.items()},
                job_fit_score=round(combined_score, 3),
                similarity=round(similarity, 3),
            )
            candidate.reasoning = _compose_reasoning(
                skills_feature_score,
                matched_skills,
                similarity,
                matched_education,
                matched_experience,
                matched_titles,
                matched_other,
            )
            ranked_candidates.append(candidate)

        ranked_candidates.sort(
            key=lambda item: getattr(item.scores, "job_fit_score", 0.0),
            reverse=True,
        )
        limited_candidates = ranked_candidates[:top_k]
        limited = [candidate.model_dump() for candidate in limited_candidates]
        logger.info("ExtractCandidatesTool produced %s unique candidates", len(limited))
        return {
            "candidates": limited,
            "scoring_weights": scoring_weights,
            "feature_weights": feature_weights,
        }

    @staticmethod
    def _normalise_top_k(raw_top_k: Any) -> int:
        try:
            numeric = int(raw_top_k)
        except (TypeError, ValueError):
            numeric = 5
        return max(1, numeric)

    @staticmethod
    def _unwrap_schema_wrapper(payload: Optional[Any]) -> Optional[Any]:
        """Strip CrewAI tool schema wrappers that may surround payload dicts."""

        if isinstance(payload, dict) and "description" in payload:
            description = payload.get("description")
            if isinstance(description, dict):
                return description
        return payload
