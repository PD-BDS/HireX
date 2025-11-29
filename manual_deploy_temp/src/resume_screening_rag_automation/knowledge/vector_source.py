"""CrewAI knowledge source wrappers for existing vector stores."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from crewai.knowledge.source.base_knowledge_source import BaseKnowledgeSource

LOGGER = logging.getLogger(__name__)


class VectorStoreKnowledgeSource(BaseKnowledgeSource):
    """Knowledge source that reuses a pre-built Chroma collection."""

    persist_directory: str
    collection_name: str
    description: Optional[str] = None

    def validate_content(self) -> Dict[str, str]:
        """Ensure the persisted Chroma directory exists before querying."""

        path = Path(self.persist_directory)
        if not path.exists():
            raise FileNotFoundError(
                f"Vector store directory not found at {path}"
            )
        return {
            "persist_directory": str(path),
            "collection_name": self.collection_name,
        }

    def add(self) -> None:
        """Vector stores are pre-populated, so no ingestion is required."""

        try:
            self.validate_content()
        except FileNotFoundError as exc:  # pragma: no cover - defensive guard
            LOGGER.warning("Skipping vector source due to missing directory: %s", exc)
            raise

        if not self.storage:
            raise ValueError("VectorStoreKnowledgeSource requires an attached storage instance")

        if getattr(self.storage, "collection", None) is None:
            # Storage should already be initialised by Knowledge.__init__, but ensure it here.
            self.storage.initialize_knowledge_storage()
