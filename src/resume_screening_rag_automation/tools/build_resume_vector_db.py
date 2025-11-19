import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()
logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

from crewai.tools import BaseTool

from resume_screening_rag_automation.paths import (
    CHROMA_VECTOR_DIR,
    STRUCTURED_RESUMES_PATH,
)
from resume_screening_rag_automation.tools.constants import RESUME_COLLECTION_NAME
from resume_screening_rag_automation.tools.vectorstore_utils import (
    CHROMADB_AVAILABLE,
    DEFAULT_EMBEDDING_MODEL,
    ensure_chroma_client,
    get_embedding_function,
)

KNOWLEDGE_JSON = STRUCTURED_RESUMES_PATH


def _load_structured_resumes(path: Path = KNOWLEDGE_JSON) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Unable to read structured resumes JSON from %s", path)
        return []
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        logger.exception("Invalid JSON in %s", path)
        return []
    if not isinstance(data, list):
        logger.error("Structured resumes JSON must be a list of resume records")
        return []
    return data


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _build_base_metadata(raw: Dict[str, Any]) -> Dict[str, Any]:
    md = raw.get("metadata", {}) or {}
    file_name = _normalize_text(md.get("file_name")) or None
    candidate_id = _normalize_text(md.get("candidate_id")) or file_name
    candidate_name = _normalize_text(md.get("candidate_name")) or None
    current_title = _normalize_text(md.get("current_title")) or None
    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "current_title": current_title,
        "file_name": file_name,
    }


def _strip_raw_text(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, sub_value in value.items():
            if key.lower() == "raw_text":
                continue
            stripped = _strip_raw_text(sub_value)
            if stripped in (None, "", [], {}, ()):  # skip empty items
                continue
            cleaned[key] = stripped
        return cleaned
    if isinstance(value, list):
        cleaned_list = [_strip_raw_text(item) for item in value]
        return [item for item in cleaned_list if item not in (None, "", [], {}, ())]
    if isinstance(value, tuple):
        cleaned_tuple = tuple(_strip_raw_text(item) for item in value)
        return tuple(item for item in cleaned_tuple if item not in (None, "", [], {}, ()))
    return value


def _resolve_candidate_identifier(metadata: Dict[str, Any], index: int) -> str:
    candidate_id = _normalize_text(metadata.get("candidate_id"))
    if candidate_id:
        return candidate_id
    file_name = _normalize_text(metadata.get("file_name"))
    if file_name:
        return file_name
    return f"resume_{index:04d}"


def _generate_resume_chunks(resume: Dict[str, Any], index: int) -> Tuple[str, List[Dict[str, Any]]]:
    chunks: List[Dict[str, Any]] = []
    base_meta = _build_base_metadata(resume)
    candidate_id = _resolve_candidate_identifier(base_meta, index)
    base_meta["candidate_id"] = candidate_id
    content = resume.get("content", {}) or {}
    content = _strip_raw_text(content)

    def add_chunk(section: str, text: str, extra_meta: Optional[Dict[str, Any]] = None) -> None:
        clean_text = _normalize_text(text)
        if not clean_text:
            return
        metadata = {**base_meta, "section": section.upper()}
        if extra_meta:
            metadata.update(extra_meta)
        metadata = {
            key: value
            for key, value in metadata.items()
            if value is not None
        }
        chunk_id = f"{candidate_id}::{section.lower()}::{len(chunks)}"
        chunks.append({
            "id": chunk_id,
            "document": clean_text,
            "metadata": metadata,
        })

    summary = content.get("summary") or content.get("SUMMARY")
    add_chunk("summary", summary)

    skills_section = content.get("skills") or content.get("SKILLS")
    skill_lines: List[str] = []
    if isinstance(skills_section, dict):
        technical = skills_section.get("technical") or []
        soft = skills_section.get("soft") or []
        tech_values = [
            _normalize_text(item) for item in technical if _normalize_text(item)
        ]
        soft_values = [
            _normalize_text(item) for item in soft if _normalize_text(item)
        ]
        if tech_values:
            skill_lines.append("Technical Skills: " + ", ".join(tech_values))
        if soft_values:
            skill_lines.append("Soft Skills: " + ", ".join(soft_values))
    elif isinstance(skills_section, list):
        values = [_normalize_text(skill) for skill in skills_section if _normalize_text(skill)]
        if values:
            skill_lines.append(", ".join(values))
    elif isinstance(skills_section, str):
        value = _normalize_text(skills_section)
        if value:
            skill_lines.append(value)
    if skill_lines:
        add_chunk("skills", "\n".join(skill_lines))

    experience_items = content.get("experience") or content.get("EXPERIENCE") or []
    if isinstance(experience_items, list):
        for idx_exp, exp in enumerate(experience_items):
            if not isinstance(exp, dict):
                continue
            lines: List[str] = []
            title = _normalize_text(exp.get("title") or exp.get("TITLE"))
            company = _normalize_text(exp.get("company") or exp.get("COMPANY"))
            period = _normalize_text(exp.get("period") or exp.get("PERIOD"))
            location = _normalize_text(exp.get("location") or exp.get("LOCATION"))
            header_parts = [part for part in [title, company] if part]
            header = " at ".join(header_parts) if len(header_parts) > 1 else (header_parts[0] if header_parts else "")
            if period:
                header = f"{header} ({period})" if header else period
            if location:
                header = f"{header} — {location}" if header else location
            if header:
                lines.append(header)
            roles = exp.get("roles") or exp.get("ROLES") or []
            if isinstance(roles, list):
                for role in roles:
                    role_text = _normalize_text(role)
                    if role_text:
                        lines.append(role_text)
            extra = {
                "title": title,
                "company": company,
                "period": period,
                "location": location,
            }
            add_chunk("experience", "\n".join(lines), extra)

    education_items = content.get("education") or content.get("EDUCATION") or []
    if isinstance(education_items, list):
        for idx_edu, edu in enumerate(education_items):
            if not isinstance(edu, dict):
                continue
            degree = _normalize_text(edu.get("degree") or edu.get("DEGREE"))
            institution = _normalize_text(edu.get("institution") or edu.get("INSTITUTION"))
            period = _normalize_text(edu.get("period") or edu.get("PERIOD"))
            notes = edu.get("notes") or edu.get("NOTES") or []
            note_lines = []
            if isinstance(notes, list):
                for note in notes:
                    note_text = _normalize_text(note)
                    if note_text:
                        note_lines.append(note_text)
            text_lines = []
            header = ", ".join(filter(None, [degree, institution]))
            if header:
                text_lines.append(header if not period else f"{header} ({period})")
            if note_lines:
                text_lines.extend(note_lines)
            extra = {
                "degree": degree,
                "institution": institution,
                "period": period,
            }
            add_chunk("education", "\n".join(text_lines), extra)

    languages = content.get("languages") or content.get("LANGUAGES")
    if isinstance(languages, list) and languages:
        add_chunk("languages", ", ".join(_normalize_text(lang) for lang in languages if _normalize_text(lang)))

    other_sections = content.get("other") or {}
    if isinstance(other_sections, dict):
        for key, value in other_sections.items():
            if key.lower() == "raw_text":
                continue
            if isinstance(value, list):
                text = "\n".join(_normalize_text(item) for item in value if _normalize_text(item))
            else:
                text = _normalize_text(value)
            add_chunk(key, text)

    additional_keys = {
        key: value
        for key, value in content.items()
        if key not in {"summary", "SUMMARY", "experience", "EXPERIENCE", "skills", "SKILLS", "education", "EDUCATION", "languages", "LANGUAGES", "other"}
    }
    for key, value in additional_keys.items():
        if isinstance(value, list):
            text = "\n".join(_normalize_text(item) for item in value if _normalize_text(item))
        else:
            text = _normalize_text(value)
        add_chunk(key, text)

    if not chunks:
        fallback_text = json.dumps(resume, ensure_ascii=False)
        add_chunk("fallback", fallback_text)

    return candidate_id, chunks


def _delete_candidate_embeddings(collection, identifier: str) -> None:
    if not identifier:
        return
    filters = [
        {"candidate_id": identifier},
    ]
    # If candidate ids fall back to file names we also clear on file_name.
    filters.append({"file_name": identifier})
    for where in filters:
        try:
            collection.delete(where=where)
        except Exception:
            logger.debug("No embeddings removed for filter %s", where, exc_info=True)


class BuildResumeVectorDBInput(BaseModel):
    collection_name: str = Field(RESUME_COLLECTION_NAME, description="Chroma collection name to (re)build")


class BuildResumeVectorDBTool(BaseTool):
    name: str = "Build Resume Vector DB"
    description: str = "Build or refresh the Chroma resume vector DB from structured JSON knowledge"
    args_schema: Type[BaseModel] = BuildResumeVectorDBInput

    def _run(self, collection_name: str = RESUME_COLLECTION_NAME) -> Dict[str, Any]:
        logger.info("BuildResumeVectorDBTool started for collection=%s", collection_name)
        result = sync_resume_vector_db(
            collection_name=collection_name,
            reset=True,
        )
        if result.get("error"):
            logger.error("Vector DB rebuild failed: %s", result["error"])
        else:
            logger.info(
                "Vector DB rebuild completed: %s chunks, %s total records",
                result.get("upserted_chunks"),
                result.get("count"),
            )
        return result


def sync_resume_vector_db(
    *,
    collection_name: str = RESUME_COLLECTION_NAME,
    candidate_ids: Optional[Sequence[str]] = None,
    removed_candidate_ids: Optional[Sequence[str]] = None,
    reset: bool = False,
    knowledge_json: Path = KNOWLEDGE_JSON,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> Dict[str, Any]:
    if not knowledge_json.exists():
        error_msg = f"Resumes file not found: {knowledge_json}"
        return {"error": error_msg}
    if not CHROMADB_AVAILABLE:
        return {"error": "chromadb not available in environment"}

    data = _load_structured_resumes(knowledge_json)
    try:
        embedding_function = get_embedding_function(embedding_model)
    except Exception as exc:  # pragma: no cover - defensive failure path
        logger.error("Unable to initialise embedding function", exc_info=True)
        return {"error": f"Failed to initialise embedding function: {exc}"}

    try:
        client = ensure_chroma_client()
    except Exception as exc:
        logger.error("Unable to initialise Chroma client", exc_info=True)
        return {"error": f"Failed to initialise Chroma client: {exc}"}
    if reset:
        try:
            client.delete_collection(collection_name)
        except Exception:
            logger.debug("Collection %s did not exist prior to reset", collection_name, exc_info=True)
    collection = client.get_or_create_collection(
        collection_name,
        embedding_function=embedding_function,
    )

    candidate_ids_provided = candidate_ids is not None
    candidate_filter = {
        _normalize_text(identifier).lower()
        for identifier in (candidate_ids or [])
        if _normalize_text(identifier)
    }
    selected_indices: List[int] = []
    found_identifiers: Dict[str, int] = {}
    for idx, resume in enumerate(data):
        meta = _build_base_metadata(resume)
        identifier = _resolve_candidate_identifier(meta, idx)
        if not identifier:
            continue
        identifier_lower = identifier.lower()
        if candidate_ids_provided and not candidate_filter:
            # Caller provided an explicit list but nothing valid to index.
            continue
        if candidate_filter and identifier_lower not in candidate_filter:
            continue
        selected_indices.append(idx)
        found_identifiers[identifier_lower] = idx

    if candidate_filter:
        missing = candidate_filter - set(found_identifiers.keys())
        for missing_id in sorted(missing):
            logger.debug("No resume record found for candidate_id=%s in knowledge store", missing_id)

    upserted_resumes = 0
    upserted_chunks = 0
    processed_identifiers: set[str] = set()

    for idx in selected_indices:
        resume = data[idx]
        candidate_id, chunks = _generate_resume_chunks(resume, idx)
        if not chunks:
            logger.debug("Skipping candidate %s (no chunks generated)", candidate_id)
            continue
        processed_identifiers.add(candidate_id)
        _delete_candidate_embeddings(collection, candidate_id)
        ids = [chunk["id"] for chunk in chunks]
        docs = [chunk["document"] for chunk in chunks]
        metas = [chunk["metadata"] for chunk in chunks]
        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        upserted_resumes += 1
        upserted_chunks += len(ids)

    removal_targets = {
        _normalize_text(identifier)
        for identifier in removed_candidate_ids or []
        if _normalize_text(identifier)
    }
    removal_targets.difference_update(processed_identifiers)
    removed_candidates = 0
    for identifier in removal_targets:
        try:
            _delete_candidate_embeddings(collection, identifier)
            removed_candidates += 1
        except Exception:
            logger.warning("Failed to delete embeddings for candidate %s", identifier, exc_info=True)

    try:
        current_count = collection.count()
    except Exception:
        current_count = None

    return {
        "status": "ok",
        "upserted_resumes": upserted_resumes,
        "upserted_chunks": upserted_chunks,
        "removed_candidates": removed_candidates,
        "count": current_count,
        "persist_dir": str(CHROMA_VECTOR_DIR),
    }


def build_resume_vector_db(collection_name: str = RESUME_COLLECTION_NAME) -> Dict[str, Any]:
    """Compatibility helper: call the BuildResumeVectorDBTool as a simple function."""
    return BuildResumeVectorDBTool()._run(collection_name=collection_name)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or refresh the resume Chroma vector store.")
    parser.add_argument(
        "--collection",
        default=RESUME_COLLECTION_NAME,
        help="Chroma collection name to populate.",
    )
    parser.add_argument(
        "--candidate-id",
        dest="candidate_ids",
        action="append",
        help="Limit rebuild to specific candidate_id (repeatable).",
    )
    parser.add_argument(
        "--remove-candidate-id",
        dest="removed_candidate_ids",
        action="append",
        help="Delete embeddings for candidate_id without re-ingesting (repeatable).",
    )
    parser.add_argument(
        "--no-reset",
        dest="reset",
        action="store_false",
        help="Skip dropping the collection before ingesting.",
    )
    parser.add_argument(
        "--knowledge-json",
        default=str(KNOWLEDGE_JSON),
        help="Path to structured_resumes.json file.",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Embedding model registered with CrewAI embedding factory.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    result = sync_resume_vector_db(
        collection_name=args.collection,
        candidate_ids=args.candidate_ids,
        removed_candidate_ids=args.removed_candidate_ids,
        reset=args.reset,
        knowledge_json=Path(args.knowledge_json),
        embedding_model=args.embedding_model,
    )
    if result.get("error"):
        logger.error("Vector store rebuild failed: %s", result["error"])
        return 1
    logger.info(
        "Vector store ready: %s resumes, %s chunks (persist_dir=%s)",
        result.get("upserted_resumes"),
        result.get("upserted_chunks"),
        result.get("persist_dir"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
