"""Command-line harness for smoke testing the resume screening Flow."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Iterable, List, Optional

from resume_screening_rag_automation.app import (
    FlowExecutionError,
    initialise_session,
    process_user_message,
)
from resume_screening_rag_automation.models import ChatMessage
from resume_screening_rag_automation.state import persist_session
from resume_screening_rag_automation.storage_sync import knowledge_store_sync

LOGGER = logging.getLogger(__name__)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _render_messages(messages: Iterable[ChatMessage]) -> None:
    for message in messages:
        print("\nAssistant:\n")
        print(message.content_md.strip())
        print()


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the resume screening assistant in the terminal")
    parser.add_argument("--session", help="Existing session identifier to resume", default=None)
    parser.add_argument(
        "--knowledge-session",
        help="Optional knowledge session identifier to reuse",
        default=None,
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write session updates back to disk",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


def run_cli(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)
    knowledge_store_sync.ensure_local_copy()

    chat_state, knowledge_state = initialise_session(
        session_id=args.session,
        knowledge_session_id=args.knowledge_session,
    )

    print("Resume Screening Assistant CLI")
    print("Type 'exit' or press Ctrl+C to leave.\n")
    print(f"Active session: {chat_state.session_id}")
    if knowledge_state.knowledge_session_id:
        print(f"Knowledge session: {knowledge_state.knowledge_session_id}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break

        try:
            responses, chat_state, knowledge_state, flow_state = process_user_message(
                user_input,
                chat_state=chat_state,
                knowledge_state=knowledge_state,
                persist=not args.no_persist,
            )
        except FlowExecutionError as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Flow execution failed: %s", exc)
            chat_state = exc.state.chat_state
            knowledge_state = exc.state.knowledge_state
            print("\nAssistant:\n\nI hit an internal error processing that turn. Please try again.\n")
            continue

        response_messages = responses or []
        if not response_messages:
            print("\nAssistant: (no response produced)\n")
        else:
            _render_messages(response_messages)

        if args.verbose:
            execution_plan = [phase.value for phase in flow_state.execution_plan]
            completed = [phase.value for phase in flow_state.completed_phases]
            controls_dump = flow_state.chat_state.query_controls.model_dump()
            print("Routing plan:", execution_plan)
            print("Completed phases:", completed)
            print("Query controls:\n" + json.dumps(controls_dump, indent=2))

    if not args.no_persist:
        persist_session(chat_state, knowledge_state)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
