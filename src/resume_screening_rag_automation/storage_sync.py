"""Remote knowledge-store syncing helpers for Streamlit deployments."""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

from resume_screening_rag_automation.paths import DATA_ROOT

LOGGER = logging.getLogger(__name__)

try:  # Optional dependency for Cloudflare R2 (S3-compatible) sync.
	import boto3
except ImportError:  # pragma: no cover - boto3 optional for R2 deployments.
	boto3 = None

try:  # pragma: no cover - botocore ships with boto3 but guard for robustness.
	from botocore.exceptions import ClientError
except Exception:  # pragma: no cover - fallback when botocore missing during tests.
	ClientError = None  # type: ignore[assignment]

REMOTE_PROVIDER = os.getenv("REMOTE_STORAGE_PROVIDER", "r2").strip().lower()
DEFAULT_OBJECT_PREFIX = os.getenv("R2_OBJECT_PREFIX") or os.getenv("R2_OBJECT_NAME", "knowledge_store")
SYNC_INTERVAL_SECONDS = max(5.0, float(os.getenv("KNOWLEDGE_SYNC_MIN_INTERVAL", "30")))


class RemoteSyncError(RuntimeError):
	"""Raised when the remote storage backend cannot be initialised."""


class _BaseRemoteBackend:
	"""Interface implemented by remote storage providers."""

	def download_tree(self, target: Path) -> bool:  # pragma: no cover - abstract
		raise NotImplementedError

	def upload_tree(self, source: Path, manifest: str) -> None:  # pragma: no cover - abstract
		raise NotImplementedError

	def fetch_manifest(self) -> Optional[Dict[str, object]]:  # pragma: no cover - abstract
		raise NotImplementedError


class CloudflareR2Backend(_BaseRemoteBackend):
	"""Cloudflare R2 (S3-compatible) backend for syncing the knowledge directory."""

	def __init__(self) -> None:
		if boto3 is None:
			raise RemoteSyncError("boto3 is not installed; add 'boto3' to dependencies for R2 support")

		access_key = os.getenv("R2_ACCESS_KEY_ID")
		secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
		bucket = os.getenv("R2_BUCKET_NAME")
		endpoint = os.getenv("R2_ENDPOINT_URL")
		account_id = os.getenv("R2_ACCOUNT_ID")
		region = os.getenv("R2_REGION", "auto")

		if not access_key or not secret_key or not bucket:
			raise RemoteSyncError("Cloudflare R2 credentials missing (R2_ACCESS_KEY_ID/SECRET + R2_BUCKET_NAME)")
		if not endpoint:
			if not account_id:
				raise RemoteSyncError("Set R2_ENDPOINT_URL or R2_ACCOUNT_ID to build the endpoint URL")
			endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

		prefix = (DEFAULT_OBJECT_PREFIX or "knowledge_store").strip()
		if prefix.endswith(".tar.gz"):
			prefix = prefix[: -len(".tar.gz")]
		self.prefix = prefix.strip("/") or "knowledge_store"
		self.prefix_with_sep = f"{self.prefix}/" if self.prefix else ""
		self.manifest_key = f"{self.prefix_with_sep}.manifest.json" if self.prefix_with_sep else ".manifest.json"

		self.bucket = bucket
		self.client = boto3.client(
			"s3",
			endpoint_url=endpoint,
			aws_access_key_id=access_key,
			aws_secret_access_key=secret_key,
			region_name=region,
		)
		self._validate_bucket_access()

	def _validate_bucket_access(self) -> None:
		if ClientError is None:
			return
		try:
			self.client.head_bucket(Bucket=self.bucket)
		except Exception as exc:
			raise RemoteSyncError(f"Unable to access Cloudflare R2 bucket {self.bucket}: {exc}") from exc

	def download_tree(self, target: Path) -> bool:
		keys = self._list_objects()
		payload_keys = [key for key in keys if key not in {self.manifest_key} and not key.endswith("/")]
		if not payload_keys:
			return False
		
		for key in payload_keys:
			relative = key
			if self.prefix_with_sep and key.startswith(self.prefix_with_sep):
				relative = key[len(self.prefix_with_sep) :]
			destination = target / relative
			
			# Check if file exists and has same size (basic incremental check)
			# For more robust check, we'd need ETags/hashes, but size is a good start for speed
			try:
				head = self.client.head_object(Bucket=self.bucket, Key=key)
				remote_size = head['ContentLength']
				if destination.exists() and destination.stat().st_size == remote_size:
					continue
			except Exception:
				pass

			destination.parent.mkdir(parents=True, exist_ok=True)
			try:
				response = self.client.get_object(Bucket=self.bucket, Key=key)
			except self.client.exceptions.NoSuchKey:
				continue
			except Exception as exc:  # pragma: no cover - network errors depend on environment
				LOGGER.info("Cloudflare R2 download failed for %s: %s", key, exc)
				continue
			body = response.get("Body")
			if not body:
				continue
			destination.write_bytes(body.read())
		return True

	def upload_tree(self, source: Path, manifest: str) -> None:
		existing_keys = set(self._list_objects())
		uploaded_keys = set()
		for file_path in self._iter_files(source):
			relative_key = self._build_key(file_path.relative_to(source))
			uploaded_keys.add(relative_key)
			extra_args = self._build_extra_args(file_path)
			with file_path.open("rb") as handle:
				put_kwargs = {
					"Bucket": self.bucket,
					"Key": relative_key,
					"Body": handle,
				}
				if extra_args:
					put_kwargs.update(extra_args)
				self.client.put_object(**put_kwargs)
		self.client.put_object(
			Bucket=self.bucket,
			Key=self.manifest_key,
			Body=manifest.encode("utf-8"),
			ContentType="application/json",
		)
		self._prune_remote_objects(existing_keys, uploaded_keys)

	def fetch_manifest(self) -> Optional[Dict[str, object]]:
		try:
			response = self.client.get_object(Bucket=self.bucket, Key=self.manifest_key)
		except self.client.exceptions.NoSuchKey:
			return None
		except Exception as exc:  # pragma: no cover - network errors depend on environment
			LOGGER.info("Cloudflare R2 manifest fetch failed: %s", exc)
			return None
		body = response.get("Body")
		if body is None:
			return None
		try:
			return json.loads(body.read().decode("utf-8"))
		except Exception:
			LOGGER.warning("Cloudflare R2 manifest unreadable; proceeding without digest")
			return None

	def _list_objects(self) -> Iterable[str]:
		kwargs = {"Bucket": self.bucket}
		if self.prefix_with_sep:
			kwargs["Prefix"] = self.prefix_with_sep
		continuation: Optional[str] = None
		while True:
			if continuation:
				kwargs["ContinuationToken"] = continuation
			response = self.client.list_objects_v2(**kwargs)
			for obj in response.get("Contents", []) or []:
				yield obj["Key"]
			if not response.get("IsTruncated"):
				break
			continuation = response.get("NextContinuationToken")

	def _prune_remote_objects(self, existing_keys: Iterable[str], uploaded_keys: Iterable[str]) -> None:
		uploaded = set(uploaded_keys)
		stale = [key for key in existing_keys if key not in uploaded and key not in {self.manifest_key}]
		if not stale:
			return
		for i in range(0, len(stale), 1000):
			chunk = stale[i : i + 1000]
			self.client.delete_objects(
				Bucket=self.bucket,
				Delete={"Objects": [{"Key": key} for key in chunk]},
			)

	def _build_key(self, relative_path: Path) -> str:
		rel = relative_path.as_posix().lstrip("/")
		if self.prefix_with_sep:
			return f"{self.prefix_with_sep}{rel}" if rel else self.prefix_with_sep.rstrip("/")
		return rel

	def _build_extra_args(self, file_path: Path) -> Optional[Dict[str, str]]:
		content_type, _ = mimetypes.guess_type(str(file_path))
		if content_type:
			return {"ContentType": content_type, "CacheControl": "no-cache"}
		return {"CacheControl": "no-cache"}

	@staticmethod
	def _iter_files(root: Path) -> Iterable[Path]:
		for path in sorted(root.rglob("*")):
			if path.is_file():
				yield path


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
		"""Download the remote knowledge tree if configured."""

		if self._initialised:
			return
		self._initialised = True

		if not self._backend:
			return

		manifest = self._backend.fetch_manifest()
		remote_digest = (manifest or {}).get("digest") if manifest else None
		local_digest = self._hash_directory(DATA_ROOT) if DATA_ROOT.exists() else None
		if remote_digest and remote_digest == local_digest:
			self._last_digest = local_digest
			return

		snapshot = self._download_remote_snapshot()
		if not snapshot:
			LOGGER.info("Remote knowledge prefix empty; keeping existing knowledge_store")
			return

		try:
			self._replace_with_snapshot(snapshot)
			self._last_digest = remote_digest or self._hash_directory(DATA_ROOT)
		finally:
			shutil.rmtree(snapshot.parent, ignore_errors=True)

	def mark_dirty(self) -> None:
		"""Flag the knowledge store as having local changes."""

		if self._backend:
			self._dirty = True

	def flush_if_needed(self, *, force: bool = False) -> None:
		"""Upload remote objects when the local tree changes."""

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

		digest = self._hash_directory(DATA_ROOT)
		if not force and digest == self._last_digest:
			self._dirty = False
			return
		manifest = self._build_manifest(digest)
		try:
			self._backend.upload_tree(DATA_ROOT, manifest)
		except Exception as exc:  # pragma: no cover - network failures depend on env
			LOGGER.warning("Failed to upload knowledge objects; will retry later: %s", exc)
			self._dirty = True
			return
		self._last_digest = digest
		self._last_flush = now
		self._dirty = False

	def flush(self) -> None:
		"""Force a sync regardless of throttling."""

		self.flush_if_needed(force=True)

	def _download_remote_snapshot(self) -> Optional[Path]:
		if not self._backend:
			return None

		tmpdir = Path(tempfile.mkdtemp(prefix="knowledge_sync_dl_"))
		target = tmpdir / "data"
		target.mkdir()
		try:
			if not self._backend.download_tree(target):
				shutil.rmtree(tmpdir, ignore_errors=True)
				return None
			return target
		except Exception as exc:  # pragma: no cover - depends on backend implementation
			shutil.rmtree(tmpdir, ignore_errors=True)
			raise RemoteSyncError(f"Failed to download remote objects: {exc}") from exc

	def _replace_with_snapshot(self, snapshot: Path) -> None:
		backup = self._evict_existing_data()
		DATA_ROOT.parent.mkdir(parents=True, exist_ok=True)
		try:
			shutil.move(str(snapshot), DATA_ROOT)
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

	def _build_manifest(self, digest: str) -> str:
		file_count = sum(1 for _ in self._iter_files(DATA_ROOT)) if DATA_ROOT.exists() else 0
		payload = {
			"digest": digest,
			"file_count": file_count,
			"generated_at": time.time(),
			"version": 1,
		}
		return json.dumps(payload, separators=(",", ":"), sort_keys=True)

	@staticmethod
	def _iter_files(root: Path) -> Iterable[Path]:
		for path in sorted(root.rglob("*")):
			if path.is_file():
				yield path

	@classmethod
	def _hash_directory(cls, root: Path) -> str:
		if not root.exists():
			return ""
		hasher = hashlib.sha256()
		for file_path in cls._iter_files(root):
			relative = file_path.relative_to(root).as_posix()
			hasher.update(relative.encode("utf-8"))
			hasher.update(b"\0")
			hasher.update(cls._hash_file(file_path).encode("utf-8"))
		return hasher.hexdigest()

	@staticmethod
	def _hash_file(path: Path) -> str:
		hasher = hashlib.sha256()
		with path.open("rb") as handle:
			for chunk in iter(lambda: handle.read(1024 * 1024), b""):
				hasher.update(chunk)
		return hasher.hexdigest()


knowledge_store_sync = KnowledgeStoreSync()

__all__ = ["knowledge_store_sync", "RemoteSyncError"]
