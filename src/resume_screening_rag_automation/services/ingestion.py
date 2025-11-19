"""Helpers for monitoring resume folders and triggering ingestion."""

from __future__ import annotations

import json
import logging
import os
import re
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from resume_screening_rag_automation.core.ingestion_models import (
    ResumeIngestionOutput,
    ResumeMonitorOutput,
    ResumeParsingInput,
    ResumeParsingOutput,
)
from resume_screening_rag_automation.core.py_models import (
    EducationItem,
    ExperienceItem,
    Metadata,
    Resume,
    ResumeContent,
    ResumeFileInfo,
    SkillsSection,
)
from resume_screening_rag_automation.paths import RAW_RESUME_DIR, STRUCTURED_RESUMES_PATH
from resume_screening_rag_automation.storage_sync import knowledge_store_sync
from resume_screening_rag_automation.tools.build_resume_vector_db import sync_resume_vector_db
from resume_screening_rag_automation.tools.constants import RESUME_COLLECTION_NAME


logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = PROJECT_ROOT.parent

_CV_DIR_CANDIDATES: Tuple[Path, ...] = (
    RAW_RESUME_DIR,
    PROJECT_ROOT / "cv_txt",
    PROJECT_ROOT.parent / "cv_txt",
    REPO_ROOT / "cv_txt",
    Path.cwd() / "cv_txt",
)

_KNOWLEDGE_FILE_CANDIDATES: Tuple[Path, ...] = (
    STRUCTURED_RESUMES_PATH,
    PROJECT_ROOT / "knowledge" / "structured_resumes.json",
    PROJECT_ROOT / "structured_resumes.json",
    PROJECT_ROOT.parent / "knowledge" / "structured_resumes.json",
    REPO_ROOT / "structured_resumes.json",
)

_MAX_FILES_PER_CREW_BATCH = 1
_MAX_PARALLEL_CREWS = 4
_PIPELINE_STATE: Dict[str, Any] = {"monitor": None, "ingestion": None, "ran": False}

_CANDIDATE_PATTERN = re.compile(r"^CAND(\d+)$", re.IGNORECASE)
_SUMMARY_SECTION_TOKENS = ("summary", "profile", "professional summary", "objective")


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _explode_skill_text(text: str) -> List[str]:
    separators = [",", "/", "\n", "|", "•", "*"]
    if any(separator in text for separator in separators):
        parts = re.split(r",|/|\n|\||•|\*", text)
        return [part.strip() for part in parts if part.strip()]
    return [text.strip()]


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        cleaned = _clean_string(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _guess_candidate_name(text: str, file_name: str) -> Optional[str]:
    if text:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            cleaned = re.sub(r"[^A-Za-z\s]", " ", stripped)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if not cleaned:
                continue
            word_count = len(cleaned.split())
            if 1 <= word_count <= 6 and 2 <= len(cleaned) <= 80:
                return cleaned.title()
    stem = Path(file_name).stem
    stem_clean = re.sub(r"[^A-Za-z\s]", " ", stem)
    parts = [part for part in re.split(r"[\s_]+", stem_clean) if part]
    filtered = [part for part in parts if part.lower() not in {"resume", "cv", "copy"}]
    if filtered:
        return " ".join(part.capitalize() for part in filtered)
    return None


def _build_fallback_resume(info: ResumeFileInfo, text: str) -> Resume:
    candidate_name = _guess_candidate_name(text, info.file_name)
    fallback_metadata = Metadata(
        file_name=info.file_name,
        candidate_name=candidate_name,
        candidate_id=None,
        current_title=None,
        content_hash=info.content_hash,
    )
    summary = _extract_summary(text)
    fallback_content = ResumeContent(
        title=None,
        summary=summary,
        experience=[],
        skills=SkillsSection(),
        education=[],
        languages=[],
        other={"raw_text": text},
    )
    return Resume(metadata=fallback_metadata, content=fallback_content)


def _resolve_resume_directory() -> Optional[Path]:
    try:
        RAW_RESUME_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:  # pragma: no cover - defensive guard for restricted fs
        logger.debug("Unable to ensure resume directory at %s", RAW_RESUME_DIR, exc_info=True)
    for candidate in _CV_DIR_CANDIDATES:
        if candidate and candidate.exists():
            return candidate
    return None


def _resolve_knowledge_path() -> Path:
    for candidate in _KNOWLEDGE_FILE_CANDIDATES:
        if candidate.exists():
            return candidate
    # Default to the first candidate even if it does not yet exist.
    return _KNOWLEDGE_FILE_CANDIDATES[0]


def _load_structured_resumes(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to read knowledge file at %s", path)
        return []
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("Invalid JSON in %s", path)
        return []
    if not isinstance(data, list):
        logger.error("Knowledge file %s must contain a list of resumes", path)
        return []
    return data


def _save_structured_resumes(path: Path, data: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(list(data), indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write knowledge file at %s", path)


def _compute_file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _format_mtime(stats: os.stat_result) -> str:
    return (
        datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _list_resume_files(root: Path) -> List[ResumeFileInfo]:
    candidates: List[ResumeFileInfo] = []
    for path in sorted(root.glob("*.txt")):
        if not path.is_file():
            continue
        stats = path.stat()
        info = ResumeFileInfo(
            file_name=path.name,
            path=str(path.resolve()),
            size_bytes=stats.st_size,
            modified_at=_format_mtime(stats),
            content_hash=_compute_file_hash(path),
        )
        candidates.append(info)
    return candidates


def _prune_duplicate_resume_files(resume_dir: Path) -> None:
    """Remove duplicate resume files by content hash, keeping the newest copy."""
    if not resume_dir.exists():
        return

    winners: Dict[str, Dict[str, Any]] = {}
    duplicates: List[Path] = []

    for path in sorted(resume_dir.glob("*.txt")):
        if not path.is_file():
            continue
        try:
            stats = path.stat()
            file_hash = _compute_file_hash(path)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Unable to inspect %s: %s", path, exc)
            continue

        record = {"path": path, "mtime": stats.st_mtime}
        existing = winners.get(file_hash)
        if existing is None or record["mtime"] > existing["mtime"]:
            if existing is not None:
                duplicates.append(existing["path"])
            winners[file_hash] = record
        else:
            duplicates.append(path)

    removed = 0
    seen: set[Path] = set()
    for duplicate in duplicates:
        if duplicate in seen:
            continue
        seen.add(duplicate)
        try:
            duplicate.unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to delete duplicate resume %s: %s", duplicate, exc)

    if removed:
        logger.info("Removed %s duplicate resume file(s) from %s", removed, resume_dir)


def _existing_hashes(records: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for record in records:
        meta = record.get("metadata", {}) or {}
        content_hash = _clean_string(meta.get("content_hash"))
        if content_hash:
            mapping[content_hash.lower()] = record
    return mapping


def _build_resume_file_info_from_record(record: Dict[str, Any], *, resume_dir: Optional[Path] = None) -> ResumeFileInfo:
    meta = record.get("metadata", {}) or {}
    file_name = _clean_string(meta.get("file_name")) or "unknown_resume.txt"
    source_path = _clean_string(meta.get("source_path"))
    if source_path:
        path = Path(source_path)
    elif resume_dir:
        path = resume_dir / file_name
    else:
        path = Path(file_name)
    size_bytes = int(meta.get("size_bytes") or 0)
    modified_at = _clean_string(meta.get("ingested_at")) or _utc_now_iso()
    content_hash = _clean_string(meta.get("content_hash")) or None
    return ResumeFileInfo(
        file_name=file_name,
        path=str(path),
        size_bytes=size_bytes,
        modified_at=modified_at,
        content_hash=content_hash,
    )


def _next_candidate_counter(records: Sequence[Dict[str, Any]]) -> int:
    max_counter = 0
    for record in records:
        meta = record.get("metadata", {}) or {}
        candidate_id = _clean_string(meta.get("candidate_id"))
        if not candidate_id:
            continue
        match = _CANDIDATE_PATTERN.match(candidate_id)
        if match:
            try:
                max_counter = max(max_counter, int(match.group(1)))
            except ValueError:
                continue
    return max_counter


def _extract_summary(full_text: str) -> Optional[str]:
    if not full_text:
        return None
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    if not lines:
        return None
    # Prefer explicit section markers when available.
    summary_lines: List[str] = []
    capture = False
    for line in lines:
        lowered = line.lower().strip(":-")
        if lowered in _SUMMARY_SECTION_TOKENS:
            capture = True
            continue
        if capture:
            if lowered.isupper() and len(lowered.split()) <= 4:
                break
            summary_lines.append(line)
            if len(summary_lines) >= 5:
                break
    if not summary_lines:
        summary_lines = lines[:3]
    summary = " ".join(summary_lines)
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary or None


def _normalise_experience(raw_items: Any) -> List[ExperienceItem]:
    if raw_items is None:
        return []
    if isinstance(raw_items, dict):
        iterable = raw_items.values()
    elif isinstance(raw_items, list):
        iterable = raw_items
    else:
        return []

    normalised: List[ExperienceItem] = []
    for item in iterable:
        if not item:
            continue
        if isinstance(item, ExperienceItem):
            normalised.append(item)
            continue
        if isinstance(item, dict):
            payload = {
                "title": _clean_string(item.get("title") or item.get("TITLE")) or None,
                "company": _clean_string(item.get("company") or item.get("COMPANY")) or None,
                "period": _clean_string(item.get("period") or item.get("PERIOD")) or None,
                "location": _clean_string(item.get("location") or item.get("LOCATION")) or None,
                "roles": [],
            }
            roles = item.get("roles") or item.get("ROLES")
            if isinstance(roles, list):
                payload["roles"] = [role for role in (_clean_string(role) for role in roles) if role]
            elif isinstance(roles, str):
                payload["roles"] = [_clean_string(role) for role in _explode_skill_text(roles) if _clean_string(role)]
            normalised.append(ExperienceItem(**payload))
        else:
            title = _clean_string(item)
            if title:
                normalised.append(ExperienceItem(title=title))
    return normalised


def _normalise_education(raw_items: Any) -> List[EducationItem]:
    if raw_items is None:
        return []
    if isinstance(raw_items, dict):
        iterable = raw_items.values()
    elif isinstance(raw_items, list):
        iterable = raw_items
    else:
        return []

    normalised: List[EducationItem] = []
    for item in iterable:
        if not item:
            continue
        if isinstance(item, EducationItem):
            normalised.append(item)
            continue
        if isinstance(item, dict):
            notes_raw = item.get("notes") or item.get("NOTES") or []
            notes: List[str] = []
            if isinstance(notes_raw, list):
                notes = [_clean_string(note) for note in notes_raw if _clean_string(note)]
            elif isinstance(notes_raw, str):
                notes = [_clean_string(notes_raw)] if _clean_string(notes_raw) else []
            payload = {
                "degree": _clean_string(item.get("degree") or item.get("DEGREE")) or None,
                "institution": _clean_string(item.get("institution") or item.get("INSTITUTION")) or None,
                "period": _clean_string(item.get("period") or item.get("PERIOD")) or None,
                "notes": notes,
            }
            if any(payload.values()):
                normalised.append(EducationItem(**payload))
        else:
            text = _clean_string(item)
            if text:
                normalised.append(EducationItem(degree=text))
    return normalised


def _normalise_skills(raw_items: Any) -> SkillsSection:
    """Coerce arbitrary payloads into the unified `SkillsSection` model."""

    if isinstance(raw_items, SkillsSection):
        return raw_items

    if raw_items is None:
        return SkillsSection()

    if isinstance(raw_items, dict):
        try:
            return SkillsSection.model_validate(raw_items)
        except Exception:
            technical_raw = raw_items.get("technical")
            soft_raw = raw_items.get("soft")
            return SkillsSection(
                technical=_dedupe(_coerce_list(technical_raw)),
                soft=_dedupe(_coerce_list(soft_raw)),
            )

    if isinstance(raw_items, list):
        values = _coerce_list(raw_items)
        return SkillsSection(technical=_dedupe(values))

    if isinstance(raw_items, str):
        value = _clean_string(raw_items)
        return SkillsSection(technical=[value] if value else [])

    return SkillsSection()


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_string(item) for item in value if _clean_string(item)]
    if isinstance(value, str):
        cleaned = _clean_string(value)
        return [cleaned] if cleaned else []
    return []


def _normalise_languages(raw_items: Any) -> List[str]:
    if raw_items is None:
        return []

    def _flatten(value: Any, bucket: List[str]) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for item in value.values():
                _flatten(item, bucket)
            return
        if isinstance(value, list):
            for item in value:
                _flatten(item, bucket)
            return
        cleaned = _clean_string(value)
        if cleaned:
            bucket.append(cleaned)

    raw_values: List[str] = []
    _flatten(raw_items, raw_values)
    languages: List[str] = []
    for value in raw_values:
        for candidate in _explode_skill_text(value):
            cleaned = _clean_string(candidate)
            if not cleaned:
                continue
            if len(cleaned) > 40:
                continue
            languages.append(cleaned.title())
    return _dedupe(languages)


def _slugify_section(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return slug.strip("_") or "section"


def _collect_other_sections(content: Dict[str, Any], consumed: set[str]) -> Dict[str, Any]:
    other: Dict[str, Any] = {}
    for key, value in (content or {}).items():
        if not isinstance(key, str):
            continue
        lowered = key.strip().lower()
        slug = _slugify_section(key)
        if lowered in consumed or slug in consumed:
            continue
        other[slug] = value
    return other


def run_resume_folder_monitor() -> Tuple[ResumeMonitorOutput, List[ResumeFileInfo]]:
    resume_dir = _resolve_resume_directory()
    if resume_dir:
        _prune_duplicate_resume_files(resume_dir)
    knowledge_path = _resolve_knowledge_path()
    existing_records = _load_structured_resumes(knowledge_path)
    inspected_at = _utc_now_iso()
    files = _list_resume_files(resume_dir) if resume_dir else []

    monitor_output = _calculate_resume_deltas(
        files,
        existing_records,
        resume_dir,
        len(existing_records),
        inspected_at,
    )

    if not monitor_output.inspected_at:
        monitor_output.inspected_at = inspected_at
    if not monitor_output.knowledge_count:
        monitor_output.knowledge_count = len(existing_records)

    return monitor_output, monitor_output.new_files


def _calculate_resume_deltas(
    files: Sequence[ResumeFileInfo],
    existing_records: Sequence[dict],
    resume_dir: Optional[Path],
    knowledge_count: int,
    inspected_at: str,
) -> ResumeMonitorOutput:
    existing_hash_map = _existing_hashes(existing_records)
    new_files: List[ResumeFileInfo] = []
    duplicate_files: List[ResumeFileInfo] = []

    for info in files:
        content_hash = (info.content_hash or "").lower()
        if content_hash and content_hash in existing_hash_map:
            record = existing_hash_map[content_hash]
            candidate_id = (record.get("metadata", {}) or {}).get("candidate_id")
            duplicate_files.append(info.model_copy(update={"candidate_id": candidate_id}))
        else:
            new_files.append(info)

    current_names = {info.file_name for info in files}
    removed_files: List[ResumeFileInfo] = []
    for record in existing_records:
        meta = record.get("metadata", {}) or {}
        file_name = meta.get("file_name")
        if file_name and file_name not in current_names:
            removed_files.append(_build_resume_file_info_from_record(record, resume_dir=resume_dir))

    return ResumeMonitorOutput(
        new_files=new_files,
        removed_files=removed_files,
        duplicate_files=duplicate_files,
        inspected_at=inspected_at,
        knowledge_count=knowledge_count,
    )


def _parse_resumes_with_ai(
    file_infos: Sequence[ResumeFileInfo],
    existing_records: Sequence[dict],
    resume_texts: Optional[Dict[str, str]] = None,
) -> ResumeParsingOutput:
    if not file_infos:
        return ResumeParsingOutput()

    try:
        from resume_screening_rag_automation.crews.resume_parsing_crew.resume_parsing_crew import (
            ResumeParsingCrew,
        )
    except Exception as exc:
        logger.warning("ResumeParsingCrew unavailable: %s", exc)
        return ResumeParsingOutput(
            warnings=[
                "ResumeParsingCrew unavailable; falling back to deterministic parser.",
            ]
        )

    aggregated_resumes: List[Resume] = []
    aggregated_warnings: List[str] = []

    batches: List[List[ResumeFileInfo]] = []
    for start in range(0, len(file_infos), _MAX_FILES_PER_CREW_BATCH):
        batch = [info for info in file_infos[start : start + _MAX_FILES_PER_CREW_BATCH] if info.file_name]
        if batch:
            batches.append(batch)

    if not batches:
        return ResumeParsingOutput()

    def _process_batch(batch_infos: List[ResumeFileInfo]) -> Tuple[List[Resume], List[str]]:
        preview_map: Dict[str, str] = {}
        if resume_texts:
            for info in batch_infos:
                if info.file_name and info.file_name in resume_texts:
                    preview_map[info.file_name] = resume_texts[info.file_name][:2000]

        payload = ResumeParsingInput(
            files=batch_infos,
            resume_texts=preview_map,
            existing_records=list(existing_records),
        )

        crew = ResumeParsingCrew().crew()
        try:
            result = crew.kickoff(inputs=payload.model_dump())
        except Exception as exc:
            batch_label = ", ".join(sorted(info.file_name for info in batch_infos if info.file_name)) or "unknown files"
            logger.exception("ResumeParsingCrew execution failed for %s", batch_label)
            return [], [f"ResumeParsingCrew execution failed for {batch_label}: {exc}"]

        try:
            if isinstance(result, ResumeParsingOutput):
                batch_output = result
            else:
                parsed_payload = getattr(result, "pydantic", None) or getattr(result, "raw", None) or result
                batch_output = ResumeParsingOutput.model_validate(parsed_payload)
        except Exception:
            batch_label = ", ".join(sorted(info.file_name for info in batch_infos if info.file_name)) or "unknown files"
            logger.exception("Unable to validate ResumeParsingCrew output for %s", batch_label)
            return [], [
                "Invalid ResumeParsingCrew response; falling back to deterministic parser."
            ]

        parsed_list = list(batch_output.parsed_resumes)
        warn_list = list(batch_output.warnings)
        return parsed_list, warn_list

    max_workers = max(1, min(len(batches), _MAX_PARALLEL_CREWS))

    if max_workers == 1:
        for batch in batches:
            parsed, warns = _process_batch(batch)
            aggregated_resumes.extend(parsed)
            aggregated_warnings.extend(warns)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process_batch, batch): batch for batch in batches}
            for future in as_completed(futures):
                try:
                    parsed, warns = future.result()
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.exception("Unexpected ResumeParsingCrew failure: %s", exc)
                    continue
                aggregated_resumes.extend(parsed)
                aggregated_warnings.extend(warns)

    return ResumeParsingOutput(parsed_resumes=aggregated_resumes, warnings=aggregated_warnings)


def apply_ingestion_updates(
    file_infos: Sequence[ResumeFileInfo],
    *,
    removed_files: Sequence[ResumeFileInfo] | None = None,
    knowledge_path: Optional[Path] = None,
    collection_name: str = RESUME_COLLECTION_NAME,
    rebuild_embeddings: bool = True,
) -> ResumeIngestionOutput:
    knowledge_file = Path(knowledge_path).resolve() if knowledge_path else _resolve_knowledge_path()
    existing_records = _load_structured_resumes(knowledge_file)
    removed_list = list(removed_files or [])

    existing_by_hash: Dict[str, dict] = {}
    existing_by_file: Dict[str, dict] = {}
    for record in existing_records:
        meta = (record.get("metadata") or {}) if isinstance(record, dict) else {}
        if not isinstance(meta, dict):
            continue
        existing_hash = _clean_string(meta.get("content_hash")).lower()
        existing_file = _clean_string(meta.get("file_name")).lower()
        if existing_hash and existing_hash not in existing_by_hash:
            existing_by_hash[existing_hash] = record
        if existing_file and existing_file not in existing_by_file:
            existing_by_file[existing_file] = record

    warnings: List[str] = []
    start_time = perf_counter()

    next_counter = _next_candidate_counter(existing_records)

    new_resumes: List[Resume] = []
    records_for_store: List[dict] = []
    embedded_candidate_ids: set[str] = set()
    removed_candidate_ids: set[str] = set()

    removed_names = {info.file_name.lower() for info in removed_list if info.file_name}
    removed_hashes = {info.content_hash.lower() for info in removed_list if info.content_hash}

    file_records: List[Dict[str, Any]] = []

    for info in file_infos:
        path = Path(info.path)
        if not path.exists():
            warnings.append(f"File not found: {info.path}")
            continue

        try:
            stats = path.stat()
        except Exception as exc:
            warnings.append(f"Failed to inspect {info.file_name}: {exc}")
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                warnings.append(
                    f"Non-UTF8 characters ignored while reading {info.file_name}; some symbols may be missing."
                )
            except Exception as exc:
                warnings.append(f"Failed to read {info.file_name}: {exc}")
                continue
        except Exception as exc:
            warnings.append(f"Failed to read {info.file_name}: {exc}")
            continue

        file_records.append(
            {
                "info": info,
                "text": text,
                "mtime": stats.st_mtime,
                "hash": (info.content_hash.lower() if info.content_hash else None),
            }
        )

        if info.content_hash:
            removed_hashes.discard(info.content_hash.lower())
        if info.file_name:
            removed_names.discard(info.file_name.lower())

    deduped_records: List[Dict[str, Any]] = []
    hash_winners: Dict[str, Dict[str, Any]] = {}
    hash_duplicates: Dict[str, List[Dict[str, Any]]] = {}

    for record in file_records:
        hash_key = record["hash"]
        if hash_key:
            winner = hash_winners.get(hash_key)
            if winner is None:
                hash_winners[hash_key] = record
            else:
                if record["mtime"] > winner["mtime"]:
                    hash_duplicates.setdefault(hash_key, []).append(winner)
                    hash_winners[hash_key] = record
                else:
                    hash_duplicates.setdefault(hash_key, []).append(record)
        else:
            deduped_records.append(record)

    for hash_key, winner in hash_winners.items():
        deduped_records.append(winner)
        duplicates = hash_duplicates.get(hash_key, [])
        if duplicates:
            hash_hint = hash_key[:8] if hash_key else "unknown"
            for duplicate in duplicates:
                warnings.append(
                    f"Duplicate resume detected (hash {hash_hint}): ignoring {duplicate['info'].file_name} in favour of {winner['info'].file_name}."
                )

    readable_infos = [record["info"] for record in deduped_records]
    resume_texts = {record["info"].file_name: record["text"] for record in deduped_records}

    parsing_output = _parse_resumes_with_ai(
        readable_infos,
        existing_records,
        resume_texts=resume_texts,
    )
    warnings.extend(parsing_output.warnings)

    parsed_map: Dict[str, Resume] = {}
    for parsed_resume in parsing_output.parsed_resumes:
        try:
            resume_obj = (
                parsed_resume
                if isinstance(parsed_resume, Resume)
                else Resume.model_validate(parsed_resume)
            )
        except Exception as exc:
            warnings.append(f"Invalid parsed resume payload skipped: {exc}")
            continue
        file_key = (resume_obj.metadata.file_name or "").strip().lower()
        if not file_key:
            warnings.append("Parsed resume missing file_name; ignoring entry.")
            continue
        parsed_map[file_key] = resume_obj

    for info in readable_infos:
        text = resume_texts.get(info.file_name, "")
        parsed_resume = parsed_map.get(info.file_name.lower())
        if not parsed_resume:
            warnings.append(
                f"No structured output returned for {info.file_name}; using fallback parser."
            )
            parsed_resume = _build_fallback_resume(info, text)

        existing_record: Optional[dict] = None
        hash_key = info.content_hash.lower() if info.content_hash else None
        if hash_key:
            existing_record = existing_by_hash.get(hash_key)
        if not existing_record:
            existing_record = existing_by_file.get(info.file_name.lower())
        existing_metadata = (existing_record.get("metadata") if isinstance(existing_record, dict) else {}) or {}

        parsed_payload = {
            "metadata": parsed_resume.metadata.model_dump(),
            "content": parsed_resume.content.model_dump(),
        }

        metadata = dict(parsed_payload.get("metadata") or {})
        if not _clean_string(metadata.get("candidate_name")) and _clean_string(existing_metadata.get("candidate_name")):
            metadata["candidate_name"] = existing_metadata.get("candidate_name")
        if not _clean_string(metadata.get("current_title")) and _clean_string(existing_metadata.get("current_title")):
            metadata["current_title"] = existing_metadata.get("current_title")
        metadata["file_name"] = info.file_name
        metadata["source_path"] = info.path
        metadata["size_bytes"] = info.size_bytes
        metadata["ingested_at"] = _utc_now_iso()
        if info.content_hash:
            metadata["content_hash"] = info.content_hash

        parsed_candidate_id = _clean_string(metadata.get("candidate_id")) or None
        existing_candidate_id = _clean_string(existing_metadata.get("candidate_id")) or None
        candidate_id = parsed_candidate_id or existing_candidate_id
        if not candidate_id:
            next_counter += 1
            candidate_id = f"CAND{next_counter:03d}"
        else:
            match = _CANDIDATE_PATTERN.match(candidate_id)
            if match:
                try:
                    next_counter = max(next_counter, int(match.group(1)))
                except ValueError:
                    pass
        metadata["candidate_id"] = candidate_id

        if candidate_id:
            embedded_candidate_ids.add(candidate_id)

        content: Dict[str, Any] = dict(parsed_payload.get("content") or {})

        summary_text = (
            _clean_string(content.get("summary"))
            or _clean_string(content.get("SUMMARY"))
            or _extract_summary(text)
        )

        title_text = (
            _clean_string(content.get("title"))
            or _clean_string(content.get("TITLE"))
            or metadata.get("current_title")
        )

        experience_items = _normalise_experience(content.get("experience") or content.get("EXPERIENCE"))
        education_items = _normalise_education(content.get("education") or content.get("EDUCATION"))
        skills_section = _normalise_skills(content.get("skills") or content.get("SKILLS"))
        language_items = _normalise_languages(content.get("languages") or content.get("LANGUAGES"))

        other_payload = content.get("other")
        other_sections = dict(other_payload) if isinstance(other_payload, dict) else {}

        consumed_sections = {
            "summary",
            "experience",
            "education",
            "skills",
            "languages",
            "title",
            "other",
        }

        additional_sections = _collect_other_sections(content, consumed_sections)
        if additional_sections:
            other_sections.update(additional_sections)
        other_sections.setdefault("raw_text", text)

        metadata_model = Metadata(
            file_name=metadata.get("file_name"),
            candidate_name=_clean_string(metadata.get("candidate_name")) or None,
            candidate_id=metadata.get("candidate_id"),
            current_title=_clean_string(metadata.get("current_title")) or None,
            content_hash=metadata.get("content_hash") or (info.content_hash if info.content_hash else None),
        )

        resume_model = Resume(
            metadata=metadata_model,
            content=ResumeContent(
                title=title_text,
                summary=summary_text,
                experience=experience_items,
                skills=skills_section,
                education=education_items,
                languages=language_items,
                other=other_sections,
            ),
        )

        record = resume_model.model_dump(mode="json")
        record.setdefault("metadata", {})
        record["metadata"]["content_hash"] = metadata_model.content_hash
        records_for_store.append(record)
        new_resumes.append(resume_model)

    new_file_names = {info.file_name.lower() for info in readable_infos if info.file_name}

    filtered_records: List[dict] = []
    existing_hash_seen: set[str] = set()
    for record in existing_records:
        meta = record.get("metadata", {}) or {}
        original_file_name = meta.get("file_name") or ""
        file_name = original_file_name.lower()
        content_hash = (meta.get("content_hash") or "").lower()
        candidate_identifier = _clean_string(meta.get("candidate_id")) or _clean_string(original_file_name)

        removed_record = False
        if file_name and file_name in removed_names:
            removed_record = True
        elif content_hash and content_hash in removed_hashes:
            removed_record = True
        elif file_name and file_name in new_file_names:
            removed_record = True

        if removed_record:
            if candidate_identifier:
                removed_candidate_ids.add(candidate_identifier)
            continue

        if content_hash and content_hash in existing_hash_seen:
            if candidate_identifier:
                removed_candidate_ids.add(candidate_identifier)
            continue

        if content_hash:
            existing_hash_seen.add(content_hash)

        filtered_records.append(record)

    records_to_store = filtered_records + records_for_store

    knowledge_target = knowledge_file
    store_changed = records_to_store != existing_records or not knowledge_target.exists()
    if store_changed:
        _save_structured_resumes(knowledge_target, records_to_store)

    vector_sync_result: Optional[Dict[str, Any]] = None
    if rebuild_embeddings and collection_name:
        removed_candidate_ids.difference_update(embedded_candidate_ids)
        candidate_id_list = sorted(embedded_candidate_ids)
        removed_id_list = sorted(removed_candidate_ids)
        if candidate_id_list or removed_id_list or store_changed:
            try:
                vector_sync_result = sync_resume_vector_db(
                    collection_name=collection_name,
                    candidate_ids=candidate_id_list,
                    removed_candidate_ids=removed_id_list,
                    knowledge_json=knowledge_target,
                )
                error_message = vector_sync_result.get("error") if vector_sync_result else None
                if error_message:
                    warnings.append(str(error_message))
                else:
                    logger.info(
                        "Vector store sync complete: upserted=%s removed=%s total=%s",
                        vector_sync_result.get("upserted_chunks") if vector_sync_result else None,
                        vector_sync_result.get("removed_candidates") if vector_sync_result else None,
                        vector_sync_result.get("count") if vector_sync_result else None,
                    )
            except Exception as exc:
                logger.exception("Vector store sync failed")
                warnings.append(f"Vector store sync failed: {exc}")

    elapsed = round(perf_counter() - start_time, 3)

    if store_changed or (vector_sync_result and not vector_sync_result.get("error")):
        knowledge_store_sync.mark_dirty()
        knowledge_store_sync.flush_if_needed(force=True)

    return ResumeIngestionOutput(
        resumes=new_resumes,
        new_resumes=new_resumes,
        removed_files=removed_list,
        embedded_candidate_ids=sorted(embedded_candidate_ids),
        removed_candidate_ids=sorted(removed_candidate_ids),
        knowledge_path=str(knowledge_target),
        collection_name=collection_name,
        warnings=warnings,
        elapsed_seconds=elapsed,
    )


def ingest_new_resumes(
    file_infos: Sequence[ResumeFileInfo],
    *,
    removed_files: Sequence[ResumeFileInfo] | None = None,
    knowledge_path: Optional[Path] = None,
    collection_name: str = RESUME_COLLECTION_NAME,
    rebuild_embeddings: bool = True,
) -> ResumeIngestionOutput:
    knowledge_target = Path(knowledge_path).resolve() if knowledge_path else None
    return apply_ingestion_updates(
        file_infos,
        removed_files=removed_files,
        knowledge_path=knowledge_target,
        collection_name=collection_name,
        rebuild_embeddings=rebuild_embeddings,
    )


def bootstrap_resume_pipeline(
    *,
    auto_ingest: bool = True,
    rebuild_embeddings: bool = True,
    force: bool = False,
) -> Tuple[ResumeMonitorOutput, Optional[ResumeIngestionOutput]]:
    if _PIPELINE_STATE["ran"] and not force:
        return (
            _PIPELINE_STATE["monitor"] or ResumeMonitorOutput(),
            _PIPELINE_STATE["ingestion"],
        )

    monitor_output, new_files = run_resume_folder_monitor()

    ingestion_output: Optional[ResumeIngestionOutput] = None
    needs_update = bool(new_files or monitor_output.removed_files)

    if auto_ingest and needs_update:
        ingestion_output = ingest_new_resumes(
            new_files,
            removed_files=monitor_output.removed_files,
            knowledge_path=_resolve_knowledge_path(),
            collection_name=RESUME_COLLECTION_NAME,
            rebuild_embeddings=rebuild_embeddings,
        )
        logger.info(
            "Ingestion pipeline processed %s resume(s)",
            len(ingestion_output.new_resumes)
            if ingestion_output and ingestion_output.new_resumes
            else len(new_files),
        )
    else:
        logger.info("Ingestion skipped: auto_ingest=%s, needs_update=%s", auto_ingest, needs_update)

    _PIPELINE_STATE.update(
        {
            "monitor": monitor_output,
            "ingestion": ingestion_output,
            "ran": True,
        }
    )

    return monitor_output, ingestion_output


__all__ = [
    "apply_ingestion_updates",
    "bootstrap_resume_pipeline",
    "ingest_new_resumes",
    "run_resume_folder_monitor",
    "_compute_file_hash",
]
