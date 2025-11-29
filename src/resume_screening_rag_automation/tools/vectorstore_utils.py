"""Shared helpers for Chroma vector store interactions."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, Optional, Tuple

from dotenv import load_dotenv, dotenv_values
from resume_screening_rag_automation.core.constants import (
    DEFAULT_EMBEDDING_MODEL,
    MAX_EMBED_CHARS,
    MAX_EMBED_TOKENS,
)
from resume_screening_rag_automation.paths import CHROMA_VECTOR_DIR

load_dotenv()

try:
    import chromadb
    from chromadb.config import Settings

    CHROMADB_AVAILABLE = True
except Exception:  # pragma: no cover - chromadb optional in some environments
    chromadb = None  # type: ignore[assignment]
    Settings = None  # type: ignore[assignment]
    CHROMADB_AVAILABLE = False

try:
    from crewai.rag.embeddings.factory import build_embedder
except ImportError:  # pragma: no cover - fallback when running without crewai>=0.220
    build_embedder = None  # type: ignore[assignment]
    try:
        from crewai.rag.embeddings.factory import build_embedder_from_dict
    except ImportError:  # pragma: no cover - fallback when rag factory unavailable
        build_embedder_from_dict = None  # type: ignore[assignment]
        try:
            from chromadb.utils import embedding_functions
        except Exception:  # pragma: no cover - chromadb optional
            embedding_functions = None  # type: ignore[assignment]
    else:
        embedding_functions = None
else:
    build_embedder_from_dict = None  # type: ignore[assignment]
    embedding_functions = None

LOGGER = logging.getLogger(__name__)

DEFAULT_EMBEDDER_SPEC: Dict[str, Any] = {
    "provider": "openai",
    "config": {
        "model_name": DEFAULT_EMBEDDING_MODEL,
    },
}

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None  # type: ignore[assignment]

_EMBEDDING_CACHE: Dict[Tuple[str, str], Any] = {}
_CHROMA_CLIENT: Optional[Any] = None
_TOKEN_ENCODER: Optional[Any] = None


def _get_env_var(key: str) -> Optional[str]:
    """Lookup env var preferring OS values, falling back to .env snapshot."""

    value = os.getenv(key)
    if value:
        return value
    return dotenv_values().get(key)


def _build_embedder(spec: Dict[str, Any]) -> Any:
    provider = spec.get("provider", "openai")
    config = spec.get("config", {}) or {}
    model_name = config.get("model_name", DEFAULT_EMBEDDING_MODEL)

    if provider == "openai":
        api_key = _get_env_var("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set for OpenAI embeddings")
        config.setdefault("api_key", api_key)

    if build_embedder is not None:
        return build_embedder(spec)

    if build_embedder_from_dict is not None:
        return build_embedder_from_dict(spec)

    if embedding_functions is None:
        raise RuntimeError("Embedding factory unavailable; install crewai>=0.210 or chromadb extras")

    if provider != "openai":  # pragma: no cover - defensive guard
        raise ValueError(f"Unsupported embedding provider '{provider}' without crewai factory")

    api_key = _get_env_var("CHROMA_OPENAI_API_KEY") or _get_env_var("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("CHROMA_OPENAI_API_KEY or OPENAI_API_KEY must be set for embeddings")
    return embedding_functions.OpenAIEmbeddingFunction(api_key=api_key, model_name=model_name)


def _normalise_model_name(model_name: Optional[str]) -> str:
    normalised = str(model_name or "").strip()
    return normalised or DEFAULT_EMBEDDING_MODEL


def _ensure_token_encoder() -> Optional[Any]:
    global _TOKEN_ENCODER

    if _TOKEN_ENCODER is not None:
        return _TOKEN_ENCODER

    if tiktoken is None:
        return None

    try:
        _TOKEN_ENCODER = tiktoken.encoding_for_model(DEFAULT_EMBEDDING_MODEL)
    except Exception:  # pragma: no cover - fallback when model unknown
        try:
            _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:  # pragma: no cover - encoding unavailable
            _TOKEN_ENCODER = None
    return _TOKEN_ENCODER


def _truncate_text(
    value: Any,
    *,
    limit: int = MAX_EMBED_CHARS,
    max_tokens: int = MAX_EMBED_TOKENS,
) -> Any:
    if not isinstance(value, str):
        return value

    truncated = value
    if len(truncated) > limit:
        LOGGER.warning("Truncating embedding input from %d to %d chars", len(truncated), limit)
        truncated = truncated[:limit]

    if max_tokens:
        encoder = _ensure_token_encoder()
        if encoder is not None:
            tokens = encoder.encode(truncated)
            if len(tokens) > max_tokens:
                LOGGER.debug("Truncating embedding input from %d to %d tokens", len(tokens), max_tokens)
                truncated = encoder.decode(tokens[:max_tokens])
        else:
            approx_limit = max_tokens * 4
            if len(truncated) > approx_limit:
                LOGGER.debug(
                    "Approximate token truncation from %d to %d chars (no tokenizer available)",
                    len(truncated),
                    approx_limit,
                )
                truncated = truncated[:approx_limit]
    return truncated


def _truncate_iterable(
    values: Iterable[Any],
    *,
    limit: int = MAX_EMBED_CHARS,
    max_tokens: int = MAX_EMBED_TOKENS,
) -> Iterable[Any]:
    return [_truncate_text(item, limit=limit, max_tokens=max_tokens) for item in values]


class _TruncatingEmbedder:
    """Wrap an embedding callable to enforce a maximum character length."""

    def __init__(
        self,
        inner: Any,
        *,
        limit: int = MAX_EMBED_CHARS,
        max_tokens: int = MAX_EMBED_TOKENS,
    ) -> None:
        self._inner = inner
        self._limit = limit
        self._max_tokens = max_tokens

    def __call__(self, input: Any) -> Any:  # noqa: ANN401 - signature expected by chromadb
        truncated = _truncate_text(input, limit=self._limit, max_tokens=self._max_tokens)
        return self._inner(truncated)

    def embed_query(self, input: Any) -> Any:  # noqa: ANN401 - align with chromadb expectations
        truncated = _truncate_text(input, limit=self._limit, max_tokens=self._max_tokens)
        target = getattr(self._inner, "embed_query", None)
        if target is not None:
            return target(truncated)
        return self._inner(truncated)

    def embed_documents(self, inputs: Iterable[Any]) -> Any:  # noqa: ANN401 - align with chromadb expectations
        truncated_inputs = _truncate_iterable(inputs, limit=self._limit, max_tokens=self._max_tokens)
        target = getattr(self._inner, "embed_documents", None)
        if target is not None:
            return target(truncated_inputs)
        return self._inner(truncated_inputs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)


def get_embedding_function(model_name: str = DEFAULT_EMBEDDING_MODEL) -> Any:
    """Return an embedding callable built via CrewAI's embedding factory."""

    if not CHROMADB_AVAILABLE:
        raise RuntimeError("chromadb is required for embedding lookups")

    normalised = _normalise_model_name(model_name)
    cache_key = ("openai", normalised)
    if cache_key in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[cache_key]

    if not _get_env_var("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set for OpenAI embeddings")

    spec = json.loads(json.dumps(DEFAULT_EMBEDDER_SPEC))  # deep copy via JSON
    spec.setdefault("config", {})["model_name"] = normalised
    embedder = _build_embedder(spec)
    wrapped = _TruncatingEmbedder(embedder)
    _EMBEDDING_CACHE[cache_key] = wrapped
    return wrapped


def ensure_chroma_client() -> Any:
    """Return a persistent Chroma client configured for the resume vector store."""

    global _CHROMA_CLIENT

    if _CHROMA_CLIENT is not None:
        return _CHROMA_CLIENT

    if not CHROMADB_AVAILABLE or chromadb is None or Settings is None:
        raise RuntimeError("chromadb not available in environment")

    CHROMA_VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    settings = Settings(persist_directory=str(CHROMA_VECTOR_DIR), allow_reset=True, is_persistent=True)
    try:
        _CHROMA_CLIENT = chromadb.PersistentClient(path=str(CHROMA_VECTOR_DIR), settings=settings)
        LOGGER.debug("Using persistent Chroma client at %s", CHROMA_VECTOR_DIR)
    except Exception:  # pragma: no cover - defensive fallback
        LOGGER.warning("Falling back to in-memory Chroma client", exc_info=True)
        _CHROMA_CLIENT = chromadb.Client()
    return _CHROMA_CLIENT


__all__ = [
    "CHROMADB_AVAILABLE",
    "CHROMA_VECTOR_DIR",
    "DEFAULT_EMBEDDING_MODEL",
    "ensure_chroma_client",
    "get_embedding_function",
]
