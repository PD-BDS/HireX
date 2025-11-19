"""CLI script to detect resume changes and run the ResumeParsingCrew end-to-end."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resume_screening_rag_automation.core.ingestion_models import (
    ResumeIngestionOutput,
    ResumeMonitorOutput,
)
from resume_screening_rag_automation.paths import RAW_RESUME_DIR
from resume_screening_rag_automation.services.ingestion import (
    apply_ingestion_updates,
    run_resume_folder_monitor,
)

LOGGER = logging.getLogger("resume_pipeline_check")


def _serialise_model(model: Any) -> dict[str, Any]:
    if model is None:
        return {}
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")  # type: ignore[call-arg]
    return dict(model)


def _print_section(title: str, payload: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _report_monitor(monitor_output: ResumeMonitorOutput) -> None:
    payload = _serialise_model(monitor_output)
    payload.setdefault("new_files", [])
    payload.setdefault("removed_files", [])
    payload.setdefault("duplicate_files", [])
    _print_section("MonitorOutput", payload)

    new_count = len(monitor_output.new_files)
    removed_count = len(monitor_output.removed_files)
    duplicate_count = len(monitor_output.duplicate_files)
    LOGGER.info(
        "Detected %s new, %s removed, %s duplicate resume(s)",
        new_count,
        removed_count,
        duplicate_count,
    )


def _run_ingestion(
    monitor_output: ResumeMonitorOutput,
    *,
    knowledge_path: Path | None,
    rebuild_embeddings: bool,
) -> ResumeIngestionOutput | None:
    if not monitor_output.new_files and not monitor_output.removed_files:
        LOGGER.info("No changes detected in %s; ingestion skipped.", RAW_RESUME_DIR)
        return None

    LOGGER.info("Running ResumeParsingCrew and updating structured_resumes.json / Chroma...")
    output = apply_ingestion_updates(
        monitor_output.new_files,
        removed_files=monitor_output.removed_files,
        knowledge_path=knowledge_path,
        rebuild_embeddings=rebuild_embeddings,
    )

    payload = _serialise_model(output)
    _print_section("IngestionOutput", payload)

    if output.warnings:
        LOGGER.warning("Pipeline completed with warnings:")
        for warning in output.warnings:
            LOGGER.warning(" - %s", warning)

    LOGGER.info(
        "Knowledge base updated at %s; %s candidate(s) embedded.",
        output.knowledge_path,
        len(output.embedded_candidate_ids),
    )

    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            f"Inspect {RAW_RESUME_DIR} for new resumes, run the ResumeParsingCrew, and update structured_resumes.json and Chroma."
        )
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=None,
        help="Override the structured_resumes.json path (defaults to auto-detected file).",
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip Chroma synchronisation (JSON will still be updated).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (e.g. INFO, DEBUG).",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    monitor_output, _ = run_resume_folder_monitor()
    _report_monitor(monitor_output)

    _run_ingestion(
        monitor_output,
        knowledge_path=args.knowledge,
        rebuild_embeddings=not args.no_embeddings,
    )

    print("\nDone. Review the sections above for parsing results and persistence details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
