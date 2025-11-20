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
from typing import Optional

from resume_screening_rag_automation.paths import DATA_ROOT

LOGGER = logging.getLogger(__name__)

try:  # Optional dependency for Cloudflare R2 (S3-compatible) sync.
	import boto3
except ImportError:  # pragma: no cover - boto3 optional for R2 deployments.
	boto3 = None

REMOTE_PROVIDER = os.getenv("REMOTE_STORAGE_PROVIDER", "r2").strip().lower()
DEFAULT_OBJECT_NAME = os.getenv("R2_OBJECT_NAME", "knowledge_store.tar.gz")
SYNC_INTERVAL_SECONDS = max(5.0, float(os.getenv("KNOWLEDGE_SYNC_MIN_INTERVAL", "30")))


class RemoteSyncError(RuntimeError):
	"""Raised when the remote storage backend cannot be initialised."""


class _BaseRemoteBackend:
	"""Interface implemented by remote storage providers."""

	def download_archive(self, target: Path) -> bool:  # pragma: no cover - abstract
		raise NotImplementedError

	def upload_archive(self, source: Path) -> None:  # pragma: no cover - abstract
		raise NotImplementedError


class CloudflareR2Backend(_BaseRemoteBackend):
	"""Cloudflare R2 (S3-compatible) backend for syncing the knowledge archive."""

	def __init__(self) -> None:
		if boto3 is None:
			raise RemoteSyncError("boto3 is not installed; add 'boto3' to dependencies for R2 support")

		access_key = os.getenv("R2_ACCESS_KEY_ID")
		secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
		bucket = os.getenv("R2_BUCKET_NAME")
		object_name = os.getenv("R2_OBJECT_NAME", DEFAULT_OBJECT_NAME)
		endpoint = os.getenv("R2_ENDPOINT_URL")
		account_id = os.getenv("R2_ACCOUNT_ID")
		region = os.getenv("R2_REGION", "auto")

		if not access_key or not secret_key or not bucket:
			raise RemoteSyncError("Cloudflare R2 credentials missing (R2_ACCESS_KEY_ID/SECRET + R2_BUCKET_NAME)")
		if not endpoint:
			if not account_id:
				raise RemoteSyncError("Set R2_ENDPOINT_URL or R2_ACCOUNT_ID to build the endpoint URL")
			endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

		self.bucket = bucket
		self.object_name = object_name
		self.client = boto3.client(
			"s3",
			endpoint_url=endpoint,
			aws_access_key_id=access_key,
			aws_secret_access_key=secret_key,
			region_name=region,
		)

	def download_archive(self, target: Path) -> bool:
		try:
			response = self.client.get_object(Bucket=self.bucket, Key=self.object_name)
		except self.client.exceptions.NoSuchKey:
			LOGGER.info("Cloudflare R2 object %s/%s missing", self.bucket, self.object_name)
			return False
		except Exception as exc:  # pragma: no cover - network errors depend on environment
			LOGGER.info("Cloudflare R2 download failed: %s", exc)
			return False

		target.parent.mkdir(parents=True, exist_ok=True)
		body = response.get("Body")
		if body is None:
			return False
		target.write_bytes(body.read())
		return True

	def upload_archive(self, source: Path) -> None:
		with source.open("rb") as handle:
			self.client.upload_fileobj(
				handle,
				self.bucket,
				self.object_name,
				ExtraArgs={
					"ContentType": "application/gzip",
					"CacheControl": "no-cache",
				},
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

		if REMOTE_PROVIDER in {"r2", "cloudflare", "cloudflare-r2"}:
			try:
				return CloudflareR2Backend()
			except RemoteSyncError as exc:
				LOGGER.warning("Cloudflare R2 backend unavailable: %s", exc)
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
		backup = self._evict_existing_data()
		DATA_ROOT.parent.mkdir(parents=True, exist_ok=True)
		try:
			with tarfile.open(archive_path, "r:gz") as tar:
				self._safe_extract(tar, DATA_ROOT.parent)
		except Exception:
			if DATA_ROOT.exists():
				shutil.rmtree(DATA_ROOT, ignore_errors=True)
			if backup and backup.exists():
				backup.rename(DATA_ROOT)
			raise
		else:
			if backup and backup.exists():
				shutil.rmtree(backup, ignore_errors=True)

	def _evict_existing_data(self) -> Optional[Path]:
		if not DATA_ROOT.exists():
			return None
		try:
			shutil.rmtree(DATA_ROOT)
			return None
		except OSError as exc:
			LOGGER.warning("Unable to remove %s directly (%s); falling back to rename", DATA_ROOT, exc)
		backup = DATA_ROOT.with_name(f"{DATA_ROOT.name}_stale_{int(time.time())}")
		try:
			DATA_ROOT.rename(backup)
		except OSError as rename_exc:
			LOGGER.error("Failed to rename stale knowledge store %s: %s", DATA_ROOT, rename_exc)
			raise
		return backup

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
