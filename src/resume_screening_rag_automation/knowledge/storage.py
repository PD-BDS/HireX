"""Custom CrewAI knowledge storage helpers."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from crewai.knowledge.storage.knowledge_storage import KnowledgeStorage
from crewai.rag.chromadb.client import ChromaDBClient

from resume_screening_rag_automation.tools.vectorstore_utils import (
    DEFAULT_EMBEDDING_MODEL,
    ensure_chroma_client,
    get_embedding_function,
)

LOGGER = logging.getLogger(__name__)


def _extract_model_name(embedder: Optional[object]) -> str:
    """Resolve the embedding model name from the provided embedder spec."""

    if isinstance(embedder, dict):
        config = embedder.get("config") if isinstance(embedder.get("config"), dict) else {}
        model_name = config.get("model_name") or embedder.get("model_name")
        if isinstance(model_name, str) and model_name.strip():
            return model_name.strip()
    return DEFAULT_EMBEDDING_MODEL


class ChromaDirectoryKnowledgeStorage(KnowledgeStorage):
    """Knowledge storage that reuses the project Chroma vector store."""

    def __init__(
        self,
        persist_directory: str,
        *,
        embedder: Optional[object] = None,
        collection_name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.persist_directory = str(Path(persist_directory).expanduser().resolve())
        self._model_name = _extract_model_name(embedder)
        self._session_component = self._normalise_session_id(session_id)
        super().__init__(embedder=None, collection_name=collection_name)

        # Build a shared Chroma client that uses the same embeddings as the resume store.
        embedding_function = get_embedding_function(self._model_name)
        self._client = ChromaDBClient(
            client=ensure_chroma_client(),
            embedding_function=embedding_function,
        )
        base_name = self.collection_name or "knowledge"
        base_name = self._normalise_collection_name(base_name)
        if self._session_component:
            self._full_collection_name = f"session-{self._session_component}__{base_name}"
        else:
            self._full_collection_name = base_name

    def initialize_knowledge_storage(self) -> None:
        """Connect to or create the configured Chroma collection."""

        persist_path = Path(self.persist_directory)
        persist_path.mkdir(parents=True, exist_ok=True)
        try:
            self._client.get_or_create_collection(
                collection_name=self._full_collection_name,
            )
        except Exception as exc:  # pragma: no cover - defensive logging only
            LOGGER.exception(
                "Failed to initialise knowledge collection '%s' at %s",
                self._full_collection_name,
                persist_path,
            )
            raise RuntimeError(
                f"Failed to initialise knowledge collection '{self._full_collection_name}'"
            ) from exc

    def reset(self) -> None:
        """Drop the knowledge collection while retaining the shared vector store."""

        try:
            self._client.delete_collection(
                collection_name=self._full_collection_name,
            )
        except Exception as exc:  # pragma: no cover - defensive logging only
            LOGGER.debug(
                "Knowledge collection '%s' could not be deleted cleanly: %s",
                self._full_collection_name,
                exc,
            )

    @staticmethod
    def _normalise_session_id(session_id: Optional[str]) -> str:
        if not session_id:
            return ""
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", session_id).strip("-")
        return cleaned.lower()

    @staticmethod
    def _normalise_collection_name(name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-")
        if not cleaned:
            return "knowledge"
        lowered = cleaned.lower()
        if lowered == "knowledge":
            return "knowledge"
        return f"knowledge-{lowered}"
