"""Utility script to exercise the QueryManager crew in isolation."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from resume_screening_rag_automation.core.py_models import (
    AppState,
    ChatMessage,
    ConversationPhase,
    QueryControls,
)
from resume_screening_rag_automation.crews.query_manager_crew.query_manager_crew import (
    QueryManagerCrew,
)
from resume_screening_rag_automation.session_memory import (
    SessionMemoryBundle,
    create_session_memory_bundle,
)

USE_MEM0_MEMORY = os.getenv("RESUME_ASSISTANT_USE_MEM0", "").strip().lower() in {
    "1",
    "true",
    "yes",
}

SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "Initial request for finding candidates",
        "user_query": "Hi, I'm hiring a Senior Electrical & Automation Engineer in Denmark and need to find candidates.",
        "controls": {
            "phase_sequence": [],
            "last_completed_phase": None,
            "jd_complete": False,
            "allow_jd_incomplete": False,
            "update_jd": False,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": False,
        },
        "history": [],
        "expectations": {
            "phase_sequence": ["job_description"],
            "flags": {"update_jd": True},
        },
    },
    {
        "name": "JD tweak while snapshot incomplete",
        "user_query": "Please update the job to highlight 10 years of experience.",
        "controls": {
            "phase_sequence": ["job_description"],
            "last_completed_phase": "job_description",
            "jd_complete": False,
            "allow_jd_incomplete": False,
            "update_jd": True,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": False,
        },
        "previous_plan": "job_description",
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:16:49Z",
                "content": "Hi, I'm hiring a Senior Electrical & Automation Engineer in Denmark with Siemens stack, and 15 years of experience and need to find candidates.",
            },
            {
                "role": "assistant",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:18:43Z",
                "content": "Great! I'm excited to assist you in finding candidates for this important role. Captured the title of the job, location, skills, and experience. I would recommend reviewing the job snapshot and add recommended details of the job for better screening.",
            },
        ],
        "expectations": {
            "phase_sequence": ["job_description"],
            "flags": {"update_jd": True},
        },
    },
    {
        "name": "Approve screening despite incomplete JD",
        "user_query": "yes, start screening.",
        "controls": {
            "phase_sequence": ["job_description"],
            "last_completed_phase": "job_description",
            "jd_complete": False,
            "allow_jd_incomplete": False,
            "update_jd": True,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": False,
        },
        "previous_plan": "job_description",
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:16:49Z",
                "content": "Here are the basics for the automation engineer in Denmark: Siemens PCS 7, SCADA, PLC, and 10 years experience.",
            },
            {
                "role": "assistant",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:18:43Z",
                "content": "Captured the automation JD with Denmark location, Siemens stack, and 10 years experience. I would recommend reviewing the job snapshot and add recommended details of the job for better screening. or Ready to move to screening now if you want.",
            },
        ],
        "expectations": {
            "phase_sequence": ["screening"],
            "flags": {"allow_jd_incomplete": True},
        },
    },
    {
        "name": "Start screening with complete JD",
        "user_query": "Great, the job profile looks good. Begin screening candidates, please.",
        "controls": {
            "phase_sequence": ["job_description"],
            "last_completed_phase": "job_description",
            "jd_complete": False,
            "allow_jd_incomplete": False,
            "update_jd": True,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": False,
        },
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:41:14Z",
                "content": "Here are all the details for the job,",
            },
            {
                "role": "assistant",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:18:43Z",
                "content": "Snapshot now includes Denmark, Siemens tools, and 10 years experience. we have a complete job description. We're all set—no open fields remaining. Ready when you want screening.",
            },
        ],
        "expectations": {
            "phase_sequence": ["screening"],
            "flags": {"allow_jd_incomplete": True},
        },
    },
    {
        "name": "Move into discussion after screening",
        "user_query": "Let's discuss the shortlisted candidates and explain why do you think they are the right fit for the role.",
        "controls": {
            "phase_sequence": ["screening"],
            "last_completed_phase": "screening",
            "jd_complete": True,
            "allow_jd_incomplete": True,
            "update_jd": False,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": True,
        },
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:28:01Z",
                "content": "screen candidates for this role.",
            },
            {
                "role": "assistant",
                "phase": "screening",
                "timestamp": "2025-11-14T14:32:16Z",
                "content": "Shortlisted Romashchenko (0.88), Abhiram (0.73), and Prasad (0.64). Romashchenko leads with Siemens PCS 7 experience.",
            },
        ],
        "expectations": {
            "phase_sequence": ["discussion"],
            "flags": {"candidates_ready": True},
        },
    },
    {
        "name": "Revisit JD after screening feedback",
        "user_query": "i want to update the responsibilities.",
        "controls": {
            "phase_sequence": ["screening"],
            "last_completed_phase": "screening",
            "jd_complete": False,
            "allow_jd_incomplete": True,
            "update_jd": False,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": True,
        },
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:28:01Z",
                "content": "screen candidates for this role.",
            },
            {
                "role": "assistant",
                "phase": "screening",
                "timestamp": "2025-11-14T14:32:16Z",
                "content": "Shortlisted Romashchenko (0.88), Abhiram (0.73), and Prasad (0.64). Romashchenko leads with Siemens PCS 7 experience.",
            },
        ],
        "expectations": {
            "phase_sequence": ["job_description"],
            "flags": {"update_jd": True},
        },
    },
    {
        "name": "Rerun screening request",
        "user_query": "Please run the screening again for 10 more candidates.",
        "controls": {
            "phase_sequence": ["screening"],
            "last_completed_phase": "screening",
            "jd_complete": True,
            "allow_jd_incomplete": True,
            "update_jd": False,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": False,
        },
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:28:01Z",
                "content": "screen candidates for this role.",
            },
            {
                "role": "assistant",
                "phase": "screening",
                "timestamp": "2025-11-14T14:32:16Z",
                "content": "Shortlisted Romashchenko (0.88), Abhiram (0.73), and Prasad (0.64). Romashchenko leads with Siemens PCS 7 experience.",
            },
        ],
        "expectations": {
            "phase_sequence": ["screening"],
            "flags": {
                "allow_jd_incomplete": True,
                "screen_again": True,
                "top_k_hint": 10,
                "jd_complete": True,
            },
        },
    },
    {
        "name": "Start fresh with new job search",
        "user_query": "Thank you. those candidate results are good. now, I want to make a new search for a new job for a logistics manager role",
        "controls": {
            "phase_sequence": ["screening"],
            "last_completed_phase": "screening",
            "jd_complete": True,
            "allow_jd_incomplete": True,
            "update_jd": False,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": True,
        },
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:28:01Z",
                "content": "screen candidates for this role.",
            },
            {
                "role": "assistant",
                "phase": "screening",
                "timestamp": "2025-11-14T14:32:16Z",
                "content": "Shortlisted Romashchenko (0.88), Abhiram (0.73), and Prasad (0.64). Romashchenko leads with Siemens PCS 7 experience.",
            },
        ],
        "expectations": {
            "phase_sequence": ["job_description"],
            "flags": {"new_job_search": True}
        },
    },
    {
        "name": "All controls toggled on",
        "user_query": "make a new fresh screening with the following changes in the jd, and screen immediately. change the number of candidates to 10, and expereince to 5 years",
        "controls": {
            "phase_sequence": ["discussion"],
            "last_completed_phase": "discussion",
            "jd_complete": True,
            "allow_jd_incomplete": True,
            "update_jd": False,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": True,
        },
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:28:01Z",
                "content": "screen candidates for this role.",
            },
            {
                "role": "assistant",
                "phase": "screening",
                "timestamp": "2025-11-14T14:32:16Z",
                "content": "Shortlisted Romashchenko (0.88), Abhiram (0.73), and Prasad (0.64). Romashchenko leads with Siemens PCS 7 experience.",
            },
            {
                "role": "user",
                "phase": "screening",
                "timestamp": "2025-11-14T14:58:22Z",
                "content": "explain why romashchenko is a great fit for the role.",
            },
            {
                "role": "assistant",
                "phase": "discussion",
                "timestamp": "2025-11-14T14:58:22Z",
                "content": "Romashchenko can lead PCS 7 upgrades and mentor the controls team across plants.",
            },
        ],
        "expectations": {
            "phase_sequence": ["job_description", "screening"],
            "flags": {"update_jd": True, "screen_again": True, "allow_jd_incomplete": True},
            "top_k_hint": 10,
        },
    },
    {
        "name": "Start sourcing while JD still in flux",
        "user_query": "I know the job description isn't complete yet, but please start pulling a few candidate resumes anyway.",
        "controls": {
            "phase_sequence": ["job_description"],
            "last_completed_phase": "job_description",
            "jd_complete": False,
            "allow_jd_incomplete": False,
            "update_jd": True,
            "screen_again": False,
            "new_job_search": False,
            "candidates_ready": False,
        },
        "previous_plan": "job_description",
        "history": [
            {
                "role": "user",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:41:14Z",
                "content": "Here are all the details for the job.",
            },
            {
                "role": "assistant",
                "phase": "job_description",
                "timestamp": "2025-11-14T14:20:05Z",
                "content": "We still need certification preferences and travel requirements to complete the jobs description. this will allow me to get appropriate candidates matching with your requirements.",
            },
        ],
        "expectations": {
            "phase_sequence": ["screening"],
            "flags": {"allow_jd_incomplete": True},
        },
    },
]

def _print_result(result: Any) -> None:
    """Pretty-print the task output from a crew kickoff."""

    payload = getattr(result, "pydantic", None)
    if payload is not None:
        print(payload.model_dump_json(indent=2))
        return

    json_dict = getattr(result, "json_dict", None)
    if json_dict is not None:
        print(json.dumps(json_dict, indent=2, ensure_ascii=False))
        return

    raw = getattr(result, "raw", None)
    if raw:
        print(raw)
        return

    print(result)


def main() -> None:
    summaries: List[Dict[str, Any]] = []
    for idx, scenario in enumerate(SCENARIOS, start=1):
        session_id = f"kickoff-demo-{idx}"
        controls = QueryControls(**scenario["controls"])
        memory_bundle: SessionMemoryBundle = create_session_memory_bundle(
            session_id,
            use_mem0=USE_MEM0_MEMORY,
        )
        memory_bundle.activate()
        conversation_history_entries = []
        for history_item in scenario.get("history", []):
            phase_value = history_item.get("phase")
            phase_enum: Optional[ConversationPhase] = None
            if phase_value:
                try:
                    phase_enum = ConversationPhase(phase_value)
                except ValueError:
                    phase_enum = None
            message = ChatMessage(
                role=history_item.get("role", "assistant"),
                content_md=history_item.get("content", ""),
                phase=phase_enum,
            )
            memory_bundle.record_message(message)
            conversation_history_entries.append(
                {
                    "role": message.role,
                    "phase": phase_value,
                    "timestamp": history_item.get("timestamp"),
                    "content": message.content_md,
                }
            )

        current_message = ChatMessage(role="user", content_md=scenario["user_query"])
        memory_bundle.record_message(current_message)
        manager = QueryManagerCrew(
            session_id=session_id,
            memory_kwargs=memory_bundle.crew_kwargs(),
        )
        crew = manager.crew()

        print(f"\n=== Scenario {idx}: {scenario['name']} ===")
        print(f"User query: {scenario['user_query']}")
        print("Input controls:")
        print(controls.model_dump_json(indent=2))

        last_phase_raw: Optional[str] = controls.last_completed_phase
        last_phase_enum = None
        if last_phase_raw:
            try:
                last_phase_enum = ConversationPhase(last_phase_raw)
            except ValueError:
                last_phase_enum = None

        pending_phases = []
        for phase in controls.phase_sequence or []:
            try:
                pending_phases.append(ConversationPhase(phase))
            except ValueError:
                continue

        routing_state = AppState(
            job_description=None,
            candidate_insights=[],
            last_completed_phase=last_phase_enum,
            pending_phases=pending_phases,
            query_controls=controls,
        )

        conversation_history = conversation_history_entries + [
            {
                "role": current_message.role,
                "phase": last_phase_raw,
                "timestamp": None,
                "content": current_message.content_md,
            }
        ]

        inputs = {
            "user_query": scenario["user_query"],
            "last_phase": last_phase_raw or "",
            "previous_plan": scenario.get("previous_plan", ""),
            "query_control": controls.model_dump_json(indent=2),
            "session_id": session_id,
            "state": json.dumps(routing_state.model_dump(mode="json"), indent=2, ensure_ascii=False),
            "conversation_history": json.dumps(conversation_history, indent=2, ensure_ascii=False),
        }

        result = crew.kickoff(inputs=inputs)

        payload = getattr(result, "pydantic", None)
        if payload is not None:
            output_controls = payload.query_controls.model_dump()
            expectations = scenario.get("expectations", {})
            expected_phases = expectations.get("phase_sequence")
            expected_flags: Dict[str, Any] = expectations.get("flags", {})
            forbidden_flags: Dict[str, Any] = expectations.get("forbidden_flags", {})
            expected_top_k = expectations.get("top_k_hint")

            phase_match = expected_phases is None or output_controls.get("phase_sequence") == expected_phases
            flag_mismatches: Dict[str, Dict[str, Any]] = {}
            for key, expected_value in expected_flags.items():
                actual_value = output_controls.get(key)
                if actual_value != expected_value:
                    flag_mismatches[key] = {
                        "expected": expected_value,
                        "actual": actual_value,
                    }

            for key, forbidden_value in forbidden_flags.items():
                actual_value = output_controls.get(key)
                if actual_value == forbidden_value:
                    flag_mismatches[key] = {
                        "expected_not": forbidden_value,
                        "actual": actual_value,
                    }

            actual_top_k = getattr(payload, "top_k_hint", None)
            top_k_match = expected_top_k is None or actual_top_k == expected_top_k

            summaries.append(
                {
                    "name": scenario["name"],
                    "input_controls": controls.model_dump(),
                    "output_controls": output_controls,
                    "expected_phases": expected_phases,
                    "expected_flags": expected_flags,
                    "phase_match": phase_match,
                    "flag_mismatches": flag_mismatches,
                    "expected_top_k": expected_top_k,
                    "actual_top_k": actual_top_k,
                    "top_k_match": top_k_match,
                }
            )

        _print_result(result)

    if summaries:
        total = len(summaries)
        matched = sum(
            1
            for item in summaries
            if item["phase_match"] and not item["flag_mismatches"] and item["top_k_match"]
        )
        print(f"\n=== Scenario Summary ({matched}/{total} matched expectations) ===")
        for item in summaries:
            status = "PASS" if item["phase_match"] and not item["flag_mismatches"] else "CHECK"
            print(f"{item['name']} -> {status}")
            print(f"  input phases:  {item['input_controls'].get('phase_sequence')}")
            print(f"  output phases: {item['output_controls'].get('phase_sequence')}")
            if item["expected_phases"] is not None:
                print(f"  expected phases: {item['expected_phases']}")
                if not item["phase_match"]:
                    print("  ⚠︎ Phase sequence mismatch")
            if item["expected_flags"]:
                print(f"  expected flags: {item['expected_flags']}")
                actual_subset = {
                    key: item["output_controls"].get(key)
                    for key in item["expected_flags"]
                }
                print(f"  actual flags:   {actual_subset}")
            if item["flag_mismatches"]:
                print(f"  ⚠︎ Flag mismatches: {item['flag_mismatches']}")
            if item["expected_top_k"] is not None:
                print(f"  expected top_k_hint: {item['expected_top_k']}")
                print(f"  actual top_k_hint:   {item['actual_top_k']}")
                if not item["top_k_match"]:
                    print("  ⚠︎ top_k_hint mismatch")


if __name__ == "__main__":
    main()
