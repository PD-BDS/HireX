import json
import logging
from typing import Any, Dict, Optional, Type

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()
logger = logging.getLogger(__name__)

from crewai.tools import BaseTool

from resume_screening_rag_automation.tools.build_resume_vector_db import build_resume_vector_db
from resume_screening_rag_automation.tools.constants import RESUME_COLLECTION_NAME
from resume_screening_rag_automation.tools.vectorstore_utils import (
    CHROMADB_AVAILABLE,
    DEFAULT_EMBEDDING_MODEL,
    ensure_chroma_client,
    get_embedding_function,
)


class SearchResumesInput(BaseModel):
    query: str = Field(..., description="Query text to search resumes")
    top_k: int = Field(5, description="Number of top results to return")
    where: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata filter passed to the vector store query",
    )

    @field_validator("where", mode="before")
    @classmethod
    def _coerce_where(cls, value: Any) -> Optional[Dict[str, Any]]:
        if value in (None, "", [], {}):
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return None

    @field_validator("top_k", mode="before")
    @classmethod
    def _ensure_positive_top_k(cls, value: Any) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = 5
        return max(1, numeric)


class SearchResumesTool(BaseTool):
    name: str = "Search Resumes"
    description: str = "Run vector similarity search over the resume collection and return hits"
    args_schema: Type[BaseModel] = SearchResumesInput
    collection_name: str = RESUME_COLLECTION_NAME
    embedding_model: str = DEFAULT_EMBEDDING_MODEL

    def _run(
        self,
        query: str,
        top_k: int = 5,
        collection_name: str = RESUME_COLLECTION_NAME,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        top_k = self._normalise_top_k(top_k)
        logger.info(
            "SearchResumesTool starting query collection=%s top_k=%s query_preview=%s",
            collection_name,
            top_k,
            query[:120].replace("\n", " "),
        )
        if not CHROMADB_AVAILABLE:
            logger.error("ChromaDB not available; cannot run search")
            return {"error": "chromadb not available in environment"}

        active_collection = collection_name or self.collection_name
        try:
            embedding_function = get_embedding_function(self.embedding_model)
        except Exception as exc:  # pragma: no cover - defensive failure path
            logger.error("Failed to load embedding function", exc_info=True)
            return {"error": f"Failed to load embedding function: {exc}"}

        try:
            client = ensure_chroma_client()
        except Exception as exc:
            logger.error("Failed to initialise Chroma client", exc_info=True)
            return {"error": f"Failed to initialise Chroma client: {exc}"}

        collection = client.get_or_create_collection(
            active_collection,
            embedding_function=embedding_function,
        )

        collection_ready = False
        for attempt in range(2):
            try:
                existing_count = collection.count()
                logger.debug(
                    "Chroma collection '%s' contains %s records",
                    active_collection,
                    existing_count,
                )
            except Exception:  # pragma: no cover - defensive reset for corrupted indexes
                logger.warning("Failed to read Chroma collection; resetting", exc_info=True)
                try:
                    client.delete_collection(active_collection)
                    logger.info("Deleted corrupted Chroma collection '%s'", active_collection)
                except Exception:
                    logger.debug("Unable to delete collection during reset", exc_info=True)
                collection = client.get_or_create_collection(
                    active_collection,
                    embedding_function=embedding_function,
                )
                continue

            if existing_count == 0 and attempt == 0:
                logger.info("Chroma collection '%s' empty; rebuilding", active_collection)
                rebuild_result = build_resume_vector_db(collection_name=active_collection)
                if rebuild_result.get("error"):
                    logger.error(
                        "Vector store rebuild failed for collection=%s: %s",
                        active_collection,
                        rebuild_result["error"],
                    )
                    return {"error": rebuild_result["error"]}
                collection = client.get_or_create_collection(
                    active_collection,
                    embedding_function=embedding_function,
                )
                continue

            if existing_count == 0:
                logger.error("Chroma collection '%s' still empty after rebuild", active_collection)
                return {"hits": [], "warning": "Resume collection is empty. Rebuild the vector store."}

            collection_ready = True
            break

        if not collection_ready:
            logger.error("Unable to prepare Chroma collection '%s' for querying", active_collection)
            return {"hits": [], "warning": "Resume collection unavailable."}

        query_kwargs: Dict[str, Any] = {
            "query_texts": [query],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if isinstance(where, dict) and where:
            query_kwargs["where"] = where

        try:
            result = collection.query(**query_kwargs)
        except Exception as exc:
            logger.error("Chroma query failed", exc_info=True)
            return {"error": f"Vector search failed: {exc}"}

        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]

        hits = []
        for index, match_id in enumerate(ids):
            hits.append(
                {
                    "id": match_id,
                    "distance": distances[index] if index < len(distances) else None,
                    "document": documents[index] if index < len(documents) else None,
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                }
            )

        logger.info("SearchResumesTool completed hits=%s collection=%s", len(hits), active_collection)
        return {"hits": hits}

    @staticmethod
    def _normalise_top_k(raw_top_k: Any) -> int:
        try:
            numeric = int(raw_top_k)
        except (TypeError, ValueError):
            numeric = 5
        return max(1, numeric)


def search_resumes_tool(
    query: str,
    top_k: int = 5,
    collection_name: str = RESUME_COLLECTION_NAME,
    where: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compatibility helper: call SearchResumesTool as a simple function."""
    return SearchResumesTool().run(
        query=query,
        top_k=top_k,
        collection_name=collection_name,
        where=where,
    )
