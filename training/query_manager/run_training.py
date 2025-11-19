"""Utility to launch interactive training for the Query Manager crew."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List

from crewai.utilities.constants import TRAINING_DATA_FILE
from crewai.utilities.evaluators.task_evaluator import TaskEvaluator
from crewai.utilities.training_handler import CrewTrainingHandler

from resume_screening_rag_automation.crews.query_manager_crew.query_manager_crew import (
    QueryManagerCrew,
)

DEFAULT_TRAINING_FILE = Path(__file__).resolve().parent / "trained_query_manager.pkl"
SCENARIO_FILE = Path(__file__).resolve().parent / "scenarios.jsonl"


def load_scenarios() -> List[dict]:
    """Load the interactive training scenarios from disk."""

    if not SCENARIO_FILE.exists():
        raise FileNotFoundError(f"Missing scenario file: {SCENARIO_FILE}")

    scenarios: List[dict] = []
    with SCENARIO_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            scenarios.append(json.loads(line))

    if not scenarios:
        raise ValueError("No scenarios found in scenarios.jsonl")

    return scenarios


def normalize_inputs(raw: dict, session_id: str) -> dict:
    """Prepare structured inputs expected by the training harness."""

    controls = raw.get("query_control", {})
    query_control = json.dumps(controls, indent=2, sort_keys=True)
    conversation_history = raw.get("conversation_history", [])
    state_payload = raw.get("state") or {}
    return {
        "user_query": raw.get("user_query", ""),
        "last_phase": raw.get("last_phase", ""),
        "previous_plan": raw.get("previous_plan", ""),
        "query_control": query_control,
        "session_id": session_id,
        "conversation_history": json.dumps(conversation_history, indent=2, ensure_ascii=False),
        "state": json.dumps(state_payload, indent=2, ensure_ascii=False),
    }


def select_scenarios(all_scenarios: List[dict], selectors: Iterable[str]) -> List[dict]:
    """Filter down the scenario set based on indexes or names."""

    if not selectors:
        return all_scenarios

    selected: List[dict] = []
    normalized = {entry["name"].lower(): entry for entry in all_scenarios}

    for token in selectors:
        token_lower = token.lower()
        if token_lower.isdigit():
            index = int(token_lower) - 1
            if index < 0 or index >= len(all_scenarios):
                raise IndexError(f"Scenario index out of range: {token}")
            selected.append(all_scenarios[index])
            continue

        matched = normalized.get(token_lower)
        if matched is None:
            raise KeyError(f"Unknown scenario selector: {token}")
        selected.append(matched)

    return selected


def _extract_payloads(training_dump: dict) -> List[dict]:
    """Pull initial/improved/feedback triplets out of the training dump."""

    if not training_dump:
        return []

    payloads: List[dict] = []
    _, agent_entries = next(iter(training_dump.items()))

    sorted_items = sorted(
        agent_entries.items(),
        key=lambda item: int(item[0]) if isinstance(item[0], str) and item[0].isdigit() else item[0],
    )
    for _, entry in sorted_items:
        if all(entry.get(field) for field in ("initial_output", "human_feedback", "improved_output")):
            payloads.append(entry)

    return payloads


def run_training(filename: Path, iterations: int, selectors: Iterable[str]) -> None:
    """Execute interactive training across the selected scenarios."""

    scenarios = load_scenarios()
    targets = select_scenarios(scenarios, selectors)

    filename = filename.resolve()
    print(f"Training data will be stored in: {filename}")
    print("Press Ctrl+C to exit at any time.\n")

    aggregated_iterations: List[dict] = []
    agent_role: str | None = None

    for index, entry in enumerate(targets, start=1):
        scenario_name = entry.get("name", f"Scenario {index}")
        expectations = entry.get("expectations", {})
        feedback_hints = expectations.get("feedback", [])
        expected_phases = expectations.get("phase_sequence")
        expected_flags = expectations.get("flags", {})

        print("=" * 80)
        print(f"Scenario {index}: {scenario_name}")
        print(f"User query          : {entry['inputs']['user_query']}")
        print(f"Last completed phase: {entry['inputs'].get('last_phase', '')}")
        if entry["inputs"].get("previous_plan"):
            print(f"Previous plan       : {entry['inputs']['previous_plan']}")
        print(f"Expected phases     : {expected_phases}")
        print(f"Expected flags      : {expected_flags}")
        if feedback_hints:
            print("Feedback reminders  :")
            for hint in feedback_hints:
                print(f"  - {hint}")

        session_id = f"training-{index:02d}"
        inputs = normalize_inputs(entry["inputs"], session_id=session_id)

        crew = QueryManagerCrew(session_id=session_id).crew()
        print("\nStarting interactive training run...")
        crew.train(
            n_iterations=iterations,
            inputs=inputs,
            filename=str(filename),
        )
        print("Training iteration complete.\n")

        agent_role = agent_role or crew.agents[0].role

        raw_training = CrewTrainingHandler(TRAINING_DATA_FILE).load()
        payloads = _extract_payloads(raw_training)
        if not payloads:
            print("No training data captured for this scenario; skipping aggregation.\n")
            continue

        aggregated_iterations.extend(payloads)

    if not aggregated_iterations:
        raise RuntimeError("No training data collected; ensure scenarios were completed with feedback.")

    evaluation_crew = QueryManagerCrew(session_id="training-aggregate").crew()
    if agent_role is None:
        agent_role = evaluation_crew.agents[0].role

    target_agent = next(
        (agent for agent in evaluation_crew.agents if agent.role == agent_role),
        evaluation_crew.agents[0],
    )
    target_agent_id = str(target_agent.id)

    aggregated_training_data = {
        target_agent_id: {
            iteration: payload for iteration, payload in enumerate(aggregated_iterations)
        }
    }

    training_handler = CrewTrainingHandler(TRAINING_DATA_FILE)
    training_handler.save(aggregated_training_data)

    evaluation = TaskEvaluator(target_agent).evaluate_training_data(
        training_data=aggregated_training_data,
        agent_id=target_agent_id,
    )

    trained_handler = CrewTrainingHandler(str(filename))
    trained_handler.initialize_file()
    trained_handler.save_trained_data(
        agent_id=agent_role,
        trained_data=evaluation.model_dump(),
    )

    print("Aggregated training saved. Suggestions:")
    for suggestion in evaluation.suggestions:
        print(f" - {suggestion}")
    print(f"Quality score: {evaluation.quality}\n")


def main() -> None:
    """Entry point for the CLI wrapper."""

    parser = argparse.ArgumentParser(
        description="Launch interactive training for the Query Manager crew",
    )
    parser.add_argument(
        "--filename",
        type=Path,
        default=DEFAULT_TRAINING_FILE,
        help="Path to save the consolidated training artifact (.pkl).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of training iterations to run per scenario (positive integer).",
    )
    parser.add_argument(
        "--scenario",
        dest="selectors",
        action="append",
        default=[],
        help="Optional scenario name or 1-based index to focus training. Can be repeated.",
    )

    args = parser.parse_args()

    if args.iterations <= 0:
        raise ValueError("Number of iterations must be a positive integer")

    run_training(
        filename=args.filename,
        iterations=args.iterations,
        selectors=args.selectors,
    )


if __name__ == "__main__":
    main()
