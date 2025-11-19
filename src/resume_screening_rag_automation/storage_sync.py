"""Remote knowledge-store syncing helpers for Streamlit deployments."""

from __future__ import annotations

import atexit
import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from resume_screening_rag_automation.paths import DATA_ROOT

LOGGER = logging.getLogger(__name__)

try:  # Optional dependency; only needed when Supabase sync is enabled.
	from supabase import create_client
except ImportError:  # pragma: no cover - Supabase sync is optional.
	create_client = None

if TYPE_CHECKING:
	from supabase import Client as SupabaseClient
else:  # pragma: no cover - typing fallback for runtime environments without supabase
	SupabaseClient = Any  # type: ignore[assignment]

REMOTE_PROVIDER = os.getenv("REMOTE_STORAGE_PROVIDER", "").strip().lower()
DEFAULT_OBJECT_NAME = os.getenv("KNOWLEDGE_ARCHIVE_OBJECT", "knowledge_store.tar.gz")
DEFAULT_BUCKET_NAME = os.getenv("KNOWLEDGE_ARCHIVE_BUCKET", "knowledge-store")
SYNC_INTERVAL_SECONDS = max(5.0, float(os.getenv("KNOWLEDGE_SYNC_MIN_INTERVAL", "30")))


class RemoteSyncError(RuntimeError):
	"""Raised when the remote storage backend cannot be initialised."""


class _BaseRemoteBackend:
	"""Interface implemented by remote storage providers."""

	def download_archive(self, target: Path) -> bool:  # pragma: no cover - abstract
		raise NotImplementedError

	def upload_archive(self, source: Path) -> None:  # pragma: no cover - abstract
		raise NotImplementedError


class SupabaseStorageBackend(_BaseRemoteBackend):
	"""Supabase storage backend for syncing the knowledge archive."""

	def __init__(self) -> None:
		if create_client is None:
			raise RemoteSyncError("supabase-py is not installed; add 'supabase' to dependencies")

		url = os.getenv("SUPABASE_URL")
		key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE")
		if not url or not key:
			raise RemoteSyncError("Supabase credentials missing (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)")

		self.bucket = os.getenv("SUPABASE_KNOWLEDGE_BUCKET", DEFAULT_BUCKET_NAME)
		self.object_name = os.getenv("SUPABASE_KNOWLEDGE_OBJECT", DEFAULT_OBJECT_NAME)
		self.client: SupabaseClient = create_client(url, key)

	def download_archive(self, target: Path) -> bool:
		storage = self.client.storage.from_(self.bucket)
		try:
			payload = storage.download(self.object_name)
		except Exception as exc:  # pragma: no cover - network errors depend on Supabase
			LOGGER.info("Remote knowledge archive missing or unavailable: %s", exc)
			return False

		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_bytes(payload)
		return True

	def upload_archive(self, source: Path) -> None:
		storage = self.client.storage.from_(self.bucket)
		with source.open("rb") as handle:
			storage.upload(
				self.object_name,
				handle,
				{"cache-control": "no-cache", "content-type": "application/gzip", "upsert": "true"},
			)


class KnowledgeStoreSync:
	"""Coordinates download/upload of the `knowledge_store` directory."""

	def __init__(self) -> None:
		self._backend = self._build_backend()
		self._initialised = False
		self._dirty = False
		self._last_digest: Optional[str] = None
		self._last_flush = 0.0
		if self._backend:
			atexit.register(self.flush)

	def _build_backend(self) -> Optional[_BaseRemoteBackend]:
		if not REMOTE_PROVIDER or REMOTE_PROVIDER in {"local", "none"}:
			LOGGER.info("Remote knowledge sync disabled (provider=%s)", REMOTE_PROVIDER or "local")
			return None

		if REMOTE_PROVIDER == "supabase":
			try:
				return SupabaseStorageBackend()
			except RemoteSyncError as exc:
				LOGGER.warning("Supabase backend unavailable: %s", exc)
				return None

		LOGGER.warning("Unsupported remote storage provider '%s'", REMOTE_PROVIDER)
		return None

	def ensure_local_copy(self) -> None:
		"""Download and extract the remote archive if configured."""

		if self._initialised:
			return
		self._initialised = True

		if not self._backend:
			return

		archive = self._download_temp_archive()
		if not archive:
			LOGGER.info("Remote archive not found; keeping existing knowledge_store")
			return

		try:
			self._extract_archive(archive)
			self._last_digest = self._hash_file(archive)
		finally:
			shutil.rmtree(archive.parent, ignore_errors=True)

	def mark_dirty(self) -> None:
		"""Flag the knowledge store as having local changes."""

		if self._backend:
			self._dirty = True

	def flush_if_needed(self, *, force: bool = False) -> None:
		"""Upload the archive when dirty or requested explicitly."""

		if not self._backend:
			return

		if not (force or self._dirty):
			return

		now = time.monotonic()
		if not force and (now - self._last_flush) < SYNC_INTERVAL_SECONDS:
			return

		if not DATA_ROOT.exists():
			LOGGER.warning("Knowledge store directory %s missing; skipping sync", DATA_ROOT)
			return

		archive = self._build_archive()
		try:
			digest = self._hash_file(archive)
			if not force and digest == self._last_digest:
				self._dirty = False
				return
			try:
				self._backend.upload_archive(archive)
			except Exception as exc:  # pragma: no cover - network failures depend on env
				LOGGER.warning("Failed to upload knowledge archive; will retry later: %s", exc)
				self._dirty = True
				return
			self._last_digest = digest
			self._last_flush = now
			self._dirty = False
		finally:
			shutil.rmtree(archive.parent, ignore_errors=True)

	def flush(self) -> None:
		"""Force a sync regardless of throttling."""

		self.flush_if_needed(force=True)

	def _download_temp_archive(self) -> Optional[Path]:
		if not self._backend:
			return None

		tmpdir = Path(tempfile.mkdtemp(prefix="knowledge_sync_dl_"))
		target = tmpdir / DEFAULT_OBJECT_NAME
		try:
			if not self._backend.download_archive(target):
				shutil.rmtree(tmpdir, ignore_errors=True)
				return None
			return target
		except Exception as exc:  # pragma: no cover - depends on backend implementation
			shutil.rmtree(tmpdir, ignore_errors=True)
			raise RemoteSyncError(f"Failed to download remote archive: {exc}") from exc

	def _build_archive(self) -> Path:
		tmpdir = Path(tempfile.mkdtemp(prefix="knowledge_sync_ul_"))
		archive_path = tmpdir / DEFAULT_OBJECT_NAME
		with tarfile.open(archive_path, "w:gz") as tar:
			tar.add(DATA_ROOT, arcname=DATA_ROOT.name)
		return archive_path

	def _extract_archive(self, archive_path: Path) -> None:
		if DATA_ROOT.exists():
			shutil.rmtree(DATA_ROOT)
		DATA_ROOT.parent.mkdir(parents=True, exist_ok=True)
		with tarfile.open(archive_path, "r:gz") as tar:
			self._safe_extract(tar, DATA_ROOT.parent)

	@staticmethod
	def _safe_extract(tar: tarfile.TarFile, target_dir: Path) -> None:
		target_dir = target_dir.resolve()
		for member in tar.getmembers():
			member_path = (target_dir / member.name).resolve()
			if not str(member_path).startswith(str(target_dir)):
				raise RemoteSyncError("Blocked path traversal attempt in archive")
		tar.extractall(path=target_dir)

	@staticmethod
	def _hash_file(path: Path) -> str:
		hasher = hashlib.sha256()
		with path.open("rb") as handle:
			for chunk in iter(lambda: handle.read(1024 * 1024), b""):
				hasher.update(chunk)
		return hasher.hexdigest()


knowledge_store_sync = KnowledgeStoreSync()

__all__ = ["knowledge_store_sync", "RemoteSyncError"]
