"""Centralised helpers for loading CrewAI knowledge configurations."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml
from crewai.knowledge.knowledge import Knowledge
from crewai.knowledge.source.base_knowledge_source import BaseKnowledgeSource
from crewai.knowledge.source.json_knowledge_source import JSONKnowledgeSource
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource

from resume_screening_rag_automation.knowledge.storage import ChromaDirectoryKnowledgeStorage
from resume_screening_rag_automation.knowledge.vector_source import VectorStoreKnowledgeSource
from resume_screening_rag_automation.paths import (
    CHROMA_VECTOR_DIR,
    DATA_ROOT,
    SCREENING_INSIGHTS_DIR,
    STRUCTURED_RESUMES_PATH,
    ensure_data_directories,
)
from resume_screening_rag_automation.tools.vectorstore_utils import DEFAULT_EMBEDDING_MODEL

LOGGER = logging.getLogger(__name__)

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = Path(__file__).resolve().parent / "sources.yaml"

_DOCUMENT_FACTORIES: Dict[str, Any] = {
    "json": JSONKnowledgeSource,
    "text": TextFileKnowledgeSource,
}


class KnowledgeConfigError(RuntimeError):
    """Raised when the knowledge configuration is invalid."""


@lru_cache(maxsize=1)
def _embedding_config() -> Dict[str, Any]:
    """Return a cached embedding configuration compatible with the resume store."""

    return {
        "provider": "openai",
        "config": {
            "model_name": DEFAULT_EMBEDDING_MODEL,
        },
    }


@lru_cache(maxsize=1)
def _raw_config() -> Dict[str, Any]:
    """Load the YAML configuration that describes available knowledge sources."""

    if not _CONFIG_PATH.exists():
        raise KnowledgeConfigError(f"Knowledge configuration file missing at {_CONFIG_PATH}")

    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - invalid YAML is unlikely in tests
        raise KnowledgeConfigError("Invalid knowledge configuration YAML") from exc

    return data


def _resolve_path(path_value: str) -> Path:
    """Resolve relative paths with respect to the package root."""

    path = Path(path_value)
    if not path.is_absolute():
        path = (_PACKAGE_ROOT / path_value).resolve()
    return path


def _resolve_vector_directory(path_value: str) -> Path:
    """Resolve a vector store directory, aligning legacy paths with the new layout."""

    if not path_value:
        return CHROMA_VECTOR_DIR.resolve()

    normalised = path_value.replace("\\", "/").strip()
    legacy_tokens = {"chroma_vectorstore", "knowledge/chroma_vectorstore"}
    if normalised in legacy_tokens:
        return CHROMA_VECTOR_DIR.resolve()

    if normalised.startswith("knowledge_store/"):
        remainder = normalised[len("knowledge_store/") :]
        return (DATA_ROOT / remainder).resolve()

    candidate = _resolve_path(normalised)
    legacy_paths = {
        (_PACKAGE_ROOT / "chroma_vectorstore").resolve(),
        (_PACKAGE_ROOT / "knowledge" / "chroma_vectorstore").resolve(),
    }
    if candidate in legacy_paths:
        return CHROMA_VECTOR_DIR.resolve()

    return candidate.resolve()


def _build_document_source(
    name: str,
    config: Mapping[str, Any],
    *,
    collection_name: str,
    override_path: Optional[Path] = None,
) -> BaseKnowledgeSource:
    """Instantiate a document-based knowledge source from configuration."""

    doc_type = str(config.get("type", "text")).lower()
    factory = _DOCUMENT_FACTORIES.get(doc_type)
    if not factory:
        raise KnowledgeConfigError(f"Unsupported document source type '{doc_type}' for '{name}'")

    if override_path is not None:
        path = override_path
    else:
        path_value = config.get("path")
        if not path_value:
            raise KnowledgeConfigError(f"Document source '{name}' requires a 'path'")
        path = _resolve_path(str(path_value))

    if not path.exists():
        raise FileNotFoundError(path)

    kwargs: Dict[str, Any] = {
        "collection_name": collection_name,
        "file_paths": [path],
    }

    if "chunk_size" in config:
        kwargs["chunk_size"] = int(config["chunk_size"])
    if "chunk_overlap" in config:
        kwargs["chunk_overlap"] = int(config["chunk_overlap"])

    metadata = config.get("metadata")
    if isinstance(metadata, dict) and metadata:
        kwargs["metadata"] = metadata

    return factory(**kwargs)


def _build_vector_source(
    name: str,
    config: Mapping[str, Any],
    *,
    default_directory: Path,
    collection_name: str,
) -> VectorStoreKnowledgeSource:
    """Instantiate the vector store knowledge source wrapper."""

    persist_value = str(config.get("persist_directory", "")).strip()
    persist_directory = (
        _resolve_vector_directory(persist_value)
        if persist_value
        else default_directory
    )
    description = config.get("description")
    metadata = config.get("metadata") if isinstance(config.get("metadata"), dict) else None

    if not persist_directory.exists():
        raise FileNotFoundError(persist_directory)

    model_kwargs: Dict[str, Any] = {
        "persist_directory": str(persist_directory),
        "collection_name": str(config.get("collection_name", collection_name)),
    }
    if description:
        model_kwargs["description"] = str(description)
    if metadata:
        model_kwargs["metadata"] = metadata

    return VectorStoreKnowledgeSource(**model_kwargs)


def _collect_sources(
    group_name: str,
    group_config: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any],
    vector_sources: Mapping[str, Mapping[str, Any]],
    document_sources: Mapping[str, Mapping[str, Any]],
    session_id: Optional[str],
) -> List[BaseKnowledgeSource]:
    """Build all sources for the requested knowledge group."""

    sources: List[BaseKnowledgeSource] = []

    default_directory_value = str(
        group_config.get("persist_directory")
        or defaults.get("persist_directory", str(CHROMA_VECTOR_DIR))
    )
    default_directory = _resolve_vector_directory(default_directory_value)

    collection_name = str(group_config.get("collection_name"))

    for vector_name in group_config.get("vector_sources", []) or []:
        vector_config = vector_sources.get(vector_name)
        if not vector_config:
            LOGGER.warning("Vector source '%s' referenced but not defined", vector_name)
            continue
        try:
            sources.append(
                _build_vector_source(
                    vector_name,
                    vector_config,
                    default_directory=default_directory,
                    collection_name=collection_name,
                )
            )
        except FileNotFoundError:
            continue

    for document_name in group_config.get("document_sources", []) or []:
        document_config = document_sources.get(document_name)
        if not document_config:
            LOGGER.warning("Document source '%s' referenced but not defined", document_name)
            continue

        override_path: Optional[Path] = None
        if document_name == "generated_screening_insights":
            if not session_id:
                LOGGER.debug(
                    "Skipping generated screening insights for '%s' without session context",
                    group_name,
                )
                continue
            override_path = (SCREENING_INSIGHTS_DIR / f"{session_id}.json").resolve()
        elif document_name == "structured_resumes":
            override_path = STRUCTURED_RESUMES_PATH.resolve()

        try:
            sources.append(
                _build_document_source(
                    document_name,
                    document_config,
                    collection_name=collection_name,
                    override_path=override_path,
                )
            )
        except FileNotFoundError as exc:
            log = LOGGER.warning
            if document_name == "generated_screening_insights":
                log = LOGGER.debug
            log(
                "Skipping document source '%s' for group '%s' because %s",
                document_name,
                group_name,
                exc,
            )

    return sources


def _build_group_knowledge(group_name: str, *, session_id: Optional[str] = None) -> Knowledge:
    """Create a Knowledge instance for the requested group key."""

    config = _raw_config()
    group_config = config.get("groups", {}).get(group_name)
    if not group_config:
        raise KnowledgeConfigError(f"Knowledge group '{group_name}' not configured")

    if "collection_name" not in group_config:
        raise KnowledgeConfigError(f"Knowledge group '{group_name}' requires a collection_name")

    defaults = config.get("defaults", {})
    vector_sources = config.get("vector_sources", {}) or {}
    document_sources = config.get("document_sources", {}) or {}

    collection_name = str(group_config["collection_name"])
    persist_directory_value = str(
        group_config.get("persist_directory")
        or defaults.get("persist_directory", str(CHROMA_VECTOR_DIR))
    )
    persist_directory = _resolve_vector_directory(persist_directory_value)

    ensure_data_directories()

    storage = ChromaDirectoryKnowledgeStorage(
        persist_directory=str(persist_directory),
        embedder=_embedding_config(),
        collection_name=collection_name,
        session_id=session_id,
    )

    sources = _collect_sources(
        group_name,
        group_config,
        defaults=defaults,
        vector_sources=vector_sources,
        document_sources=document_sources,
        session_id=session_id,
    )

    return Knowledge(
        collection_name=collection_name,
        sources=sources,
        storage=storage,
    )


def knowledge_for(group_name: str, *, session_id: Optional[str] = None) -> Knowledge:
    """Return (and cache) the knowledge object for the given group and session."""

    session_key = session_id or ""
    return _cached_knowledge(group_name, session_key)


@lru_cache(maxsize=None)
def _cached_knowledge(group_name: str, session_key: str) -> Knowledge:
    resolved_session = session_key or None
    return _build_group_knowledge(group_name, session_id=resolved_session)


def for_query_manager(*, session_id: Optional[str] = None) -> Knowledge:
    """Knowledge sources tailored for the Query Manager crew."""

    return knowledge_for("query_manager", session_id=session_id)


def for_job_description(*, session_id: Optional[str] = None) -> Knowledge:
    """Knowledge sources tailored for the Job Description crew."""

    return knowledge_for("job_description", session_id=session_id)


def for_screening(*, session_id: Optional[str] = None) -> Knowledge:
    """Knowledge sources tailored for the Screening crew."""

    return knowledge_for("screening", session_id=session_id)


def for_discussion(*, session_id: Optional[str] = None) -> Knowledge:
    """Knowledge sources tailored for the Discussion crew."""

    return knowledge_for("discussion", session_id=session_id)


__all__ = [
    "KnowledgeConfigError",
    "knowledge_for",
    "for_query_manager",
    "for_job_description",
    "for_screening",
    "for_discussion",
]
