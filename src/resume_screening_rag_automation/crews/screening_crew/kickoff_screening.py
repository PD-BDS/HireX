"""Utility script to exercise the Screening crew in isolation."""

from __future__ import annotations

import json
from typing import Any

from resume_screening_rag_automation.core.py_models import JobDescription, JobType, ScreeningInput
from resume_screening_rag_automation.crews.screening_crew.screening_crew import (
    ScreeningCrew,
)
from resume_screening_rag_automation.state import ChatSessionState


def _print_result(result: Any) -> None:
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
    session_id = "kickoff-demo"
    crew = ScreeningCrew(session_id=session_id).crew()

    job_snapshot = JobDescription(
        job_title="Senior Electrical and Automation Engineer",
        location="Denmark (Copenhagen / Aalborg / Aarhus)",
        experience_level_years=10,
        required_skills=[
            "Siemens PCS 7",
            "TIA Portal",
            "CEMAT S7",
            "SCADA environments",
            "PLC programming",
            "HMI software development",
            "EPLAN",
            "AutoCAD",
            "process instrumentation",
            "project management",
        ],
        job_responsibilities=[
            "Lead the design, configuration, and implementation of process control systems (PCS) for industrial plants, including cement, industrial gas, and manufacturing facilities.",
            "Develop and maintain PLC and HMI software, primarily using Siemens PCS 7, TIA Portal, and WinCC.",
            "Design electrical control cabinets, power supply systems (LV/MV), and instrumentation layouts using EPLAN and AutoCAD.",
            "Oversee the integration of instrumentation and field devices, ensuring accuracy, reliability, and compliance with safety standards.",
            "Manage full project lifecycle — from concept design, documentation, and FAT/SAT testing to commissioning and maintenance.",
            "Provide technical leadership for automation and electrical design teams, including mentoring and cross-functional collaboration.",
            "Troubleshoot, optimize, and maintain process control systems to ensure maximum plant uptime and operational efficiency.",
            "Collaborate with cross-disciplinary teams including mechanical, process, and electrical engineers to ensure seamless system integration.",
            "Conduct risk assessments, system testing, and validation of control system modifications and new installations.",
            "Support supplier quality inspections, FATs, and equipment acceptance.",
            "Maintain up-to-date documentation and participate in continuous improvement initiatives for engineering standards and processes.",
        ],
        education_requirements=[
            "Master’s Degree in Electrical Engineering or Industrial Automation (Kryvyi Rih National University or equivalent)",
        ],
        language_requirements=[
            "Fluent in English",
            "Working knowledge of Polish",
            "Working knowledge of Russian",
        ],
        job_type=JobType.full_time,
        outstanding_questions=[
            "Any certifications required or preferred?",
            "Any additional preferences or nice-to-haves?",
        ],
    )

    chat_state = ChatSessionState(session_id=session_id, job_snapshot=job_snapshot)

    inputs = ScreeningInput(
        user_query="Screen the top automation engineers who match the Danish Senior Electrical and Automation Engineer brief.",
        job_snapshot=job_snapshot,
        top_k=5,
        session_id=session_id,
    )

    chat_state.top_k = inputs.top_k
    chat_state.scoring_weights = inputs.scoring_weights
    chat_state.feature_weights = inputs.feature_weights

    kickoff_inputs = inputs.model_dump(mode="json")
    kickoff_inputs.update(
        {
            "job_snapshot": json.dumps(kickoff_inputs.get("job_snapshot", {}), indent=2, ensure_ascii=False),
            "scoring_weights": json.dumps(kickoff_inputs.get("scoring_weights", {}), indent=2, ensure_ascii=False),
            "feature_weights": json.dumps(kickoff_inputs.get("feature_weights", {}), indent=2, ensure_ascii=False),
            "candidate_insights": "[]",
            "retrieval_md": "",
            "candidates": "[]",
            "session_id": chat_state.session_id,
        }
    )

    result = crew.kickoff(inputs=kickoff_inputs)

    _print_result(result)


if __name__ == "__main__":
    main()
